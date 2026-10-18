local UEHelpers = require("UEHelpers")
local Terrain = require("terrain")

local Vegetation = {
    actor = nil,
    component = nil,
    components = {},
    generation = 0,
    overlay = nil,
    hidden = nil,
}

local DEFAULT_MESH =
    "/Game/Meshes/Mountain/SM_Spruce_15m.SM_Spruce_15m"
-- ISM insertion/refresh may copy the component's existing instance buffer.
-- Bound that buffer as well as the Lua batch: one 250k-instance component
-- becomes increasingly expensive to update, particularly during save travel.
local COMPONENT_CAPACITY = 8192
local MAX_POINTS = 1000000
local DRAW_INSTANCING = 'r.MeshDrawCommands.DynamicInstancing'

local function valid(object)
    return object and object:IsValid()
end

local function stable_draw_commands()
    local system=UEHelpers.GetKismetSystemLibrary()
    assert(valid(system), 'vegetation render settings are unavailable')
    Vegetation.previous_draw_instancing=system:GetConsoleVariableIntValue(DRAW_INSTANCING)
    system:ExecuteConsoleCommand(UEHelpers.GetWorld(), DRAW_INSTANCING..' 0', UEHelpers.GetPlayerController())
end

local function identity_transform()
    return {
        Rotation = { X = 0.0, Y = 0.0, Z = 0.0, W = 1.0 },
        Translation = { X = 0.0, Y = 0.0, Z = 0.0 },
        Scale3D = { X = 1.0, Y = 1.0, Z = 1.0 },
    }
end

local function load_asset(path)
    local asset = StaticFindObject(path)
    if valid(asset) then return asset end
    local ok, loaded = pcall(LoadAsset, path)
    if ok and valid(loaded) then return loaded end
    return nil
end

function Vegetation.parse_skxy(bytes)
    if type(bytes) ~= "string" or #bytes < 12 then
        error("SKXY vegetation source is truncated", 2)
    end
    local magic = bytes:sub(1, 4)
    local function uint32_le(offset)
        local first, second, third, fourth = bytes:byte(offset, offset + 3)
        return first + second * 256 + third * 65536 + fourth * 16777216
    end
    local version, count = uint32_le(5), uint32_le(9)
    if magic ~= "SKXY" or version ~= 1 then
        error("unsupported SKXY vegetation source", 2)
    end
    if count > MAX_POINTS or #bytes ~= 12 + count * 8 then
        error("invalid SKXY vegetation source length", 2)
    end
    return count
end


function Vegetation.unload()
    Vegetation.generation = Vegetation.generation + 1
    local actor = Vegetation.actor
    Vegetation.actor, Vegetation.component = nil, nil
    Vegetation.components = {}
    Vegetation.overlay, Vegetation.hidden = nil, nil
    if Vegetation.previous_draw_instancing~=nil then
        local previous=Vegetation.previous_draw_instancing
        Vegetation.previous_draw_instancing=nil
        local system=UEHelpers.GetKismetSystemLibrary()
        if valid(system) then
            system:ExecuteConsoleCommand(UEHelpers.GetWorld(), DRAW_INSTANCING..' '..previous, UEHelpers.GetPlayerController())
        end
    end
    if valid(actor) then
        ExecuteInGameThread(function()
            if valid(actor) then actor:K2_DestroyActor() end
        end)
    end
end

-- The native view button changes the world's obstacle fade state. Portable
-- trees live in their own ISM actor, so they must follow that same state.
function Vegetation.sync_visibility()
    local world = UEHelpers.GetWorld()
    local actor = Vegetation.actor
    if not valid(world) or not valid(actor)
        or actor:GetWorld():GetAddress() ~= world:GetAddress() then return end
    local overlay = Vegetation.overlay
    if not valid(overlay)
        or overlay:GetWorld():GetAddress() ~= world:GetAddress() then
        overlay = nil
        for _, candidate in ipairs(FindAllOf("TerrainOverlaySubsystem") or {}) do
            if valid(candidate) and candidate:GetWorld():GetAddress() == world:GetAddress() then
                overlay = candidate
                break
            end
        end
        Vegetation.overlay = overlay
    end
    if not valid(overlay) then return end
    local hidden = overlay:GetObstacleFadeLevel() == 1
    if Vegetation.hidden ~= hidden then
        actor:SetActorHiddenInGame(hidden)
        Vegetation.hidden = hidden
    end
end

local function create_renderer(mesh_path, cull_distance)
    local world = UEHelpers.GetWorld()
    local gameplay = UEHelpers.GetGameplayStatics()
    local actor_class = StaticFindObject("/Script/Engine.Actor")
    -- The stock obstacle renderer uses plain ISM components. HISM starts an
    -- asynchronous cluster-tree rebuild while instances are still arriving;
    -- on this UE build that races the next Lua insertion at roughly 8k
    -- instances. ISM keeps the same GPU instancing without that mutable tree.
    local component_class = StaticFindObject(
        "/Script/Engine.InstancedStaticMeshComponent")
    local mesh = load_asset(mesh_path)
    assert(valid(world), "vegetation world is unavailable")
    assert(valid(gameplay), "GameplayStatics is unavailable")
    assert(valid(actor_class), "vegetation Actor class is unavailable")
    assert(valid(component_class), "ISM component class is unavailable")
    assert(valid(mesh), "vegetation mesh is unavailable: " .. mesh_path)

    local transform = identity_transform()
    local actor = gameplay:BeginDeferredActorSpawnFromClass(
        world, actor_class, transform, 1, nil, 0)
    assert(valid(actor), "could not spawn vegetation renderer")
    actor = gameplay:FinishSpawningActor(actor, transform, 0)
    assert(valid(actor), "could not finish vegetation renderer")
    local function add_component()
        assert(valid(actor), "vegetation renderer was destroyed")
        local component = actor:AddComponentByClass(
            component_class, false, transform, false)
        assert(valid(component), "could not create vegetation ISM")
        assert(component:SetStaticMesh(mesh), "could not assign vegetation mesh")
        component:SetCollisionEnabled(0)
        component:SetCullDistances(0, cull_distance)
        return component
    end
    return actor, add_component
end

local function refresh_component(component, count)
    if count == 0 then return end
    local first_transform = {}
    assert(component:GetInstanceTransform(0, first_transform, true),
        "first vegetation transform is unavailable")
    assert(component:UpdateInstanceTransform(0, first_transform, true, true, false),
        "vegetation render-state refresh failed")
end

-- Reconstruct a forest renderer from portable XY positions. Z, rotation and
-- scale are derived at load time, so the map never ships Unreal-cooked HISM
-- data. Work is split across frames to keep the game thread responsive.
local function load_points(count, point_at, api, options, done)
    options = options or {}
    done = done or function() end
    Vegetation.unload()
    local generation = Vegetation.generation
    local stride = math.max(1, math.floor(options.stride or 1))
    -- This is a per-callback insertion budget. Never submit the complete map
    -- as one Lua TArray: a quarter-million FTransforms is too large for the
    -- UE4SS marshaller. Conversely, issuing AddInstance once per tree queues
    -- hundreds of thousands of incremental scene-proxy updates and can make
    -- the GameThread time out while waiting for the RenderThread. Bounded
    -- AddInstances calls provide one native update per batch while preserving
    -- every portable source point.
    local batch_size = math.max(64, math.min(512,
        math.floor(options.batch_size or 256)))
    local minimum_scale = options.minimum_scale or 0.55
    local maximum_scale = options.maximum_scale or 0.95
    local scale_range = maximum_scale - minimum_scale
    local cull_distance = math.floor(options.cull_distance or 650000)
    local mesh_path = options.mesh or DEFAULT_MESH

    api:log(string.format(
        "creating portable forest renderer (%d source points, stride %d, batch %d)",
        count, stride, batch_size))
    local ok, actor_or_message, add_component = pcall(
        create_renderer, mesh_path, cull_distance)
    if not ok then done(tostring(actor_or_message)); return end
    Vegetation.actor = actor_or_message
    -- UE's cached mesh-command merging drops whole portable ISM instances
    -- on alternating frames. Keep ISM GPU batching, but disable that second
    -- optimization while this forest exists; restore the user's value on exit.
    if count>0 then
        local configured,message=pcall(stable_draw_commands)
        if not configured then Vegetation.unload();done(tostring(message));return end
    end
    Vegetation.sync_visibility()
    api:every(250, function()
        if Vegetation.generation ~= generation then return false end
        Vegetation.sync_visibility()
    end)
    api:log("portable forest renderer ready")

    local source_index, created = 1, 0
    local component, component_count = nil, 0
    local first_batch = true
    local function add_batch()
        if Vegetation.generation ~= generation then return end
        if first_batch then
            first_batch = false
            api:log("inserting first portable forest batch")
        end
        local batch_ok, batch_message = pcall(function()
            assert(valid(Vegetation.actor), "vegetation renderer was destroyed")
            if not component then
                component = add_component()
                Vegetation.component = Vegetation.component or component
                Vegetation.components[#Vegetation.components + 1] = component
            end
            assert(valid(component), "vegetation component was destroyed")
            local transforms = {}
            local scanned = 0
            local budget = math.min(batch_size, COMPONENT_CAPACITY - component_count)
            -- Off-terrain points count toward the budget too. Otherwise a
            -- malformed/outside forest can scan a million records in a frame.
            while source_index <= count and scanned < budget do
                local record = source_index
                source_index = source_index + stride
                scanned = scanned + 1
                local x, y = point_at(record)
                local z = Terrain.surface_height_at(x, y)
                if z then
                    -- Two inexpensive integer sequences give stable visual
                    -- variation without depending on Lua's global RNG state.
                    local yaw = (record * 137.50776405) % 360.0
                    local radians = math.rad(yaw * 0.5)
                    local scale = minimum_scale +
                        ((record * 2654435761) % 997) / 996.0 * scale_range
                    transforms[#transforms + 1] = {
                        Rotation = {
                            X = 0.0, Y = 0.0,
                            Z = math.sin(radians), W = math.cos(radians),
                        },
                        Translation = { X = x, Y = y, Z = z },
                        Scale3D = { X = scale, Y = scale, Z = scale },
                    }
                end
            end
            if #transforms > 0 then
                component:AddInstances(transforms, false, true, false)
                created = created + #transforms
                component_count = component_count + #transforms
            end
            if component_count == COMPONENT_CAPACITY or source_index > count then
                -- Refresh each bounded buffer once, rather than rebuilding a
                -- quarter-million-tree render buffer at the end of the load.
                refresh_component(component, component_count)
                component, component_count = nil, 0
            end
        end)
        if not batch_ok then
            Vegetation.unload()
            done(tostring(batch_message))
            return
        end
        api:loading_progress("Creating forest", 0.95 + 0.04 *
            (count == 0 and 1 or math.min(1, source_index / count)))
        if created > 0 and created % 4096 == 0 then
            api:log(string.format("portable forest progress: %d instances", created))
        end
        if source_index <= count then
            -- Give the render thread time to consume the preceding instance
            -- buffer update before the next native batch is enqueued.
            api:after(10, add_batch)
        else
            api:log(string.format("portable forest render buffers refreshed (%d components)",
                #Vegetation.components))
            done(nil, created, count)
        end
    end
    -- Never perform the first native bulk insertion from the map-ready
    -- callback itself. Yield once so landscape registration and other map
    -- reconstruction callbacks can finish unwinding first.
    api:after(1, add_batch)
end

function Vegetation.load_skxy(bytes, api, options, done)
    local count = Vegetation.parse_skxy(bytes)
    return load_points(count, function(record)
        return string.unpack("<ff", bytes, 13 + (record - 1) * 8)
    end, api, options, done)
end

return Vegetation
