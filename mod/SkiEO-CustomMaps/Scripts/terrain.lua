local UEHelpers = require("UEHelpers")
local Heightmap = require("heightmap")
local NativeTerrain = require("native_terrain")
local Textures = require("textures")
local Mesh = require("terrain_mesh")

-- The fresh Landscape initializes the native height, brush and snow systems.
-- Its compiled Landscape shader variants belong to cooked levels; the neutral
-- world renders source procedural meshes with the shared terrain/snow materials
-- instead. Rendering and collision sample the same portable R16 and transform.
local Terrain = {
    active = nil,
    actor = nil,
    component = nil,
    snow_component = nil,
    skirt_component = nil,
    trail_component = nil,
    generation = 0,
    callbacks = {},
    completed_callback = nil,
}

local MOD_NAME = "SkiEO-CustomMaps"

local function log(message)
    print(string.format("[%s] %s\n", MOD_NAME, tostring(message)))
end

local function valid(object)
    return object and object:IsValid()
end

-- UE4SS retains weak callback references. Keep each queued closure rooted
-- until it runs, and cancel work belonging to an unloaded terrain generation.
local function schedule(milliseconds, callback)
    local pending = {generation=Terrain.generation}
    Terrain.callbacks[pending] = pending
    pending.game = function()
        if pending.generation ~= Terrain.generation then
            Terrain.callbacks[pending] = nil
            return
        end
        -- Keep this wrapper rooted through the entire native invocation,
        -- including GC inside large mesh-argument conversion. The following
        -- callback replaces it only after the previous invocation returned.
        Terrain.completed_callback = pending
        callback()
        Terrain.callbacks[pending] = nil
    end
    if milliseconds == nil then
        ExecuteInGameThread(pending.game)
    elseif type(ExecuteInGameThreadWithDelay) == 'function' then
        ExecuteInGameThreadWithDelay(milliseconds,pending.game)
    else
        pending.delay = function() ExecuteInGameThread(pending.game) end
        ExecuteWithDelay(milliseconds,pending.delay)
    end
end
local function queue_game_thread(callback) schedule(nil,callback) end
local function defer_game_thread(milliseconds,callback) schedule(milliseconds,callback) end

local function belongs_to_world(object, world)
    if not valid(object) or not valid(world) then return false end
    local ok, object_world = pcall(function() return object:GetWorld() end)
    return ok and valid(object_world)
        and object_world:GetAddress() == world:GetAddress()
end

local function identity_transform()
    return {
        Rotation = { X = 0.0, Y = 0.0, Z = 0.0, W = 1.0 },
        Translation = { X = 0.0, Y = 0.0, Z = 0.0 },
        Scale3D = { X = 1.0, Y = 1.0, Z = 1.0 },
    }
end

function Terrain.height_at(x, y)
    local state = Terrain.active
    if not state then return nil end
    return Heightmap.height_at(state, x, y)
end

-- Tree roots follow the triangles actually rendered, including decimation
-- and adaptive cliff seams. Native simulation keeps its source-height API.
function Terrain.surface_height_at(x, y)
    local state = Terrain.active
    if not state then return nil end
    return Mesh.height_at(state, x, y)
end

function Terrain.is_active_in_current_world()
    local world = UEHelpers.GetWorld()
    return Terrain.active ~= nil and belongs_to_world(Terrain.actor, world)
end

local function hide_template_terrain(world)
    local hidden = 0
    for _, class_name in ipairs({
        "Landscape", "LandscapeStreamingProxy", "SnowShellActor",
        "TerrainSkirtActor", "ObstacleRendererActor",
    }) do
        for _, actor in ipairs(FindAllOf(class_name) or {}) do
            if belongs_to_world(actor, world) then
                pcall(function()
                    actor:SetActorHiddenInGame(true)
                    actor:SetActorEnableCollision(false)
                end)
                hidden = hidden + 1
            end
        end
    end
    return hidden
end

local function add_mesh_component(actor, component_class, transform, collision)
    local component = actor:AddComponentByClass(
        component_class, false, transform, false)
    assert(valid(component), "could not create ProceduralMeshComponent")
    component.bUseComplexAsSimpleCollision = collision
    component.bUseAsyncCooking = collision
    pcall(function() component:SetCollisionEnabled(collision and 3 or 0) end)
    return component
end

local function spawn_mesh_actor(world, with_snow, with_skirt)
    local gameplay = UEHelpers.GetGameplayStatics()
    assert(valid(gameplay), "GameplayStatics is unavailable")
    local actor_class = StaticFindObject("/Script/Engine.Actor")
    local component_class = StaticFindObject(
        "/Script/ProceduralMeshComponent.ProceduralMeshComponent")
    assert(valid(actor_class), "Actor class is unavailable")
    assert(valid(component_class), "ProceduralMeshComponent class is unavailable")
    local transform = identity_transform()
    local actor = gameplay:BeginDeferredActorSpawnFromClass(
        world, actor_class, transform, 1, nil, 0)
    assert(valid(actor), "could not spawn the terrain actor")
    actor = gameplay:FinishSpawningActor(actor, transform, 0)
    assert(valid(actor), "could not finish the terrain actor")
    actor:SetActorEnableCollision(true)
    local component = add_mesh_component(
        actor, component_class, transform, true)
    local snow_component = nil
    if with_snow then
        snow_component = add_mesh_component(
            actor, component_class, transform, false)
    end
    local skirt_component = nil
    if with_skirt then
        skirt_component = add_mesh_component(
            actor, component_class, transform, false)
    end
    return actor, component, snow_component, skirt_component
end

local sampled_indices = Mesh.sampled_indices
local build_tile = Mesh.build_tile

local function canonical_asset_path(path)
    if path:match("/[^/]+%.[^/]+$") then return path end
    local name = path:match("/([^/]+)$")
    return name and (path .. "." .. name) or path
end

local function load_material(path)
    local canonical = canonical_asset_path(path)
    local found = StaticFindObject(canonical)
    if valid(found) then return found, canonical end
    local ok, loaded = pcall(LoadAsset, canonical)
    if ok and valid(loaded) then return loaded, canonical end
    return nil, canonical
end

local function tint_material(material, color, label, owned_dynamic)
    if type(color) ~= "table" or #color < 3 then return material end
    if owned_dynamic then
        -- Tint the dynamic instance that already carries the terrain textures.
        -- A second instance parented to it renders without the parent's
        -- texture parameters, so baked ground-cover albedo would disappear.
        local ok, message = pcall(function()
            material:SetVectorParameterValue(
                UEHelpers.FindOrAddFName("Color"), {
                    R = color[1], G = color[2], B = color[3],
                    A = color[4] or 1.0,
                })
        end)
        if not ok then log("dynamic material tint failed for " .. label .. ": " .. tostring(message)) end
        return material
    end
    local library = StaticFindObject(
        "/Script/Engine.Default__KismetMaterialLibrary")
    local world = UEHelpers.GetWorld()
    if not valid(library) or not valid(world) then return material end
    local ok, dynamic = pcall(function()
        local instance = library:CreateDynamicMaterialInstance(
            world, material,
            UEHelpers.FindOrAddFName("SkiEO_" .. label:gsub("[^%w]", "_")), 0)
        if valid(instance) then
            instance:SetVectorParameterValue(
                UEHelpers.FindOrAddFName("Color"), {
                    R = color[1], G = color[2], B = color[3],
                    A = color[4] or 1.0,
                })
        end
        return instance
    end)
    if ok and valid(dynamic) then return dynamic end
    log("dynamic material tint failed for " .. label .. ": " .. tostring(dynamic))
    return material
end

local function apply_material(
    state, component, generation, requested_material, color, label, done)
    local source_ground = state.independent_world and label == "terrain"
        and not requested_material
    local requested = requested_material or (source_ground
        and "/Game/Materials/M_Prop_albtex.M_Prop_albtex"
        or "/Engine/EngineMaterials/DefaultMaterial.DefaultMaterial")
    local material, resolved = load_material(requested)
    if not material then
        material, resolved = load_material(
            "/Engine/EngineMaterials/DefaultMaterial.DefaultMaterial")
    end
    if not material then
        log("terrain material unavailable: " .. tostring(requested))
        done()
        return
    end
    -- Texture import can trigger GC before the dynamic instance exists.
    if NativeTerrain.retain_texture then NativeTerrain.retain_texture(material) end
    local owned_dynamic = false
    local texture_definitions = state.map.terrain.textures or {}
    if (source_ground and resolved == requested)
        or (label == "terrain" and next(texture_definitions) ~= nil) then
        local library = StaticFindObject("/Script/Engine.Default__KismetMaterialLibrary")
        if not valid(library) then
            done(false, "source ground material library is unavailable")
            return
        end
        -- Load assets before invoking a UFunction: UE4SS function wrappers
        -- must not be re-entered by LoadAsset while evaluating arguments.
        local world = UEHelpers.GetWorld()
        local ok, dynamic = pcall(function()
            local textures = Textures.load(state.map)
            if source_ground and not textures.albedo then
                textures.albedo = load_material(
                    "/Game/Materials/Terrain/Textures/t_terrain_rock_alb.t_terrain_rock_alb")
                assert(valid(textures.albedo), "source ground texture is unavailable")
            end
            local instance = library:CreateDynamicMaterialInstance(world,
                material, FName("SkiEOSourceGround"), 0)
            assert(valid(instance), "could not create the source ground material")
            local parameters = state.runtime.texture_parameters or {}
            for channel, texture in pairs(textures) do
                local parameter = parameters[channel] or (channel == "albedo" and "Albedo")
                assert(parameter, "terrain texture channel needs a runtime texture parameter: " .. channel)
                local name = FName(parameter)
                instance:SetTextureParameterValue(name, texture)
            end
            return instance
        end)
        if not ok then done(false, dynamic) return end
        material = dynamic
        owned_dynamic = true
    end
    material = tint_material(material, color, label, owned_dynamic)
    -- This material crosses queued frames before every section references it.
    -- Lua wrappers are weak Unreal references; keep it alive during loading
    -- and parallel render-state rebuilds, just like imported terrain textures.
    if NativeTerrain.retain_texture then NativeTerrain.retain_texture(material) end

    -- SetMaterial dirties the component render state. Doing it repeatedly in
    -- the frame that completed mesh generation races UE5's parallel
    -- end-of-frame component update and can terminate the game. Apply one
    -- material slot per frame, just like the mesh sections themselves.
    local section = 0
    local function next_section()
        if Terrain.generation ~= generation then return end
        if section >= state.section_count then
            log(string.format("%s material: %s", label, resolved))
            done()
            return
        end
        queue_game_thread(function()
            if Terrain.generation ~= generation or not valid(component) then return end
            local ok, message = pcall(function()
                component:SetMaterial(section, material)
            end)
            if not ok then
                log("terrain material failed: " .. tostring(message))
                done(false, message)
                return
            end
            section = section + 1
            defer_game_thread(1, next_section)
        end)
    end
    next_section()
end

local function create_sections(state, component, generation, options, done)
    local step = math.max(1, math.floor(state.runtime.sample_step or 4))
    local tile_quads = math.max(8, math.min(127,
        math.floor(state.runtime.tile_quads or 63)))
    state.sample_step = step
    if state.independent_world and not state.mesh_plan then
        state.mesh_plan = Mesh.plan(state, step)
        log(string.format("adaptive cliff mesh: %d/%d cells refined, base spacing %.1f m, cliff spacing %.1f m",
            state.mesh_plan.refined_count, state.mesh_plan.width * state.mesh_plan.height,
            step * state.spacing_cm / 100, state.mesh_plan.fine_step * state.spacing_cm / 100))
    end
    local columns = state.mesh_plan and state.mesh_plan.columns or sampled_indices(state.width, step)
    local rows = state.mesh_plan and state.mesh_plan.rows or sampled_indices(state.height, step)
    local tiles = {}
    for first_y = 1, #rows - 1, tile_quads do
        for first_x = 1, #columns - 1, tile_quads do
            tiles[#tiles + 1] = { x = first_x, y = first_y }
        end
    end
    state.section_count = #tiles
    local index = 1
    local function next_tile()
        if Terrain.generation ~= generation then return end
        if index > #tiles then
            if options.visible == false then
                pcall(function() component:SetVisibility(false, false) end)
                log(string.format(
                    "%s generated as invisible collision from %s: %dx%d source, %dx%d runtime, %d sections",
                    options.label,
                    state.map.terrain.source.file, state.width, state.height,
                    #columns, #rows, #tiles))
                done(true)
                return
            end
            apply_material(
                state, component, generation, options.material, options.color,
                options.label, function(material_ok, material_message)
                if material_ok == false then done(false, material_message) return end
                pcall(function()
                    log(string.format(
                        "%s component: %d section(s), origin=(%.0f, %.0f), extent=(%.0f, %.0f), elevation=(%.0f, %.0f) cm",
                        options.label, component:GetNumSections(),
                        state.origin_x, state.origin_y,
                        (state.width - 1) * state.spacing_cm,
                        (state.height - 1) * state.spacing_cm,
                        state.map.terrain.elevation_meters[1] * 100.0,
                        state.map.terrain.elevation_meters[2] * 100.0))
                end)
                log(string.format(
                    "%s generated from %s: %dx%d source, %dx%d runtime, %d sections",
                    options.label,
                    state.map.terrain.source.file, state.width, state.height,
                    #columns, #rows, #tiles))
                done(true)
            end)
            return
        end
        queue_game_thread(function()
            if Terrain.generation ~= generation or not valid(component) then return end
            local tile = tiles[index]
            local ok, message = pcall(function()
                local vertices, triangles, normals, uvs = build_tile(
                    state, columns, rows, tile.x, tile.y, tile_quads,
                    options.z_offset_cm, options.rock_projection, state.mesh_plan)
                component:CreateMeshSection(
                    index - 1, vertices, triangles, normals, uvs, {}, {},
                    options.collision)
            end)
            if not ok then
                log("terrain section failed: " .. tostring(message))
                done(false, message)
                return
            end
            index = index + 1
            if state.progress then
                local base = options.label == "terrain" and 0.08 or 0.60
                local span = options.label == "terrain" and 0.52 or 0.30
                state.progress(options.label == "terrain"
                    and "Generating terrain" or "Snow layer",
                    base + span * (index - 1) / #tiles)
            end
            defer_game_thread(1, next_tile)
        end)
    end
    next_tile()
end

local function build_skirt(state)
    local step = math.max(1, math.floor(state.runtime.sample_step or 4))
    local columns = sampled_indices(state.width, step)
    local rows = sampled_indices(state.height, step)
    local points = {}
    for _, column in ipairs(columns) do
        points[#points + 1] = { column = column, row = 0 }
    end
    for index = 2, #rows do
        points[#points + 1] = {
            column = state.width - 1, row = rows[index]
        }
    end
    for index = #columns - 1, 1, -1 do
        points[#points + 1] = {
            column = columns[index], row = state.height - 1
        }
    end
    for index = #rows - 1, 2, -1 do
        points[#points + 1] = { column = 0, row = rows[index] }
    end

    local minimum, maximum = math.huge, -math.huge
    for _, point in ipairs(points) do
        point.z = Heightmap.sample_grid_cm(state,point.column,point.row)
        minimum, maximum = math.min(minimum,point.z),math.max(maximum,point.z)
    end
    -- Fit the wall to the actual perimeter, including its source datum.
    -- A proportional depth keeps small maps and broad mountain maps alike
    -- usable without requiring an authored skirt mesh or depth in the JSON.
    local extent = math.min(state.width-1,state.height-1) * state.spacing_cm
    local depth_cm = state.runtime.skirt_depth_meters
        and state.runtime.skirt_depth_meters * 100
        or math.max(10000,extent*0.04,(maximum-minimum)*0.2)
    depth_cm = math.max(100,depth_cm)
    local bottom_z = minimum - depth_cm
    local uv_tile_cm = math.max(100.0,
        (state.runtime.uv_tile_meters or 20.0) * 100.0)
    local vertices, triangles, normals, uvs = {}, {}, {}, {}
    local distance = 0.0
    for index = 1, #points do
        local first = points[index]
        local second = points[index % #points + 1]
        local first_x = state.origin_x + first.column * state.spacing_cm
        local first_y = state.origin_y + first.row * state.spacing_cm
        local second_x = state.origin_x + second.column * state.spacing_cm
        local second_y = state.origin_y + second.row * state.spacing_cm
        local first_z, second_z = first.z, second.z
        local dx, dy = second_x - first_x, second_y - first_y
        local length = math.sqrt(dx * dx + dy * dy)
        if length > 0.0 then
            local normal = { X = dy / length, Y = -dx / length, Z = 0.0 }
            local base = #vertices
            vertices[#vertices + 1] = { X = first_x, Y = first_y, Z = first_z }
            vertices[#vertices + 1] = { X = first_x, Y = first_y, Z = bottom_z }
            vertices[#vertices + 1] = { X = second_x, Y = second_y, Z = second_z }
            vertices[#vertices + 1] = { X = second_x, Y = second_y, Z = bottom_z }
            for _ = 1, 4 do normals[#normals + 1] = normal end
            local first_u = distance / uv_tile_cm
            local second_u = (distance + length) / uv_tile_cm
            uvs[#uvs + 1] = { X = first_u, Y = (first_z - bottom_z) / uv_tile_cm }
            uvs[#uvs + 1] = { X = first_u, Y = 0.0 }
            uvs[#uvs + 1] = { X = second_u, Y = (second_z - bottom_z) / uv_tile_cm }
            uvs[#uvs + 1] = { X = second_u, Y = 0.0 }
            for _, triangle_index in ipairs({
                base, base + 2, base + 1,
                base + 1, base + 2, base + 3,
                base + 1, base + 2, base,
                base + 3, base + 2, base + 1,
            }) do
                triangles[#triangles + 1] = triangle_index
            end
            distance = distance + length
        end
    end

    -- Only the vertical perimeter is required. A horizontal bottom cap spans
    -- the whole 64 km map and can cross the view frustum as a large dark
    -- triangle when the camera approaches an edge.
    return vertices, triangles, normals, uvs, bottom_z
end

local function create_skirt(state, component, generation, done)
    queue_game_thread(function()
        if Terrain.generation ~= generation or not valid(component) then return end
        local ok, vertices_or_message, triangles, normals, uvs, bottom_z =
            pcall(build_skirt, state)
        if not ok then done(false, vertices_or_message) return end
        local created, message = pcall(function()
            component:CreateMeshSection(
                0, vertices_or_message, triangles, normals, uvs, {}, {}, false)
        end)
        if not created then done(false, message) return end
        local skirt_state = setmetatable({section_count=1},{__index=state})
        apply_material(
            skirt_state, component, generation,
            state.runtime.skirt_material or (state.independent_world
                and "/Game/Materials/Terrain/M_StriatedRock.M_StriatedRock" or state.runtime.material),
            state.runtime.skirt_color,
            "terrain skirt", function(material_ok, material_message)
                if material_ok == false then done(false, material_message) return end
                log(string.format(
                    "terrain skirt generated: %d segments, bottom=%.0f cm",
                    #triangles / 12, bottom_z))
                done(true)
            end)
    end)
end

function Terrain.unload(preserve_native)
    Terrain.generation = Terrain.generation + 1
    Terrain.callbacks = {}
    local previous_actor = Terrain.actor
    if valid(previous_actor) then
        queue_game_thread(function()
            if valid(previous_actor) then previous_actor:K2_DestroyActor() end
        end)
    end
    Terrain.active, Terrain.actor, Terrain.component = nil, nil, nil
    Terrain.snow_component, Terrain.skirt_component = nil, nil
    Terrain.trail_component = nil
    if not preserve_native then NativeTerrain.reset() end
end

function Terrain.load(map, done, progress, prepared_state)
    Terrain.unload(prepared_state ~= nil)
    local generation = Terrain.generation
    local ok, state_or_message = true, prepared_state
    if not prepared_state then ok, state_or_message = pcall(Heightmap.load, map) end
    if not ok then done(false, state_or_message) return end
    local state = state_or_message
    state.progress = progress
    Terrain.active = state
    queue_game_thread(function()
        if Terrain.generation ~= generation then return end
        local world = UEHelpers.GetWorld()
        if not valid(world) then done(false, "world is unavailable") return end
        local world_address = world:GetAddress()
        if not state.independent_world then
            log(string.format("hidden %d template terrain actor(s)", hide_template_terrain(world)))
        end
        local function is_current()
            local current_world = UEHelpers.GetWorld()
            return Terrain.generation == generation and valid(current_world)
                and current_world:GetAddress() == world_address
        end
        local function create_runtime_terrain()
            if not is_current() then return end
            local snow_material = state.runtime.snow_material
            local skirt_enabled = state.runtime.skirt_enabled ~= false
            local created, actor_or_message, component, snow_component,
                skirt_component = pcall(function()
                local actor, mesh, snow, skirt = spawn_mesh_actor(
                    world, state.independent_world or (snow_material ~= nil and not state.native_landscape),
                    skirt_enabled)
                return actor, mesh, snow, skirt
            end)
            if not created then done(false, actor_or_message) return end
            Terrain.actor, Terrain.component = actor_or_message, component
            Terrain.snow_component = snow_component
            Terrain.skirt_component = skirt_component
            create_sections(state, component, generation, {
                label = "terrain",
                material = state.runtime.material,
                rock_projection = state.independent_world and not state.runtime.material,
                color = state.runtime.material_color,
                z_offset_cm = 0.0,
                collision = true,
                visible = state.independent_world or not state.native_landscape,
            }, function(ok, message)
                if not ok then done(false, message) return end
                local function finish_with_skirt(snow_ok, snow_message)
                    if not snow_ok then done(false, snow_message) return end
                    local function finish(ok, message)
                        if not ok then done(false, message); return end
                        require("nanite_terrain").apply(Terrain, schedule, function()
                            require('scenery').create(map,Terrain,schedule,done,log)
                        end, log)
                    end
                    if valid(skirt_component) then
                        if progress then progress("Building terrain skirt", 0.92) end
                        create_skirt(state, skirt_component, generation, finish)
                    else
                        finish(true)
                    end
                end
                if not valid(snow_component) then
                    finish_with_skirt(true)
                    return
                end
                create_sections(state, snow_component, generation, {
                    label = "snow shell",
                    material = snow_material or (state.independent_world
                        and "/Game/Materials/Snow/M_Snow.M_Snow"),
                    color = state.runtime.snow_color,
                    z_offset_cm = state.runtime.snow_offset_centimeters or 30.0,
                    collision = false,
                }, finish_with_skirt)
            end)
        end
        NativeTerrain.populate(state, function(native_ok, native_result)
            if not native_ok then done(false, native_result) return end
            log(string.format(
                "native terrain reconstructed: %dx%d, spacing=(%.3f, %.3f) cm, %d Landscape atlas(es)/%d mip(s), %d derived simulation texture(s), %.2f s",
                native_result.width, native_result.height,
                native_result.spacing_x, native_result.spacing_y,
                native_result.landscape.texture_count,
                native_result.landscape.mip_count,
                native_result.derived_textures.count,
                native_result.elapsed_seconds))
            create_runtime_terrain()
        end, progress, is_current)
    end)
end

-- Native placement can retain a vertical offset measured against the hidden
-- template Landscape. Once the portable cache is installed that offset may
-- put a placeable either below or far above the source surface. Normalize
-- both directions to the map's declared clearance.
function Terrain.align_building(actor)
    if not Terrain.active or not valid(actor)
        or not actor:IsA("/Script/SkiResortSimulator.BuildingActor") then
        return false
    end
    if not valid(Terrain.actor)
        or not belongs_to_world(actor, Terrain.actor:GetWorld()) then return false end
    local ok, location = pcall(function() return actor:K2_GetActorLocation() end)
    if not ok or not location then return false end
    local decorative = false
    pcall(function()
        decorative = actor:GetClass():GetFullName():find('/Blueprints/Decorations/', 1, true) ~= nil
    end)
    -- Small furniture follows the visible triangles. The simulation height
    -- can differ on decimated slopes and bury a bench or table in the mesh.
    local ground_z = decorative and Terrain.surface_height_at(location.X, location.Y)
        or Terrain.height_at(location.X, location.Y)
    if not ground_z then return false end
    local delta = location.Z - ground_z
    local tolerance = Terrain.active.runtime
        .placeable_below_ground_tolerance_centimeters or 5.0
    local clearance = Terrain.active.runtime
        .placeable_clearance_centimeters or 0.0
    if decorative then
        clearance = math.max(clearance, (Terrain.active.runtime.snow_offset_centimeters or 30.0)
            + (tonumber(actor.TerrainSnapBufferCm) or 10.0))
    end
    if math.abs(delta - clearance) <= tolerance then
        return false, delta, ground_z
    end
    local target = {
        X = location.X,
        Y = location.Y,
        Z = ground_z + clearance,
    }
    -- FinalizePlacement makes building roots static. Unreal silently rejects
    -- K2_SetActorLocation on a static root, so make it movable just long
    -- enough to repair the transform and then restore its original mobility.
    local root_component = nil
    pcall(function() root_component = actor.RootComponent end)
    if not valid(root_component) then
        pcall(function() root_component = actor:K2_GetRootComponent() end)
    end
    local original_mobility = nil
    if valid(root_component) then
        pcall(function() original_mobility = root_component.Mobility end)
        local mobility_changed = pcall(function()
            root_component:SetMobility(2)
        end)
        if not mobility_changed then
            pcall(function() root_component.Mobility = 2 end)
        end
    else
        log("building terrain alignment could not find its root component")
    end
    local moved, message = pcall(function()
        actor:K2_SetActorLocation(target, false, {}, true)
    end)
    if valid(root_component) and original_mobility ~= nil then
        pcall(function() root_component:SetMobility(original_mobility) end)
    end
    if not moved then
        log("building terrain alignment failed: " .. tostring(message))
        return false, delta, ground_z
    end
    local verified, final_location = pcall(function()
        return actor:K2_GetActorLocation()
    end)
    if not verified or not final_location then
        log("building terrain alignment could not verify the resulting position")
        return false, delta, ground_z
    end
    local final_delta = final_location.Z - ground_z
    local aligned = math.abs(final_delta - clearance) <= 1.0
    if not aligned then
        log(string.format(
            "building terrain alignment was rejected: target=%.1f cm, final=%.1f cm",
            clearance, final_delta))
    end
    return aligned, delta, ground_z, final_delta
end

local aligning_lifts = {}

-- Lift geometry is world-space data, not children that follow the actor's
-- transform. Native Initialize/GenerateTowers can retain template-Landscape
-- offsets even when its collision is disabled. Repair geometry on either side
-- of the source surface before rebuilding cables.
function Terrain.align_lift(actor)
    if not Terrain.active or not valid(actor)
        or not actor:IsA("/Script/SkiResortSimulator.LiftActor") then
        return false
    end
    if not valid(Terrain.actor)
        or not belongs_to_world(actor, Terrain.actor:GetWorld()) then
        return false
    end
    local address = actor:GetAddress()
    if aligning_lifts[address] then return false end
    aligning_lifts[address] = true
    local ok, changed_or_message, waypoint_count, tower_count = pcall(function()
        local tolerance = Terrain.active.runtime
            .placeable_below_ground_tolerance_centimeters or 5.0
        local waypoints, towers = 0, 0
        actor.Waypoints:ForEach(function(_, value)
            local point = value:get()
            local position = point.position
            local height = Terrain.height_at(position.X, position.Y)
            if height and math.abs(position.Z - height) > tolerance then
                position.Z = height
                waypoints = waypoints + 1
            end
        end)
        actor.Towers:ForEach(function(index, value)
            local tower = value:get()
            local position = tower.BasePosition
            local height = Terrain.height_at(position.X, position.Y)
            if not height or math.abs(position.Z - height) <= tolerance then return end
            local delta = height - position.Z
            local component = index <= #actor.TowerMeshComponents
                and actor.TowerMeshComponents[index] or nil
            if valid(component) then
                local location = component:K2_GetComponentLocation()
                local mobility = component.Mobility
                component:SetMobility(2)
                local moved, message = pcall(function()
                    component:K2_SetWorldLocation({
                        X = location.X, Y = location.Y, Z = location.Z + delta,
                    }, false, {}, true)
                end)
                component:SetMobility(mobility)
                if not moved then error(message, 0) end
            end
            position.Z = height
            towers = towers + 1
        end)
        if waypoints == 0 and towers == 0 then return false, 0, 0 end
        actor:UpdateTerminalPositions()
        actor:UpdateCableSpline()
        actor:RebuildCableMeshes()
        actor:RebuildChairMeshes(0.0)
        return true, waypoints, towers
    end)
    aligning_lifts[address] = nil
    if not ok then
        log("lift terrain alignment failed: " .. tostring(changed_or_message))
        return false
    end
    if changed_or_message then
        log(string.format("lift terrain aligned: %d waypoint(s), %d tower(s); %s",
            waypoint_count, tower_count, actor:GetFullName()))
    end
    return changed_or_message
end

-- FinalizePlacement snapshots lift terminal positions into the native hub
-- graph. Correct the persisted waypoints before that snapshot is taken; the
-- heavier mesh/cable rebuild remains deferred until the finalizer returns.
function Terrain.align_lift_waypoints(actor)
    if not Terrain.active or not valid(actor)
        or not actor:IsA("/Script/SkiResortSimulator.LiftActor") then
        return 0
    end
    if not valid(Terrain.actor)
        or not belongs_to_world(actor, Terrain.actor:GetWorld()) then
        return 0
    end
    local address = actor:GetAddress()
    if aligning_lifts[address] then return 0 end
    aligning_lifts[address] = true
    local ok, changed_or_message = pcall(function()
        local tolerance = Terrain.active.runtime
            .placeable_below_ground_tolerance_centimeters or 5.0
        local changed = 0
        actor.Waypoints:ForEach(function(_, value)
            local point = value:get()
            local position = point.position
            local height = Terrain.height_at(position.X, position.Y)
            if height and math.abs(position.Z - height) > tolerance then
                position.Z = height
                changed = changed + 1
            end
        end)
        if changed > 0 then
            -- The hub graph reads the terminal components, not just the
            -- persisted waypoint array. Refresh those derived transforms
            -- while the FinalizePlacement pre-hook is still running so the
            -- native registration snapshots the grounded coordinates.
            actor:UpdateTerminalPositions()
        end
        return changed
    end)
    aligning_lifts[address] = nil
    if not ok then
        log("lift terminal preparation failed: " .. tostring(changed_or_message))
        return 0
    end
    return changed_or_message
end

local function parameter_value(parameter)
    local value = parameter
    for _ = 1, 3 do
        if type(value) ~= "userdata" and type(value) ~= "table" then break end
        local ok, unwrapped = pcall(function() return value:get() end)
        if not ok then break end
        value = unwrapped
    end
    return value
end

local function numeric(value)
    return tonumber(parameter_value(value))
end

local function current_object(class_name)
    local world = UEHelpers.GetWorld()
    if not valid(world) then return nil end
    for _, object in ipairs(FindAllOf(class_name) or {}) do
        if valid(object) then
            local ok, object_world = pcall(function() return object:GetWorld() end)
            if ok and valid(object_world)
                and object_world:GetAddress() == world:GetAddress() then
                return object
            end
        end
    end
    return nil
end

local function current_actors(class_name)
    local world = UEHelpers.GetWorld()
    local gameplay = UEHelpers.GetGameplayStatics()
    local class = StaticFindObject(
        "/Script/SkiResortSimulator." .. class_name)
    local actors = {}
    if not valid(world) or not valid(gameplay) or not valid(class) then return actors end
    local found = {}
    gameplay:GetAllActorsOfClass(world, class, found)
    for _, entry in ipairs(found) do
        local actor = parameter_value(entry)
        if valid(actor) and not actor:IsActorBeingDestroyed() then
            actors[#actors + 1] = actor
        end
    end
    return actors
end

local function actor_to_surface(actor, clearance)
    if not Terrain.active or not valid(actor) then return false end
    local location = actor:K2_GetActorLocation()
    local x, y, z = numeric(location.X), numeric(location.Y), numeric(location.Z)
    local ground = x and y and Terrain.height_at(x, y) or nil
    local tolerance = Terrain.active.runtime
        .placeable_below_ground_tolerance_centimeters or 5.0
    if not ground or not z or z >= ground - tolerance then return false end
    local root = nil
    pcall(function() root = actor.RootComponent end)
    local mobility = nil
    if valid(root) then
        pcall(function() mobility = root.Mobility end)
        pcall(function() root:SetMobility(2) end)
    end
    actor:K2_SetActorLocation({ X = x, Y = y, Z = ground + clearance }, false, {}, true)
    if valid(root) and mobility ~= nil then pcall(function() root:SetMobility(mobility) end) end
    return true
end

local function for_each_value(collection, callback)
    if not collection then return end
    if type(collection) == "table" then
        for _, value in ipairs(collection) do callback(value) end
        return
    end
    local ok, message = pcall(function()
        collection:ForEach(function(_, value) callback(value) end)
    end)
    if not ok then error(message, 0) end
end

local function vector_values(vector)
    return numeric(vector.X), numeric(vector.Y), numeric(vector.Z)
end

local function sample_curve(state, curve, points, z_offset)
    local sx, sy = vector_values(curve.StartPoint)
    local cx, cy = vector_values(curve.ControlPoint)
    local ex, ey = vector_values(curve.Endpoint)
    if not sx or not sy or not cx or not cy or not ex or not ey then return end
    local length = math.sqrt((cx - sx) ^ 2 + (cy - sy) ^ 2)
        + math.sqrt((ex - cx) ^ 2 + (ey - cy) ^ 2)
    local samples = math.max(4, math.min(64, math.ceil(length / 500.0)))
    local first = #points == 0 and 0 or 1
    for index = first, samples do
        local t = index / samples
        local inverse = 1.0 - t
        local x = inverse * inverse * sx + 2.0 * inverse * t * cx + t * t * ex
        local y = inverse * inverse * sy + 2.0 * inverse * t * cy + t * t * ey
        local z = Heightmap.height_at(state, x, y)
        if z then points[#points + 1] = { X = x, Y = y, Z = z + z_offset } end
    end
end

local function curve_point(curve, t)
    local inverse = 1.0 - t
    local sx, sy, sz = vector_values(curve.StartPoint)
    local cx, cy, cz = vector_values(curve.ControlPoint)
    local ex, ey, ez = vector_values(curve.Endpoint)
    return {
        X = inverse * inverse * sx + 2.0 * inverse * t * cx + t * t * ex,
        Y = inverse * inverse * sy + 2.0 * inverse * t * cy + t * t * ey,
        Z = inverse * inverse * sz + 2.0 * inverse * t * cz + t * t * ez,
    }
end

local function grounded_z(state, point)
    return Heightmap.height_at(state, point.X, point.Y) or point.Z
end

-- Preserve each quadratic curve in XY with exact de Casteljau sub-curves,
-- while fitting its Z to the portable heightmap at both ends and midpoint.
-- Native trail selection, highlights and hub endpoints all consume these
-- curves, whereas the source ribbon below is only a visual representation.
local function grounded_subcurves(state, curve, maximum_length)
    local sx, sy = vector_values(curve.StartPoint)
    local cx, cy = vector_values(curve.ControlPoint)
    local ex, ey = vector_values(curve.Endpoint)
    local length = math.sqrt((cx - sx) ^ 2 + (cy - sy) ^ 2)
        + math.sqrt((ex - cx) ^ 2 + (ey - cy) ^ 2)
    local count = math.max(1, math.ceil(length / maximum_length))
    local width = numeric(curve.CorridorWidth) or 1000.0
    local result = {}
    for index = 0, count - 1 do
        local first_t = index / count
        local last_t = (index + 1) / count
        local middle_t = (first_t + last_t) * 0.5
        local first = curve_point(curve, first_t)
        local last = curve_point(curve, last_t)
        local middle = curve_point(curve, middle_t)
        local span = last_t - first_t
        local control = {
            X = first.X + span * ((1.0 - first_t) * (cx - sx)
                + first_t * (ex - cx)),
            Y = first.Y + span * ((1.0 - first_t) * (cy - sy)
                + first_t * (ey - cy)),
            Z = 0.0,
        }
        first.Z = grounded_z(state, first)
        last.Z = grounded_z(state, last)
        local middle_z = grounded_z(state, middle)
        -- For a quadratic Bezier, B(0.5) = .25 P0 + .5 P1 + .25 P2.
        -- This control Z therefore makes the native curve touch the sampled
        -- surface at the sub-curve midpoint as well as at both endpoints.
        control.Z = 2.0 * middle_z - 0.5 * (first.Z + last.Z)
        result[#result + 1] = {
            StartPoint = first,
            ControlPoint = control,
            Endpoint = last,
            CorridorWidth = width,
        }
    end
    return result
end

local function all_trail_curves(info)
    local curves = { info.Curve }
    info.AdditionalCurves:ForEach(function(_, curve)
        curves[#curves + 1] = parameter_value(curve)
    end)
    return curves
end

-- A custom map reuses a stock level whose decoded obstacle index still holds
-- the template trees. They are hidden with its renderer, but native trail
-- validation keeps querying them and reports invisible trees in otherwise
-- clear source corridors. Run this after final trail grounding, using the
-- exact registered curves and an extra canopy margin, before exposing the
-- playable world.
function Terrain.clear_native_trail_obstacles()
    if not Terrain.active then return 0, 0 end
    local trail_map = current_object("TrailMapSubsystem")
    local obstacles = current_object("ObstacleDataManager")
    if not valid(trail_map) or not valid(obstacles) then return 0, 0 end

    local operations, cleared = 0, 0
    trail_map.RegisteredTrails:ForEach(function(key, value)
        local trail_id = numeric(key)
        local info = parameter_value(value)
        if not trail_id or not info then return end
        for _, curve in ipairs(all_trail_curves(info)) do
            local half_width = (numeric(curve.CorridorWidth) or 1000.0) * 0.5
                + 2000.0
            for _, pair in ipairs({
                { curve.StartPoint, curve.ControlPoint },
                { curve.ControlPoint, curve.Endpoint },
            }) do
                local ok, result = pcall(function()
                    return obstacles:ClearObstaclesAlongLine(
                        pair[1], pair[2], half_width, false)
                end)
                operations = operations + 1
                if ok then cleared = cleared + (tonumber(result) or 0) end
            end
        end
        pcall(function() trail_map:SetTrailGroomed(trail_id, true) end)
    end)
    trail_map:NotifyPaintComplete()
    log(string.format(
        "native trail corridors cleared: %d operation(s), %d obstacle(s)",
        operations, cleared))
    return operations, cleared
end

function Terrain.align_native_trails()
    if not Terrain.active then return 0, 0, 0 end
    local trail_map = current_object("TrailMapSubsystem")
    if not valid(trail_map) then return 0, 0, 0 end
    local hub_connectivity = current_object("HubConnectivitySubsystem")
    local maximum_length = math.max(400.0,
        math.min(1000.0, (Terrain.active.spacing_cm or 400.0) * 2.0))
    local replacements = {}
    trail_map.RegisteredTrails:ForEach(function(key, value)
        local trail_id = numeric(key)
        local info = parameter_value(value)
        if not trail_id or not info then return end
        local rebuilt = {}
        for _, curve in ipairs(all_trail_curves(info)) do
            for _, segment in ipairs(grounded_subcurves(
                Terrain.active, curve, maximum_length)) do
                rebuilt[#rebuilt + 1] = segment
            end
        end
        if #rebuilt > 0 then
            replacements[#replacements + 1] = {
                id = trail_id,
                original_count = 1 + info.AdditionalCurves:GetArrayNum(),
                base = rebuilt[1],
                additional = { table.unpack(rebuilt, 2) },
            }
        end
    end)

    local hubs_before, hubs_before_message = NativeTerrain.probe_hubs()
    log("hub lifecycle before trail grounding: " ..
        tostring(hubs_before) .. " " .. tostring(hubs_before_message))

    local replaced, original_curves, grounded_curves = 0, 0, 0
    for _, replacement in ipairs(replacements) do
        if valid(hub_connectivity) then
            pcall(function()
                hub_connectivity:HandleTrailUnregistered(replacement.id)
            end)
        end
        local ok, did_replace = pcall(function()
            return trail_map:ReplaceTrailGeometry(
                replacement.id, replacement.base, replacement.additional)
        end)
        if ok and did_replace then
            trail_map:RegisterOrUpdateTrail(replacement.id)
            if valid(hub_connectivity) then
                -- RegisterOrUpdateTrail refreshes visualization and trail
                -- nodes; explicitly replace the hub member too because the
                -- original endpoint was registered before all curves existed.
                pcall(function()
                    hub_connectivity:HandleTrailUnregistered(replacement.id)
                    hub_connectivity:HandleTrailRegistered(replacement.id)
                end)
            end
            replaced = replaced + 1
            original_curves = original_curves + replacement.original_count
            grounded_curves = grounded_curves + 1 + #replacement.additional
            if replaced == 1 then
                local first_ok, first_message = NativeTerrain.probe_hubs()
                log("hub lifecycle after first grounded trail: " ..
                    tostring(first_ok) .. " " .. tostring(first_message))
            end
        else
            log(string.format("native trail %d grounding failed: %s",
                replacement.id, tostring(did_replace)))
            if valid(hub_connectivity) then
                pcall(function()
                    hub_connectivity:HandleTrailRegistered(replacement.id)
                end)
            end
        end
    end
    if replaced > 0 then
        trail_map:DetectIntersections()
        trail_map:NotifyPaintComplete()
        local hubs_probed, hub_message = NativeTerrain.probe_hubs()
        if hubs_probed then
            log("hub lifecycle after trail grounding: " .. hub_message)
        else
            log("native hub graph probe unavailable: " ..
                tostring(hub_message))
        end
        for _, lift in ipairs(current_actors("LiftActor")) do
            pcall(function() lift:HandleHubsRebuilt() end)
        end
        local trail_visualization = current_object(
            "TrailVisualizationSubsystem")
        if valid(trail_visualization) then
            pcall(function() trail_visualization:HandleHubsRebuilt() end)
        end
        local guests = current_object("GuestSimulationSubsystem")
        if valid(guests) then
            pcall(function() guests:HandleHubsRebuilt() end)
        end
        local hub_visualization = current_object("HubVisualizationSubsystem")
        if valid(hub_visualization) then
            hub_visualization:HandleHubsRebuilt()
        end
    end
    log(string.format(
        "native trail geometry grounded: %d trail(s), %d -> %d curve(s)",
        replaced, original_curves, grounded_curves))
    return replaced, original_curves, grounded_curves
end

local function trail_ribbon(state, info, width, z_offset)
    local points = {}
    sample_curve(state, info.Curve, points, z_offset)
    info.AdditionalCurves:ForEach(function(_, value)
        sample_curve(state, parameter_value(value), points, z_offset)
    end)
    if #points < 2 then return nil end
    local vertices, triangles, normals, uvs = {}, {}, {}, {}
    local half_width = width * 0.5
    local distance = 0.0
    for index, point in ipairs(points) do
        local previous = points[math.max(1, index - 1)]
        local following = points[math.min(#points, index + 1)]
        local dx, dy = following.X - previous.X, following.Y - previous.Y
        local length = math.sqrt(dx * dx + dy * dy)
        if length < 0.001 then dx, dy, length = 1.0, 0.0, 1.0 end
        local side_x, side_y = -dy / length * half_width, dx / length * half_width
        local left_x, left_y = point.X + side_x, point.Y + side_y
        local right_x, right_y = point.X - side_x, point.Y - side_y
        local left_z = Heightmap.height_at(state, left_x, left_y) or point.Z - z_offset
        local right_z = Heightmap.height_at(state, right_x, right_y) or point.Z - z_offset
        vertices[#vertices + 1] = { X = left_x, Y = left_y, Z = left_z + z_offset }
        vertices[#vertices + 1] = { X = right_x, Y = right_y, Z = right_z + z_offset }
        normals[#normals + 1] = { X = 0.0, Y = 0.0, Z = 1.0 }
        normals[#normals + 1] = { X = 0.0, Y = 0.0, Z = 1.0 }
        if index > 1 then
            local segment_x = point.X - points[index - 1].X
            local segment_y = point.Y - points[index - 1].Y
            distance = distance + math.sqrt(segment_x * segment_x + segment_y * segment_y)
        end
        uvs[#uvs + 1] = { X = 0.0, Y = distance / math.max(width, 1.0) }
        uvs[#uvs + 1] = { X = 1.0, Y = distance / math.max(width, 1.0) }
    end
    for index = 1, #points - 1 do
        local left = (index - 1) * 2
        local right = left + 1
        local next_left = left + 2
        local next_right = left + 3
        for _, vertex in ipairs({
            left, right, next_left,
            right, next_right, next_left,
        }) do triangles[#triangles + 1] = vertex end
    end
    return vertices, triangles, normals, uvs
end

local function native_trail_materials(visualization)
    local materials = {}
    if not valid(visualization) then return materials end
    visualization.SpawnedTrailLines:ForEach(function(key, value)
        local trail_id = numeric(key)
        local actor = parameter_value(value)
        if trail_id and valid(actor) and valid(actor.MeshComponent) then
            local material = actor.MeshComponent:GetMaterial(0)
            if valid(material) then materials[trail_id] = material end
        end
    end)
    return materials
end

local function hide_native_trail_lines()
    local visualization = current_object("TrailVisualizationSubsystem")
    local retained = {}
    if valid(visualization) then
        visualization.SpawnedTrailLines:ForEach(function(_, value)
            local actor = parameter_value(value)
            if valid(actor) then retained[actor:GetAddress()] = true end
        end)
    end
    local hidden, removed = 0, 0
    for _, actor in ipairs(current_actors("TrailLineActor")) do
        if retained[actor:GetAddress()] then
            actor:SetActorHiddenInGame(true)
            -- The native ribbon was built before the portable heightfield
            -- existed.  Keeping it hidden preserves the game's trail
            -- bookkeeping, but its buried primitive must not remain in the
            -- click trace or it can be selected through the terrain.
            actor:SetActorEnableCollision(false)
            pcall(function()
                if valid(actor.MeshComponent) then
                    actor.MeshComponent:SetCollisionEnabled(0)
                end
            end)
            hidden = hidden + 1
        else
            actor:K2_DestroyActor()
            removed = removed + 1
        end
    end
    return hidden, removed
end

local function trail_visualization_enabled()
    local visualization = current_object("TrailVisualizationSubsystem")
    if not valid(visualization) then return true end
    local ok, enabled = pcall(function() return visualization:IsVisualizationEnabled() end)
    return not ok or enabled
end

function Terrain.sync_trail_visualization()
    if not Terrain.active then return end
    hide_native_trail_lines()
    if valid(Terrain.trail_component) then
        Terrain.trail_component:SetVisibility(trail_visualization_enabled(), true)
    end
end

function Terrain.rebuild_trail_visuals(preserve_visibility)
    if not Terrain.active then
        log("source trail visualization skipped: terrain state is unavailable")
        return 0
    end
    if not valid(Terrain.actor) then
        log("source trail visualization skipped: terrain actor is unavailable")
        return 0
    end
    local trail_map = current_object("TrailMapSubsystem")
    local visualization = current_object("TrailVisualizationSubsystem")
    if not valid(trail_map) then
        log("source trail visualization skipped: TrailMapSubsystem is unavailable")
        return 0
    end
    if valid(visualization) then
        pcall(function()
            if not preserve_visibility then visualization:SetVisualizationEnabled(true) end
            visualization:RefreshLabels()
        end)
    end
    if not valid(Terrain.trail_component) then
        local component_class = StaticFindObject(
            "/Script/ProceduralMeshComponent.ProceduralMeshComponent")
        if not valid(component_class) then
            log("source trail visualization skipped: ProceduralMeshComponent is unavailable")
            return 0
        end
        Terrain.trail_component = add_mesh_component(
            Terrain.actor, component_class, identity_transform(), false)
    else
        Terrain.trail_component:ClearAllMeshSections()
    end
    local component = Terrain.trail_component
    local materials = native_trail_materials(visualization)
    local fallback = valid(visualization) and valid(visualization.Config)
        and visualization.Config.TrailLineMaterial or nil
    local width = valid(visualization) and valid(visualization.Config)
        and numeric(visualization.Config.TrailLineWidth) or nil
    width = math.max(50.0, width or 160.0)
    local native_offset = valid(visualization) and valid(visualization.Config)
        and numeric(visualization.Config.TrailLineZOffset) or nil
    local snow_offset = Terrain.active.runtime.snow_offset_centimeters or 30.0
    local z_offset = math.max(snow_offset + 8.0, native_offset or 50.0)
    local section = 0
    trail_map.RegisteredTrails:ForEach(function(key, value)
        local trail_id = numeric(key)
        local info = parameter_value(value)
        local vertices, triangles, normals, uvs = trail_ribbon(
            Terrain.active, info, width, z_offset)
        if vertices then
            component:CreateMeshSection(
                section, vertices, triangles, normals, uvs, {}, {}, false)
            local material = materials[trail_id] or fallback
            if valid(material) then component:SetMaterial(section, material) end
            section = section + 1
        end
    end)
    local hidden, removed = hide_native_trail_lines()
    component:SetVisibility(trail_visualization_enabled(), true)
    log(string.format(
        "source trail visualization: %d ribbon(s), %d native line actor(s) hidden, %d orphan(s) removed",
        section, hidden, removed))
    return section
end

function Terrain.clamp_camera_to_surface()
    if not Terrain.active then return false end
    local pawn = nil
    local controller_ok, controller = pcall(UEHelpers.GetPlayerController)
    if controller_ok and valid(controller) then
        local pawn_ok, controlled = pcall(function() return controller:K2_GetPawn() end)
        if pawn_ok and valid(controlled) then pawn = controlled end
    end
    if not valid(pawn) then pawn = current_object("SkiResortCameraPawn") end
    if not valid(pawn) then return false end
    local position = pawn:K2_GetActorLocation()
    local x, y, z = vector_values(position)
    local ground = x and y and Terrain.height_at(x, y) or nil
    if not ground or not z then return false end
    local snow_offset = Terrain.active.runtime.snow_offset_centimeters or 30.0
    local sphere_radius = numeric(pawn.CollisionSphereRadius) or 50.0
    -- The native camera samples the template level's height cache. Clamp its
    -- actual pawn against the source heightmap after the native camera tick so
    -- zooming or panning cannot carry it through the procedural surface.
    local minimum_z = ground + snow_offset + math.max(25.0, sphere_radius)
    if z >= minimum_z then return false end
    pawn:K2_SetActorLocation(
        { X = x, Y = y, Z = minimum_z }, false, {}, true)
    return true
end

function Terrain.align_guests()
    if not Terrain.active then return 0 end
    local guests = current_object("GuestSimulationSubsystem")
    if not valid(guests) then return 0 end
    local tolerance = Terrain.active.runtime
        .placeable_below_ground_tolerance_centimeters or 5.0
    local clearance = Terrain.active.runtime.guest_clearance_centimeters or 50.0
    local changed = 0
    guests.GuestsHot:ForEach(function(_, hot)
        local position = hot.WorldPosition
        local x, y, z = vector_values(position)
        local ground = x and y and Terrain.height_at(x, y) or nil
        if ground and z and z < ground - tolerance then
            position.Z = ground + clearance
            changed = changed + 1
        end
    end)
    return changed
end

local function plain_transform(transform, target_z)
    local rotation = transform.Rotation
    local translation = transform.Translation
    local scale = transform.Scale3D
    return {
        Rotation = {
            X = numeric(rotation.X), Y = numeric(rotation.Y),
            Z = numeric(rotation.Z), W = numeric(rotation.W),
        },
        Translation = {
            X = numeric(translation.X), Y = numeric(translation.Y), Z = target_z,
        },
        Scale3D = {
            X = numeric(scale.X), Y = numeric(scale.Y), Z = numeric(scale.Z),
        },
    }
end

local function align_instanced_people(component)
    if not valid(component) then return 0 end
    local count = numeric(component:GetInstanceCount()) or 0
    if count <= 0 then return 0 end
    local changed = 0
    local tolerance = Terrain.active.runtime
        .placeable_below_ground_tolerance_centimeters or 5.0
    local clearance = Terrain.active.runtime.guest_visual_clearance_centimeters or 162.0
    for index = 0, count - 1 do
        local transform = {}
        if component:GetInstanceTransform(index, transform, true) then
            local translation = transform.Translation
            local x, y, z = vector_values(translation)
            local ground = x and y and Terrain.height_at(x, y) or nil
            local target_z = z
            if ground and z and z < ground - tolerance then
                target_z = ground + clearance
                changed = changed + 1
            end
            if target_z ~= z then
                -- The native renderer rebuilds these transforms from its
                -- template-terrain cache on each tick. Update only buried
                -- instances after that pass; batching every entry is more
                -- expensive and has proven fragile through UE4SS's TArray
                -- marshalling.
                component:UpdateInstanceTransform(
                    index, plain_transform(transform, target_z), true,
                    true, true)
            end
        end
    end
    return changed
end

function Terrain.align_people_rendering()
    if not Terrain.active then return 0 end
    -- New builds consolidate StaffRoleActors into StaffRenderingActor.
    -- Enumerate the current world's public actor class so either renderer
    -- layout works without reading the subsystem's private containers.
    local changed = 0
    for _, actor in ipairs(current_actors("CrowdRenderingActor")) do
        changed = changed + align_instanced_people(actor.CrowdISM)
        changed = changed + align_instanced_people(actor.EquippedISM)
        changed = changed + align_instanced_people(actor.SnowboardISM)
    end
    return changed
end

function Terrain.align_event_definition(event_parameter)
    if not Terrain.active then return false end
    local event = parameter_value(event_parameter)
    if not event or not event.WorldLocation then return false end
    local location = event.WorldLocation
    local x, y, z = vector_values(location)
    local ground = x and y and Terrain.height_at(x, y) or nil
    if not ground or not z or z >= ground - 5.0 then return false end
    location.Z = ground + (Terrain.active.runtime.snow_offset_centimeters or 30.0)
    return true
end

function Terrain.dismiss_buried_events()
    if not Terrain.active then return 0 end
    local subsystem = current_object("EventSubsystem")
    if not valid(subsystem) then return 0 end
    local event_ids = {}
    for_each_value(subsystem:GetActiveEvents(), function(value)
        local event = parameter_value(value)
        local location = event and event.WorldLocation
        if location then
            local x, y, z = vector_values(location)
            local ground = x and y and Terrain.height_at(x, y) or nil
            if ground and z and z < ground - 5.0 then
                event_ids[#event_ids + 1] = event.EventId
            end
        end
    end)
    for _, event_id in ipairs(event_ids) do subsystem:DismissEvent(event_id) end
    local removed = #event_ids
    if removed > 0 then log(string.format("dismissed %d buried template event(s)", removed)) end
    return removed
end


local dynamic_error_seen = {}

local function guarded_dynamic(label, callback)
    local ok, result = pcall(callback)
    if not ok and not dynamic_error_seen[label] then
        dynamic_error_seen[label] = true
        log(label .. " grounding failed: " .. tostring(result))
    end
    return ok and result or 0
end

function Terrain.maintain_dynamic_grounding(frame)
    if not Terrain.active then return end
    guarded_dynamic("camera", Terrain.clamp_camera_to_surface)
    -- GuestsHot stores native struct values whose UE4SS wrappers are not
    -- stable across simulation ticks. The reconstructed native height cache
    -- now owns simulation grounding; only repair the rendered ISM copies
    -- here. Accessing GuestsHot every frame eventually crashes UE4SS.
    guarded_dynamic("guest rendering", Terrain.align_people_rendering)
    if frame % 60 ~= 1 then return end
    local snow_offset = Terrain.active.runtime.snow_offset_centimeters or 30.0
    guarded_dynamic("litter", function()
        local changed = 0
        for _, actor in ipairs(current_actors("LitterPropActor")) do
            if actor_to_surface(actor, snow_offset) then changed = changed + 1 end
        end
        return changed
    end)
    guarded_dynamic("event marker", function()
        local changed = 0
        for _, actor in ipairs(current_actors("EventMarkerActor")) do
            if actor_to_surface(actor, snow_offset + 100.0) then changed = changed + 1 end
        end
        return changed
    end)
    guarded_dynamic("trail label", function()
        local visualization = current_object("TrailVisualizationSubsystem")
        local label_offset = valid(visualization) and valid(visualization.Config)
            and numeric(visualization.Config.LabelHeightOffset) or 250.0
        local changed = 0
        for _, actor in ipairs(current_actors("TrailPathLabelActor")) do
            if actor_to_surface(actor, label_offset) then changed = changed + 1 end
        end
        return changed
    end)
    guarded_dynamic("trail visualization", Terrain.sync_trail_visualization)
end

local function current_world_context(context)
    local object = context and context:get()
    local world = UEHelpers.GetWorld()
    return valid(object) and valid(world) and belongs_to_world(Terrain.actor, world)
end

function Terrain.install_height_hooks()
    -- Native post-hooks receive (self, return_value, world_context, ...).
    -- Skipping only one argument shifts X onto the world UObject.
    local function ground_height(context, _, world_context, x, y)
        if not Terrain.active or not current_world_context(context) then return nil end
        x, y = tonumber(parameter_value(x)), tonumber(parameter_value(y))
        if not x or not y then return nil end
        return Terrain.height_at(x, y)
    end
    local function terrain_height(context, _, world_context, location)
        if not Terrain.active or not current_world_context(context) then return nil end
        local value = parameter_value(location)
        if not value then return nil end
        return Terrain.height_at(value.X, value.Y)
    end
    local contracts=require('compatibility_contracts')
    for _,definition in ipairs({
        {'height.ground','/Script/SkiResortSimulator.SkiResortFunctionLibrary:GetGroundHeightAtLocation',ground_height,contracts.ground_height},
        {'height.terrain','/Script/SkiResortSimulator.TerrainUtils:GetHeightAtLocation',terrain_height,contracts.terrain_height},
    }) do
        local path=definition[2]
        local ok, message = require('compatibility').hook(definition[1],path,'post',definition[3],definition[4])
        if not ok then log("height hook unavailable " .. path .. ": " .. tostring(message)) end
    end
end

Terrain.schedule = schedule
Terrain.build_skirt = build_skirt
Terrain.build_tile = build_tile
return Terrain
