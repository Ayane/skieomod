local UEHelpers = require("UEHelpers")
local Heightmap = require("heightmap")
local RenderMapping = require("render_mapping")
local Compatibility = require('compatibility')

-- A portable map contains source R16 and metric metadata. The loader creates
-- the Landscape in a neutral world, then binds every consumer to that source:
-- native CPU heights, G16 snow input, float32 native brush heights, packed
-- Landscape atlases/mips, derived slope/morphology/snow maps and procedural
-- collision. No stock map supplies terrain, bounds, cache pixels or topology.
local NativeTerrain = {
    installed = false,
    install_error = nil,
    cache = nil,
    height_texture = nil,
    landscape = nil,
    landscape_textures = {},
    landscape_materials = {},
    derived_textures = {},
}

local CLASS_PATH = "/Script/SkiResortSimulator.TerrainHeightCacheSubsystem"
local LANDSCAPE_COMPONENT_CLASS = "/Script/Landscape.LandscapeComponent"
local SOURCE_DIRECTORY = debug.getinfo(1, "S").source:match("^@(.*[/\\])[^/\\]+$")
local PROPERTY_DEFINITIONS = {
    { "SkiEOHeightSamples", "ArrayProperty", 0x48, "UInt16Property" },
    { "SkiEOHeightMin", "FloatProperty", 0x58 },
    { "SkiEOHeightRange", "FloatProperty", 0x5C },
    { "SkiEOGridWidth", "IntProperty", 0x80 },
    { "SkiEOGridHeight", "IntProperty", 0x84 },
    -- UE4SS does not publish DoubleProperty in this build. FVector2D uses two
    -- doubles in UE5, so preserve their bit patterns through uint64 fields.
    { "SkiEOOriginXBits", "UInt64Property", 0x88 },
    { "SkiEOOriginYBits", "UInt64Property", 0x90 },
    -- The sampler normalizes world XY against this full FBox2D.  Retaining
    -- the template map's upper bounds makes it read the correct R16 at the
    -- wrong coordinates even when the origin and spacing are replaced.
    { "SkiEOMaximumXBits", "UInt64Property", 0x98 },
    { "SkiEOMaximumYBits", "UInt64Property", 0xA0 },
    { "SkiEOOriginZ", "FloatProperty", 0xA8 },
    -- The native sampler interpolates between two absolute world altitudes.
    -- On stock maps the minimum happens to be zero, which made 0xAC look like
    -- a scale during the first layout inspection.
    { "SkiEOMaximumHeight", "FloatProperty", 0xAC },
    { "SkiEOSpacingX", "FloatProperty", 0xB0 },
    { "SkiEOSpacingY", "FloatProperty", 0xB4 },
    -- FVector4 is double-precision in UE5. Writing its four fields as raw
    -- bit patterns avoids UE4SS constructing a temporary reflected struct
    -- while the Landscape render thread is consuming the component.
    { "SkiEOHeightBiasXBits", "UInt64Property", 0x610, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOHeightBiasYBits", "UInt64Property", 0x618, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOHeightBiasZBits", "UInt64Property", 0x620, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOHeightBiasWBits", "UInt64Property", 0x628, nil,
        LANDSCAPE_COMPONENT_CLASS },
    -- FBox uses two UE5 double-precision vectors followed by its validity
    -- byte. Exposing the individual fields lets a portable R16 source rebuild
    -- the render bounds without requiring a cooked Landscape asset.
    { "SkiEOCachedMinXBits", "UInt64Property", 0x630, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOCachedMinYBits", "UInt64Property", 0x638, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOCachedMinZBits", "UInt64Property", 0x640, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOCachedMaxXBits", "UInt64Property", 0x648, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOCachedMaxYBits", "UInt64Property", 0x650, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOCachedMaxZBits", "UInt64Property", 0x658, nil,
        LANDSCAPE_COMPONENT_CLASS },
    { "SkiEOCachedBoxValid", "ByteProperty", 0x660, nil,
        LANDSCAPE_COMPONENT_CLASS },
}


local function valid(object)
    return object and object:IsValid()
end

local function unwrap(value)
    local ok, nested = pcall(function() return value:get() end)
    return ok and nested or value
end

local function belongs_to_world(object, world)
    if not valid(object) or not valid(world) then return false end
    local ok, object_world = pcall(function() return object:GetWorld() end)
    return ok and valid(object_world)
        and object_world:GetAddress() == world:GetAddress()
end

local function register_properties()
    if NativeTerrain.installed then return true end
    if NativeTerrain.install_error then return false, NativeTerrain.install_error end
    local compatible,detail=Compatibility.check('terrain.private_layout',require('compatibility_contracts').terrain)
    if not compatible then return false,detail end
    if type(RegisterCustomProperty) ~= "function" or type(PropertyTypes) ~= "table" then
        NativeTerrain.install_error = "UE4SS custom properties are unavailable"
        return false, NativeTerrain.install_error
    end
    for _, spec in ipairs(PROPERTY_DEFINITIONS) do
        local property_type = PropertyTypes[spec[2]]
        if property_type == nil then
            NativeTerrain.install_error = "UE4SS property type is unavailable: " .. spec[2]
            return false, NativeTerrain.install_error
        end
        local definition = {
            Name = spec[1],
            Type = property_type,
            BelongsToClass = spec[5] or CLASS_PATH,
            OffsetInternal = spec[3],
        }
        if spec[4] then
            local inner = PropertyTypes[spec[4]]
            if inner == nil then
                NativeTerrain.install_error = "UE4SS property type is unavailable: " .. spec[4]
                return false, NativeTerrain.install_error
            end
            definition.ArrayProperty = { Type = inner }
        end
        local ok, message = pcall(RegisterCustomProperty, definition)
        if not ok then
            NativeTerrain.install_error = string.format(
                "could not register native terrain field %s: %s",
                spec[1], tostring(message))
            return false, NativeTerrain.install_error
        end
    end
    NativeTerrain.installed = true
    return true
end

local function current_cache(world)
    for _, object in ipairs(FindAllOf("TerrainHeightCacheSubsystem") or {}) do
        if belongs_to_world(object, world) then return object end
    end
    return nil
end

local function current_object(class_name, world)
    for _, object in ipairs(FindAllOf(class_name) or {}) do
        if belongs_to_world(object, world) then return object end
    end
    return nil
end

-- Lua UObject wrappers do not keep Unreal objects alive. The snow renderer
-- also caches texture pointers outside the reflected cache properties, so
-- replacing those properties must not collect their previous textures while
-- this world is running. A rooted, unattached UMG panel owns image brushes
-- with reflected references; it never creates any visible UI. Reuse it and
-- release its children when a different world starts loading.
local function retain_texture(texture)
    if not valid(texture) then return end
    local world_address = (NativeTerrain.preparing_world or UEHelpers.GetWorld()):GetAddress()
    if not valid(NativeTerrain.texture_references) then
        local panel_class = StaticFindObject("/Script/UMG.VerticalBox")
        local transient = StaticFindObject("/Engine/Transient")
        assert(valid(panel_class) and valid(transient),
            "Unreal texture reference container is unavailable")
        NativeTerrain.texture_references = StaticConstructObject(
            panel_class, transient, 0, 0xC0,
            EInternalObjectFlags.RootSet, false, false, nil, 0, 0, 0)
        assert(valid(NativeTerrain.texture_references),
            "could not create Unreal texture reference container")
    end
    if NativeTerrain.texture_reference_world ~= world_address then
        NativeTerrain.texture_references:ClearChildren()
        NativeTerrain.texture_reference_world = world_address
        NativeTerrain.retained_texture_addresses = {}
    end
    local address = texture:GetAddress()
    if NativeTerrain.retained_texture_addresses[address] then return end
    local image = StaticConstructObject(
        StaticFindObject("/Script/UMG.Image"),
        NativeTerrain.texture_references, 0, 0x40, 0,
        false, false, nil, 0, 0, 0)
    assert(valid(image), "could not retain Unreal texture")
    image:SetBrushResourceObject(texture)
    assert(valid(NativeTerrain.texture_references:AddChild(image)),
        "could not attach Unreal texture reference")
    NativeTerrain.retained_texture_addresses[address] = true
end

local write_binary, read_all

local function replace_texture_data(destination, source, width, height)
    local job_path = SOURCE_DIRECTORY .. "native_swap.job"
    local status_path = SOURCE_DIRECTORY .. "native_swap.status"
    local written, message = write_binary(job_path, string.pack(
        "<c4I4I8I8I4I4", "SKTS", 1, destination:GetAddress(),
        source:GetAddress(), width, height))
    assert(written, "could not stage texture exchange: " .. tostring(message))
    os.remove(status_path)
    local helper, load_error = package.loadlib(
        SOURCE_DIRECTORY .. "skieo_native_terrain.dll", "skieo_swap_texture_data")
    assert(helper, tostring(load_error))
    local ok, call_error = pcall(helper)
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    assert(ok, tostring(call_error))
    assert(status and status:sub(1, 3) == "ok:", status or "texture exchange failed")
end

local function double_to_bits(value)
    -- Lua integers are signed, while the custom property is uint64. UE4SS
    -- preserves the same 64 bits when marshalling either representation.
    return string.unpack("<i8", string.pack("<d", value))
end

write_binary = function(path, bytes)
    local file, message = io.open(path, "wb")
    if not file then return false, message end
    local ok, write_error = file:write(bytes)
    file:close()
    if not ok then return false, write_error end
    return true
end

read_all = function(path)
    local file = io.open(path, "rb")
    if not file then return nil end
    local bytes = file:read("*a")
    file:close()
    return bytes
end

local function landscape_texture_path(index, mip)
    mip = mip or 0
    if mip == 0 then
        return SOURCE_DIRECTORY .. string.format(
            "native_landscape_%02d.png", index)
    end
    return SOURCE_DIRECTORY .. string.format(
        "native_landscape_%02d_mip%02d.png", index, mip)
end

local function landscape_bounds_path()
    return SOURCE_DIRECTORY .. "native_landscape.bounds"
end

local function remove_staged_textures()
    if not SOURCE_DIRECTORY then return end
    os.remove(SOURCE_DIRECTORY .. "native_terrain.png")
    os.remove(SOURCE_DIRECTORY .. "native_terrain.bmp")
    os.remove(SOURCE_DIRECTORY .. "native_placement_slope.png")
    os.remove(SOURCE_DIRECTORY .. "native_snow_redistribution.png")
    os.remove(SOURCE_DIRECTORY .. "native_terrain_morphology.png")
    os.remove(SOURCE_DIRECTORY .. "native_format.job")
    os.remove(SOURCE_DIRECTORY .. "native_format.status")
    os.remove(landscape_bounds_path())
    for index = 0, 15 do
        for mip = 0, 9 do
            os.remove(landscape_texture_path(index, mip))
            if mip == 0 then
                os.remove(SOURCE_DIRECTORY .. string.format(
                    "native_landscape_%02d.bmp", index))
            else
                os.remove(SOURCE_DIRECTORY .. string.format(
                    "native_landscape_%02d_mip%02d.bmp", index, mip))
            end
        end
    end
end

local function copy_samples_native(
    state, cache, samples, width, height, spacing_cm, height_scale_cm,
    maximum_x, maximum_y, origin_z, maximum_z, spacing_x, spacing_y, stage_only)
    if not SOURCE_DIRECTORY or type(package.loadlib) ~= "function" then
        return false, "native terrain helper loading is unavailable"
    end
    local source_path = SOURCE_DIRECTORY .. "native_terrain.r16"
    local job_path = SOURCE_DIRECTORY .. "native_terrain.job"
    local status_path = SOURCE_DIRECTORY .. "native_terrain.status"
    local texture_path = SOURCE_DIRECTORY .. "native_terrain.png"
    local helper_path = SOURCE_DIRECTORY .. "skieo_native_terrain.dll"
    local written, message = write_binary(source_path, state.bytes)
    if not written then
        return false, "could not stage source heightmap: " .. tostring(message)
    end
    local flags = (state.little_endian and 1 or 0)
        + (state.row_order == "south_to_north" and 2 or 0)
    -- Version 3 lets the helper update the samples and their complete native
    -- sampling transform in one operation. This avoids partial writes through
    -- UE4SS's synthetic UInt64 properties leaving the template FBox2D maxima
    -- behind while the R16 data itself has already been replaced.
    local job = string.pack("<c4I4I8I8I4I4I4I4I4ddddddffff", "SKNT", stage_only and 4 or 3,
        stage_only and 0 or samples:GetArrayDataAddress(), stage_only and 0 or cache:GetAddress(),
        state.width, state.height, width, height, flags,
        spacing_cm, height_scale_cm,
        state.origin_x, state.origin_y, maximum_x, maximum_y,
        origin_z, maximum_z, spacing_x, spacing_y)
    written, message = write_binary(job_path, job)
    if not written then
        os.remove(source_path)
        return false, "could not stage native terrain job: " .. tostring(message)
    end
    os.remove(status_path)
    remove_staged_textures()
    local loader, load_error = package.loadlib(
        helper_path, "skieo_copy_heightmap")
    if not loader then
        os.remove(job_path)
        os.remove(source_path)
        return false, "could not load native terrain helper: " .. tostring(load_error)
    end
    local ok, call_error = pcall(loader)
    local status = read_all(status_path)
    local landscape_bounds = read_all(landscape_bounds_path())
    os.remove(landscape_bounds_path())
    os.remove(job_path)
    os.remove(source_path)
    if not ok then return false, "native terrain helper failed: " .. tostring(call_error) end
    if not status or status:sub(1, 3) ~= "ok:" then
        return false, status or "native terrain helper produced no status"
    end
    if not landscape_bounds or #landscape_bounds ~= 32 * 32 * 4 then
        return false, "native terrain helper produced invalid Landscape bounds"
    end
    return true, status, texture_path, landscape_bounds
end

local function run_hub_helper(export_name, job_bytes)
    if not SOURCE_DIRECTORY or type(package.loadlib) ~= "function" then
        return false, "native hub helper loading is unavailable"
    end
    local world = UEHelpers.GetWorld()
    local subsystem = current_object("HubConnectivitySubsystem", world)
    if not valid(subsystem) then
        return false, "hub connectivity subsystem is unavailable"
    end
    local job_path = SOURCE_DIRECTORY .. "native_hubs.job"
    local status_path = SOURCE_DIRECTORY .. "native_hubs.status"
    local helper_path = SOURCE_DIRECTORY .. "skieo_native_terrain.dll"
    local written, message = write_binary(job_path, job_bytes or
        string.pack("<c4I4I8", "SKNH", 1, subsystem:GetAddress()))
    if not written then
        return false, "could not stage native hub job: " .. tostring(message)
    end
    os.remove(status_path)
    local loader, load_error = package.loadlib(
        helper_path, export_name)
    if not loader then
        os.remove(job_path)
        return false, "could not load native hub helper: " .. tostring(load_error)
    end
    local ok, call_error = pcall(loader)
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    if not ok then
        return false, "native hub helper failed: " .. tostring(call_error)
    end
    if not status or status:sub(1, 3) ~= "ok:" then
        return false, status or "native hub helper produced no status"
    end
    return true, status
end

function NativeTerrain.refresh_skiability()
    local world=UEHelpers.GetWorld()
    local map=current_object('TrailMapSubsystem',world)
    local cache=current_object('SnowStateCache',world)
    if not valid(map) or not valid(cache) or not cache:IsCacheValid() then
        return false,'snow readback is not ready'
    end
    local cls=StaticFindObject('/Script/SkiResortSimulator.TrailMapSubsystem')
    local job_path=SOURCE_DIRECTORY..'native_skiability.job'
    local status_path=SOURCE_DIRECTORY..'native_terrain.status'
    local written,message=write_binary(job_path,string.pack('<c4I4I8I8','SKSK',1,map:GetAddress(),cls:GetAddress()))
    if not written then return false,message end
    os.remove(status_path)
    local fn,failure=package.loadlib(SOURCE_DIRECTORY..'skieo_native_terrain.dll','skieo_refresh_skiability')
    if not fn then os.remove(job_path);return false,failure end
    local ok,error=pcall(fn);local status=read_all(status_path)
    os.remove(job_path);os.remove(status_path)
    return ok and status and status:sub(1,3)=='ok:',status or tostring(error)
end

function NativeTerrain.name_hubs(names)
    if #names==0 then return true end
    assert(#names<=64,'too many hub names in one update')
    local sub=current_object('HubConnectivitySubsystem',UEHelpers.GetWorld())
    local cls=StaticFindObject('/Script/SkiResortSimulator.HubConnectivitySubsystem')
    assert(valid(sub) and valid(cls),'hub names owner unavailable')
    local parts={string.pack('<c4I4I8I8I4I4','SKHN',1,sub:GetAddress(),cls:GetAddress(),#names,0)}
    for _,name in ipairs(names) do local id=name.id
        assert(type(name.name)=='string' and #name.name<=128,'invalid hub name')
        parts[#parts+1]=string.pack('<I4I4I4I4I4',id.A&0xffffffff,id.B&0xffffffff,id.C&0xffffffff,id.D&0xffffffff,#name.name)..name.name
    end
    local job_path,status_path=SOURCE_DIRECTORY..'native_hub_names.job',SOURCE_DIRECTORY..'native_terrain.status'
    local written,message=write_binary(job_path,table.concat(parts));if not written then return false,message end
    os.remove(status_path)
    local fn,failure=package.loadlib(SOURCE_DIRECTORY..'skieo_native_terrain.dll','skieo_name_hubs')
    if not fn then os.remove(job_path);return false,failure end
    local ok,error=pcall(fn);local status=read_all(status_path)
    os.remove(job_path);os.remove(status_path)
    return ok and status and status:sub(1,3)=='ok:',status or tostring(error)
end

-- Only new source resorts use this bridge; existing saves retain their
-- native roster and hiring pool. Call from the game thread between hires.
function NativeTerrain.refresh_staff_pool(subsystem)
    assert(valid(subsystem) and subsystem:IsA('/Script/SkiResortSimulator.StaffSubsystem')
        and belongs_to_world(subsystem, UEHelpers.GetWorld()), 'current staff subsystem is unavailable')
    local settings = subsystem:GetSettings()
    assert(valid(settings), 'staff settings are unavailable')
    local job_path, status_path = SOURCE_DIRECTORY .. 'native_staff.job',
        SOURCE_DIRECTORY .. 'native_staff.status'
    local written, message = write_binary(job_path, string.pack('<c4I4I8I8I4I4',
        'SKNS',1,subsystem:GetAddress(),settings:GetAddress(),#subsystem:GetHiringPool(),0))
    assert(written, message)
    os.remove(status_path)
    local helper, load_error = package.loadlib(SOURCE_DIRECTORY .. 'skieo_native_terrain.dll',
        'skieo_refresh_staff_pool')
    local ok, call_error = false, load_error
    if helper then ok, call_error = pcall(helper) end
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    assert(ok, call_error)
    assert(status and status:sub(1,3) == 'ok:', status or 'staff pool refresh failed')
    return status
end

-- Replace each native per-id terrain pad after the final source alignment.
-- Keep native sculpt layers and snow; clearing BrushDeltaRT hides the symptom
-- but also discards the visible player edits stored in that render target.
function NativeTerrain.refresh_placeable_pads(actors)
    if #actors == 0 then return true, 'no terrain pads to refresh' end
    require('compatibility').require('terrain.pads', require('compatibility_contracts').terrain_pads)
    local world = UEHelpers.GetWorld()
    local pieces = {string.pack('<c4I4I4I4', 'SKPD', 1, #actors, 0)}
    for _, actor in ipairs(actors) do
        assert(valid(actor) and belongs_to_world(actor, world)
            and actor:IsA('/Script/SkiResortSimulator.PlaceableActor')
            and not actor:IsActorBeingDestroyed() and not actor.bIsPreview,
            'terrain pad owner is not a live placeable in the current world')
        pieces[#pieces+1] = string.pack('<I8I8', actor:GetAddress(), actor:GetClass():GetAddress())
    end
    local job_path, status_path = SOURCE_DIRECTORY..'native_pads.job', SOURCE_DIRECTORY..'native_terrain.status'
    local written, message = write_binary(job_path, table.concat(pieces))
    if not written then return false, message end
    os.remove(status_path)
    local helper, failure = package.loadlib(SOURCE_DIRECTORY..'skieo_native_terrain.dll', 'skieo_refresh_placeable_pads')
    local ok, detail = false, failure
    if helper then ok, detail = pcall(helper) end
    local status = read_all(status_path)
    os.remove(job_path); os.remove(status_path)
    return ok and status and status:sub(1,3)=='ok:' or false,
        not ok and tostring(detail) or status or 'native terrain pads produced no status'
end

-- Replays the stock Build-tool registration once late-created actors have
-- their final terrain-aligned transforms. The helper batches members and
-- performs one graph rebuild, as for an ordinary player-built lift.
function NativeTerrain.register_placeable_hubs(lifts, buildings)
    lifts = lifts or {}
    buildings = buildings or {}
    local world = UEHelpers.GetWorld()
    local subsystem = current_object("HubConnectivitySubsystem", world)
    if not valid(subsystem) then
        return false, "hub connectivity subsystem is unavailable"
    end
    local pieces = {
        string.pack("<c4I4I8I4I4", "SKHR", 1,
            subsystem:GetAddress(), #lifts + #buildings, 0),
    }
    local function append(objects, kind, label)
        for index, actor in ipairs(objects) do
            if not valid(actor) or not belongs_to_world(actor, world) then
                error(string.format("%s %d is not in the current world",
                    label, index), 3)
            end
            pieces[#pieces + 1] = string.pack(
                "<I8I4I4", actor:GetAddress(), kind, 0)
        end
    end
    local ok, message = pcall(function()
        append(lifts, 1, "lift")
        append(buildings, 2, "building")
    end)
    if not ok then return false, tostring(message) end
    if #lifts + #buildings == 0 then
        return false, "no placeables were supplied for hub registration"
    end
    return run_hub_helper(
        "skieo_register_placeable_hubs", table.concat(pieces))
end

-- Inspect the private TSet counters without running any native gameplay code.
-- This lets the loader distinguish active members from freed sparse slots.
function NativeTerrain.probe_hubs()
    return run_hub_helper("skieo_probe_hubs")
end

function NativeTerrain.probe_hub_coverage()
    return run_hub_helper("skieo_probe_hub_coverage")
end

-- Re-register the validated FHubMemberInfo values left in the subsystem's
-- sparse slots by late source-map placement. The game then recreates the
-- compound hub actors and their routing graph through its own native path.
function NativeTerrain.restore_hubs()
    return run_hub_helper("skieo_restore_hubs")
end

-- Late source-map placeables reach the public HubConnectivity member set, but
-- UE 5.8 exposes only per-trail callbacks to Blueprints. Keep the guarded
-- private rebuild available for diagnostics; normal loading uses the read-only
-- probe until its lifecycle can be reproduced through public registrations.
function NativeTerrain.rebuild_hubs()
    return run_hub_helper("skieo_rebuild_hubs")
end

function NativeTerrain.refresh_navigation()
    local world = UEHelpers.GetWorld()
    local navigation = current_object("WalkNavSubsystem", world)
    local class = StaticFindObject("/Script/SkiResortSimulator.WalkNavSubsystem")
    if not valid(navigation) or not valid(class) then
        return false, "native navigation subsystem is unavailable"
    end
    local job_path = SOURCE_DIRECTORY .. "native_navigation.job"
    local status_path = SOURCE_DIRECTORY .. "native_terrain.status"
    local written, message = write_binary(job_path,
        string.pack("<c4I4I8I8", "SKNV", 1, navigation:GetAddress(), class:GetAddress()))
    if not written then return false, message end
    os.remove(status_path)
    local helper, failure = package.loadlib(
        SOURCE_DIRECTORY .. "skieo_native_terrain.dll", "skieo_refresh_navigation")
    local ok = false
    if helper then ok, failure = pcall(helper) end
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    if not ok then return false, tostring(failure) end
    return status and status:sub(1,3) == "ok:" or false,
        status or "native navigation helper produced no status"
end

local function import_texture(rendering, context, path, width, height, label)
    local ok, texture_or_message = pcall(function()
        return rendering:ImportFileAsTexture2D(context, path)
    end)
    os.remove(path)
    if not ok or not valid(texture_or_message) then
        return nil, string.format("could not import %s: %s",
            label, tostring(texture_or_message))
    end
    local texture = texture_or_message
    local retained, retain_error = pcall(retain_texture, texture)
    if not retained then return nil, tostring(retain_error) end
    local dimensions_ok, dimensions_match = pcall(function()
        return texture:Blueprint_GetSizeX() == width
            and texture:Blueprint_GetSizeY() == height
    end)
    if not dimensions_ok or not dimensions_match then
        return nil, label .. " dimensions differ from the native grid"
    end
    return texture
end

-- Unreal's runtime importer preserves every sample of a grayscale 16-bit PNG
-- but labels its platform data PF_G16. PlacementSlopeTex and
-- SnowRedistributionTex are PF_R16F. Their generated PNG samples therefore
-- contain binary16 bit patterns, and this guarded helper changes the platform
-- tag before UpdateResource creates the final GPU view. Both formats are two
-- bytes per pixel, so no allocation or object ownership is changed.
local function reinterpret_as_r16f(texture, width, height)
    if not SOURCE_DIRECTORY or type(package.loadlib) ~= "function" then
        return false, "native texture format conversion is unavailable"
    end
    local job_path = SOURCE_DIRECTORY .. "native_format.job"
    local status_path = SOURCE_DIRECTORY .. "native_format.status"
    local helper_path = SOURCE_DIRECTORY .. "skieo_native_terrain.dll"
    local job = string.pack("<c4I4I8I4I4I1I1c6",
        "SKTF", 1, texture:GetAddress(), width, height,
        4, 21, string.rep("\0", 6))
    local written, message = write_binary(job_path, job)
    if not written then
        return false, "could not stage texture format job: " .. tostring(message)
    end
    os.remove(status_path)
    local loader, load_error = package.loadlib(
        helper_path, "skieo_reinterpret_texture_format")
    if not loader then
        os.remove(job_path)
        return false, "could not load texture format helper: "
            .. tostring(load_error)
    end
    local ok, call_error = pcall(loader)
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    if not ok then
        return false, "native texture format helper failed: "
            .. tostring(call_error)
    end
    if not status or status:sub(1, 3) ~= "ok:" then
        return false, status or "native texture format helper produced no status"
    end
    return true, status
end

-- The game initializes these maps before source collision is ready. Rebuild
-- them from the authoritative R16 at the new world's native resolutions.
-- Preserve their UObject identities because the renderer caches those refs.
local function install_derived_textures(cache, rendering, context, width, height)
    local update_resource = StaticFindObject(
        "/Script/Engine.CanvasRenderTarget2D:UpdateResource")
    if not valid(update_resource) then
        remove_staged_textures()
        return false, "texture resource refresh function is unavailable"
    end
    local redistribution = unwrap(cache.SnowRedistributionTex)
    assert(valid(redistribution), "native coarse terrain texture is unavailable")
    local coarse_width, coarse_height = redistribution:Blueprint_GetSizeX(), redistribution:Blueprint_GetSizeY()
    local definitions = {
        {
            field = "PlacementSlopeTex",
            file = "native_placement_slope.png",
            width = width,
            height = height,
            float_r = true,
            minimum_bytes = width * height * 2,
        },
        {
            field = "SnowRedistributionTex",
            file = "native_snow_redistribution.png",
            width = coarse_width,
            height = coarse_height,
            float_r = true,
            minimum_bytes = coarse_width * coarse_height * 2,
        },
        {
            field = "TerrainMorphologyTex",
            file = "native_terrain_morphology.png",
            width = coarse_width,
            height = coarse_height,
            float_r = false,
            minimum_bytes = coarse_width * coarse_height * 8,
        },
    }
    local textures, statuses = {}, {}
    for _, definition in ipairs(definitions) do
        local previous = unwrap(cache[definition.field])
        retain_texture(previous)
        local path = SOURCE_DIRECTORY .. definition.file
        local texture, import_error = import_texture(
            rendering, context, path, definition.width, definition.height,
            definition.field)
        if not texture then
            remove_staged_textures()
            return false, import_error
        end
        local configured, configuration_error = pcall(function()
            assert(texture:Blueprint_GetMemorySize() >= definition.minimum_bytes,
                definition.field .. " lost its 16-bit samples")
            texture.SRGB = false
            texture.Filter = 1
            texture.AddressX = 1
            texture.AddressY = 1
            texture.NeverStream = true
            if definition.float_r then
                local converted, conversion_status = reinterpret_as_r16f(
                    texture, definition.width, definition.height)
                assert(converted, conversion_status)
                statuses[#statuses + 1] = conversion_status
                texture.CompressionSettings = 15
            else
                -- RGBA16 PNGs import as PF_R16G16B16A16_UNORM (62).
                -- The stock map uses its equivalent legacy format (19);
                -- the data exchange validates and preserves that format.
                texture.CompressionSettings = 0
            end
            assert(valid(previous), "original derived texture is unavailable")
            replace_texture_data(previous, texture,
                definition.width, definition.height)
            previous.SRGB = false
            previous.NeverStream = true
            update_resource(previous)
            -- Keep the native renderer's cached UObject pointer valid and
            -- update every existing material binding through that same object.
            texture = previous
        end)
        if not configured then
            remove_staged_textures()
            return false, "could not install " .. definition.field .. ": "
                .. tostring(configuration_error)
        end
        textures[definition.field] = texture
    end
    NativeTerrain.derived_textures = textures
    return true, {
        count = #definitions,
        placement_size = width,
        coarse_size = coarse_width,
        coarse_height = coarse_height,
        format_statuses = statuses,
    }
end

local function install_texture_mips(destination, template_texture, sources, portable)
    if not SOURCE_DIRECTORY or type(package.loadlib) ~= "function" then
        return false, "native texture mip installation is unavailable"
    end
    if not valid(destination) or (template_texture and not valid(template_texture))
        or (portable and (#sources < 1 or #sources > 10))
        or (not portable and #sources ~= 10) then
        return false, "Landscape texture mip set is incomplete"
    end
    local pieces = {
        string.pack("<c4I4I8I8I4I4", "SKTM", portable and 5 or (template_texture and 3 or 4),
            destination:GetAddress(), template_texture and template_texture:GetAddress() or 0,
            #sources, 0),
    }
    for mip, source in ipairs(sources) do
        if not valid(source) then
            return false, string.format(
                "Landscape texture mip %d is invalid", mip - 1)
        end
        pieces[#pieces + 1] = string.pack("<I8", source:GetAddress())
    end
    for _ = #sources + 1, 10 do pieces[#pieces + 1] = string.pack("<I8", 0) end

    local job_path = SOURCE_DIRECTORY .. "native_mips.job"
    local status_path = SOURCE_DIRECTORY .. "native_mips.status"
    local helper_path = SOURCE_DIRECTORY .. "skieo_native_terrain.dll"
    local written, message = write_binary(job_path, table.concat(pieces))
    if not written then
        return false, "could not stage texture mip job: " .. tostring(message)
    end
    os.remove(status_path)
    local loader, load_error = package.loadlib(
        helper_path, "skieo_install_texture_mips")
    if not loader then
        os.remove(job_path)
        return false, "could not load texture mip helper: "
            .. tostring(load_error)
    end
    local ok, call_error = pcall(loader)
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    if not ok then
        return false, "native texture mip helper failed: "
            .. tostring(call_error)
    end
    if not status or status:sub(1, 3) ~= "ok:" then
        return false, status or "native texture mip helper produced no status"
    end
    return true, status
end

NativeTerrain.install_portable_texture_mips = function(sources)
    return install_texture_mips(sources[1], nil, sources, true)
end

NativeTerrain.retain_texture = retain_texture

local function install_height_texture(texture_path, width, height)
    local rendering = StaticFindObject(
        "/Script/Engine.Default__KismetRenderingLibrary")
    local context = UEHelpers.GetWorldContextObject()
    if not valid(rendering) or not valid(context) then
        os.remove(texture_path)
        return false, "runtime texture importer is unavailable"
    end
    local texture, import_error = import_texture(
        rendering, context, texture_path, width, height,
        "native height texture")
    if not texture then return false, import_error end
    local configured, configuration_error = pcall(function()
        assert(texture:Blueprint_GetSizeX() == width
            and texture:Blueprint_GetSizeY() == height,
            "imported height texture dimensions differ from the native grid")
        assert(texture:Blueprint_GetMemorySize() >= width * height * 2,
            "native height texture lost its 16-bit samples")
        -- Match H_<map>_Out on the stock maps. The R16 sample is height data,
        -- not colour, and must not be sampled through sRGB conversion. A
        -- grayscale 16-bit PNG imports as G16, whose GPU format has no sRGB
        -- view, while retaining all portable R16 source samples.
        texture.SRGB = false
        texture.CompressionSettings = 7
        texture.Filter = 3
        texture.AddressX = 0
        texture.AddressY = 0

        local world = UEHelpers.GetWorld()
        local snow = current_object("SnowSimulationSubsystem", world)
        local brush = current_object("TerrainBrushSubsystem", world)
        assert(valid(snow), "snow simulation subsystem is unavailable")
        assert(valid(brush), "terrain brush subsystem is unavailable")
        retain_texture(unwrap(snow.HeightmapTexture_GPU))
        retain_texture(unwrap(brush.BaseHeightTex))
        -- Save restoration can supply an edited height texture to the native
        -- view extension before our final source texture replaces it.
        NativeTerrain.previous_snow_height_texture = unwrap(snow.HeightmapTexture_GPU)
        snow.HeightmapTexture_GPU = texture
        -- TerrainBrush owns a PF_R32_FLOAT texture and writes float32 world
        -- heights into its bulk data. Sharing the G16 snow texture corrupts
        -- that allocation when the first building flattens its pad. Invalidate
        -- its previous base: the native brush rebuilds the correct format from
        -- our now-authoritative CPU cache on its next request.
        brush.BaseHeightTex = nil
        -- Snow depth is weather state, not cooked terrain data. Preserve the
        -- native simulation while replacing only the base
        -- height reference; ClearSnow here would leave every imported trail
        -- temporarily unskiable until a new storm accumulated enough depth.
    end)
    if not configured then
        return false, "could not install native height texture: "
            .. tostring(configuration_error)
    end
    NativeTerrain.height_texture = texture
    return true, texture:GetFullName(), rendering, context
end

-- The atlas and component topology were constructed before BeginPlay. Keep
-- this Landscape for native bounds/cache initialization, and render the source
-- procedural surface: generic materials have a cooked LocalVertexFactory
-- variant, whereas Landscape shader permutations live inside cooked maps.
local function finish_landscape(state)
    state = state.native_encoding or state
    local landscape = NativeTerrain.landscape
    if not state.independent_world or not valid(landscape) then
        return false, 'source Landscape is unavailable'
    end
    -- Bounds queries explicitly include collidable components. The fresh
    -- Landscape has no physical heightfield; query-only bounds must remain
    -- enabled for hub/navigation/environment code throughout this world.
    landscape:SetActorEnableCollision(true)
    landscape:SetActorHiddenInGame(true)
    return true, {
        actor = landscape:GetFullName(),
        texture_count = #NativeTerrain.landscape_textures,
        mip_count = #NativeTerrain.landscape_textures * 10,
        location_z = state.origin_z + state.height_offset_cm
            + 32768 * state.height_scale_cm,
        scale_z = state.height_scale_cm * 128,
    }
end

local function raw_at(state, column, row)
    if state.row_order == "south_to_north" then
        row = state.height - 1 - row
    end
    local byte_index = (row * state.width + column) * 2 + 1
    local first, second = state.bytes:byte(byte_index, byte_index + 1)
    if state.little_endian then return first + second * 256 end
    return first * 256 + second
end

local function resampled_raw(state, column, row, width, height)
    if width == state.width and height == state.height then
        return raw_at(state, column, row)
    end
    local source_x = column * (state.width - 1) / (width - 1)
    local source_y = row * (state.height - 1) / (height - 1)
    local x0, y0 = math.floor(source_x), math.floor(source_y)
    local x1 = math.min(state.width - 1, x0 + 1)
    local y1 = math.min(state.height - 1, y0 + 1)
    local tx, ty = source_x - x0, source_y - y0
    local north = raw_at(state, x0, y0) * (1.0 - tx)
        + raw_at(state, x1, y0) * tx
    local south = raw_at(state, x0, y1) * (1.0 - tx)
        + raw_at(state, x1, y1) * tx
    return math.floor(north * (1.0 - ty) + south * ty + 0.5)
end

local function cache_height_limits(state)
    local minimum = state.origin_z + state.height_offset_cm
    local amplitude = state.height_scale_cm * 65536.0
    return minimum, minimum + amplitude, amplitude
end

local function float32_matches(actual,expected)
    -- Reflected FloatProperties round centimetres to binary32. Above 2,621 m
    -- a half-ULP can exceed the old 0.01 cm validation tolerance.
    local rounded=string.unpack('<f',string.pack('<f',expected))
    return actual==rounded or math.abs(actual-expected)<0.01
end

-- The native terrain view extension keeps its own texture references and
-- sampling bounds. Updating the reflected subsystem fields alone leaves
-- cliff shading clamped to the template map's central square.
local function install_render_mapping(state, cache)
    if not SOURCE_DIRECTORY or type(package.loadlib) ~= "function" then
        return false, "native terrain render mapping is unavailable"
    end
    local world = UEHelpers.GetWorld()
    local environment = current_object("LevelEnvironmentSettings", world)
    if not valid(environment) then
        return false, "terrain render mapping context is unavailable"
    end
    local textures = {
        NativeTerrain.height_texture,
        unwrap(environment.HeightmapReference),
        valid(NativeTerrain.previous_snow_height_texture)
            and NativeTerrain.previous_snow_height_texture
            or unwrap(environment.HeightmapReference),
        unwrap(cache.WindExposureTex),
        unwrap(cache.CanopyTex),
        unwrap(cache.TerrainMorphologyTex),
        unwrap(cache.PlacementSlopeTex),
    }
    local addresses = {}
    for index = 1, 7 do
        if not valid(textures[index]) then
            return false, "terrain render mapping texture is unavailable"
        end
        addresses[index] = textures[index]:GetAddress()
    end
    local minimum_z, maximum_z = cache_height_limits(state)
    local pieces = {string.pack("<c4I4I8I8I8I8I8I8I8", "SKTR", 2,
        table.unpack(addresses)), string.pack("<ffffff",
        state.origin_x, state.origin_y,
        state.origin_x + (state.width - 1) * state.spacing_cm,
        state.origin_y + (state.height - 1) * state.spacing_cm,
        minimum_z, maximum_z)}
    pieces[#pieces + 1] = string.pack("<I8", world:GetAddress())
    local job_path = SOURCE_DIRECTORY .. "native_render.job"
    local status_path = SOURCE_DIRECTORY .. "native_render.status"
    local written, message = write_binary(job_path, table.concat(pieces))
    if not written then
        return false, "could not stage terrain render mapping: " .. tostring(message)
    end
    os.remove(status_path)
    local helper, load_error = package.loadlib(
        SOURCE_DIRECTORY .. "skieo_native_terrain.dll", "skieo_update_render_mapping")
    if not helper then
        os.remove(job_path)
        return false, "could not load terrain render mapping helper: " .. tostring(load_error)
    end
    local ok, call_error = pcall(helper)
    local status = read_all(status_path)
    os.remove(job_path)
    os.remove(status_path)
    if not ok then return false, "terrain render mapping failed: " .. tostring(call_error) end
    if not status or status:sub(1, 3) ~= "ok:" then
        return false, status or "terrain render mapping helper produced no status"
    end
    -- The snow/cliff material has a second XY mapping in the level's weather
    -- collection. Its cooked bounds also clamp sampling at Sugar Bowl's edges.
    local configured, configuration_error = pcall(function()
        local collection = unwrap(environment.WeatherMPC)
        local library = StaticFindObject("/Script/Engine.Default__KismetMaterialLibrary")
        assert(valid(collection) and valid(library), "weather material mapping is unavailable")
        local bounds = {
            { "WorldBoundsMin", state.origin_x, state.origin_y },
            { "WorldBoundsMax",
                state.origin_x + (state.width - 1) * state.spacing_cm,
                state.origin_y + (state.height - 1) * state.spacing_cm },
        }
        for _, bound in ipairs(bounds) do
            local name = UEHelpers.FindOrAddFName(bound[1])
            local previous = library:GetVectorParameterValue(world, collection, name)
            library:SetVectorParameterValue(world, collection, name,
                { R = bound[2], G = bound[3], B = previous.B, A = previous.A })
        end
    end)
    if not configured then
        return false, "could not update weather material bounds: " .. tostring(configuration_error)
    end
    print("[SkiEO-CustomMaps] " .. status .. "\n")
    return true, status
end

local function cache_is_ready(cache)
    if not valid(cache) then return false end
    local ok, ready = pcall(function()
        local width, height = cache.SkiEOGridWidth, cache.SkiEOGridHeight
        return width >= 2 and height >= 2
            and cache.SkiEOHeightSamples:GetArrayNum() == width * height
    end)
    return ok and ready
end

local function schedule_populate(
    delay_ms, state, done, progress, is_current, attempt, stability, retry_count)
    -- UE4SS keeps only a weak registry reference for some delayed Lua
    -- actions. Retain both closures explicitly until they have run; otherwise
    -- the 15-second cache-settling loop can be collected after a few ticks.
    NativeTerrain.pending_callback = function()
        NativeTerrain.game_callback = function()
            NativeTerrain.pending_handle = nil
            NativeTerrain.pending_callback = nil
            NativeTerrain.populate(
                state, done, progress, is_current, attempt, stability, retry_count)
            NativeTerrain.game_callback = nil
        end
        ExecuteInGameThread(NativeTerrain.game_callback)
    end
    if type(ExecuteInGameThreadWithDelay) == 'function' then
        NativeTerrain.pending_handle = ExecuteInGameThreadWithDelay(
            delay_ms, NativeTerrain.pending_callback)
    else
        NativeTerrain.pending_handle = ExecuteWithDelay(
            delay_ms, NativeTerrain.pending_callback)
    end
end

-- Stage engine textures from portable data before travel. No game world or
-- previously allocated terrain cache is required here.
function NativeTerrain.check_compatibility()
    return pcall(function()
        Compatibility.require_startup('events')
        local contracts=require('compatibility_contracts')
        Compatibility.require('placement.private_layout',contracts.placement)
        Compatibility.require('terrain.private_layout',contracts.terrain)
        Compatibility.require('saves.session_layout',contracts.session)
    end)
end

function NativeTerrain.prepare_world(state)
    -- Refuse before staging/travel if a required private bridge moved.
    assert(NativeTerrain.check_compatibility())
    local source = state
    state = Heightmap.native_state(state)
    local width, height = 2017, 2017
    local minimum, maximum = cache_height_limits(state)
    local spacing_x = (state.width - 1) * state.spacing_cm / (width - 1)
    local spacing_y = (state.height - 1) * state.spacing_cm / (height - 1)
    local ok, message, path, bounds = copy_samples_native(state, nil, nil,
        width, height, spacing_x, state.height_scale_cm,
        state.origin_x + (state.width - 1) * state.spacing_cm,
        state.origin_y + (state.height - 1) * state.spacing_cm,
        minimum, maximum, spacing_x, spacing_y, true)
    assert(ok, message)
    state.bootstrap = { width = width, height = height, spacing_x = spacing_x,
        spacing_y = spacing_y, height_path = path, bounds = bounds }
    source.bootstrap = state.bootstrap
    return source
end

local function initialize_array(owner, kind, values)
    local pieces = {string.pack('<c4I4I8I8I4I4', 'SKIA', 1,
        owner:GetAddress(), owner:GetClass():GetAddress(), kind, #values)}
    for _, value in ipairs(values) do
        pieces[#pieces + 1] = string.pack('<I8', type(value) == 'number'
            and value or value:GetAddress())
    end
    local path = SOURCE_DIRECTORY .. 'native_array.job'
    assert(write_binary(path, table.concat(pieces)))
    local status_path = SOURCE_DIRECTORY .. 'native_terrain.status'
    os.remove(status_path)
    local helper, message = package.loadlib(SOURCE_DIRECTORY .. 'skieo_native_terrain.dll',
        'skieo_initialize_landscape_array')
    assert(helper, message)
    local ok, failure = pcall(helper)
    local status = read_all(status_path)
    os.remove(path)
    assert(ok, failure)
    assert(status and status:sub(1,3) == 'ok:', status or 'runtime array initialization failed')
end

function NativeTerrain.bootstrap_world(state, world)
    local source = state
    state = state.native_encoding or state
    assert(register_properties())
    NativeTerrain.preparing_world = world
    local ok, result = pcall(function()
        local data = assert(state.bootstrap, 'terrain must be staged before travel')
        local rendering = StaticFindObject('/Script/Engine.Default__KismetRenderingLibrary')
        local update = StaticFindObject('/Script/Engine.CanvasRenderTarget2D:UpdateResource')
        local materials = StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary')
        local gameplay = UEHelpers.GetGameplayStatics()
        local guid_library = StaticFindObject('/Script/Engine.Default__KismetGuidLibrary')
        local parent = LoadAsset('/Game/Materials/Terrain/M_Terrain.M_Terrain')
        assert(valid(parent), 'terrain material is unavailable')
        local texture, message = import_texture(rendering, world, data.height_path,
            data.width, data.height, 'source world heightmap')
        assert(texture, message)
        texture.SRGB, texture.NeverStream = false, true
        texture.CompressionSettings, texture.Filter = 7, 3
        texture.AddressX, texture.AddressY = 1, 1
        update(texture)
        NativeTerrain.height_texture = texture
        local atlases = {}
        for tile = 0,15 do
            local sources = {}
            for mip = 0,9 do
                local side = math.floor(512 / 2^mip)
                local donor, failure = import_texture(rendering, world,
                    landscape_texture_path(tile,mip), side,side,'source Landscape mip')
                assert(donor, failure)
                donor.SRGB, donor.NeverStream = false,true
                donor.Filter, donor.AddressX, donor.AddressY = 3,1,1
                update(donor)
                sources[#sources+1] = donor
            end
            local installed, failure = install_texture_mips(sources[1], nil, sources)
            assert(installed, failure)
            sources[1].LODGroup = 24
            update(sources[1])
            atlases[tile+1] = sources[1]
        end
        local transform = {
            Rotation={X=0,Y=0,Z=0,W=1},
            Translation={X=state.origin_x,Y=state.origin_y,
                Z=state.origin_z+state.height_offset_cm+32768*state.height_scale_cm},
            Scale3D={X=data.spacing_x,Y=data.spacing_y,Z=state.height_scale_cm*128},
        }
        local landscape = gameplay:BeginDeferredActorSpawnFromClass(world,
            StaticFindObject('/Script/Landscape.Landscape'), transform,1,nil,0)
        assert(valid(landscape), 'could not construct source Landscape')
        landscape.LandscapeGuid = guid_library:NewGuid()
        landscape.OriginalLandscapeGuid = landscape.LandscapeGuid
        landscape.ComponentSizeQuads, landscape.SubsectionSizeQuads = 63,63
        landscape.NumSubsections = 1
        landscape.LandscapeMaterial = parent
        landscape.bEnableNanite = false
        landscape.bDisableRuntimeGrassMapGeneration = true
        landscape.MaxLODLevel = 0
        landscape.RootComponent:SetMobility(2)
        landscape:SetActorScale3D(transform.Scale3D)
        landscape.RootComponent:SetMobility(0)
        local components = {}
        for y=0,31 do for x=0,31 do
            local relative = { Rotation={X=0,Y=0,Z=0,W=1},
                Translation={X=x*63,Y=y*63,Z=0},Scale3D={X=1,Y=1,Z=1} }
            local component = landscape:AddComponentByClass(
                StaticFindObject(LANDSCAPE_COMPONENT_CLASS), true, relative, true)
            assert(valid(component), 'could not construct Landscape component')
            component.ComponentSizeQuads, component.SubsectionSizeQuads = 63,63
            component.NumSubsections = 1
            component.SectionBaseX, component.SectionBaseY = x*63,y*63
            component.HeightmapTexture = atlases[math.floor(y/8)*4+math.floor(x/8)+1]
            component.MapBuildDataId = guid_library:NewGuid()
            component.ForcedLOD = 0
            component.CollisionMipLevel = 0
            local material = materials:CreateDynamicMaterialInstance(world,parent,FName('SkiEOTerrain'),0)
            assert(valid(material), 'could not construct terrain material')
            material:SetTextureParameterValue(FName('Heightmap'),component.HeightmapTexture)
            assert(component.MaterialInstances:GetArrayNum() == 1, 'unexpected fresh material topology')
            component.MaterialInstances[1] = material
            initialize_array(component,4,{0,0,0,0,0,0,0})
            component.SkiEOHeightBiasXBits = double_to_bits(1/512)
            component.SkiEOHeightBiasYBits = double_to_bits(1/512)
            component.SkiEOHeightBiasZBits = double_to_bits((x%8)*64/512)
            component.SkiEOHeightBiasWBits = double_to_bits((y%8)*64/512)
            local minimum,maximum = string.unpack('<I2I2',data.bounds,(y*32+x)*4+1)
            component.SkiEOCachedMinXBits,component.SkiEOCachedMinYBits = double_to_bits(0),double_to_bits(0)
            component.SkiEOCachedMinZBits = double_to_bits((minimum-32768)/128)
            component.SkiEOCachedMaxXBits,component.SkiEOCachedMaxYBits = double_to_bits(63),double_to_bits(63)
            component.SkiEOCachedMaxZBits = double_to_bits((maximum-32768)/128)
            component.SkiEOCachedBoxValid = 1
            -- Query bounds are needed by the native cache bootstrap.
            -- Physical collision is built later from the same source.
            component:SetCollisionEnabled(1)
            assert(component:K2_AttachToComponent(landscape.RootComponent,FName(''),1,1,1,false),
                'Landscape component attachment was rejected')
            component:K2_SetRelativeTransform(relative,false,{},true)
            components[#components+1] = component
        end end
        initialize_array(landscape,1,components)
        for index,component in ipairs(components) do
            local x,y = (index-1)%32, math.floor((index-1)/32)
            local relative = {Rotation={X=0,Y=0,Z=0,W=1},Translation={X=x*63,Y=y*63,Z=0},Scale3D={X=1,Y=1,Z=1}}
            landscape:FinishAddComponent(component,true,relative)
        end
        landscape = gameplay:FinishSpawningActor(landscape, transform,0)
        landscape:SetActorEnableCollision(true)
        landscape:SetActorHiddenInGame(false)
        state.native_landscape = true
        state.independent_world = true
        source.native_landscape = true
        source.independent_world = true
        NativeTerrain.landscape = landscape
        NativeTerrain.landscape_textures = atlases
        return {landscape=landscape,height_texture=texture}
    end)
    NativeTerrain.preparing_world = nil
    assert(ok,result)
    return result
end

function NativeTerrain.install()
    return register_properties()
end

function NativeTerrain.populate(
    state, done, progress, is_current, attempt, stability, retry_count)
    state = state.native_encoding or state
    local installed, install_error = register_properties()
    if not installed then done(false, install_error) return end
    if is_current and not is_current() then return end

    local world = UEHelpers.GetWorld()
    local cache = current_cache(world)
    attempt = attempt or 1
    retry_count = retry_count or 0
    -- The subsystem initially allocates and fills its arrays asynchronously.
    -- Writing while that native task is still running succeeds briefly, then
    -- gets overwritten by the native initialization result. Wait until dimensions and
    -- representative samples remain unchanged before replacing the cache.
    if not cache_is_ready(cache) then
        if attempt < 80 then
            if progress then progress("Waiting for native terrain cache", 0.05) end
            schedule_populate(100, state, done, progress, is_current,
                attempt + 1, stability, retry_count)
        else
            done(false, "native terrain cache did not initialize")
        end
        return
    end

    local samples = cache.SkiEOHeightSamples
    local width, height = cache.SkiEOGridWidth, cache.SkiEOGridHeight
    local count = samples:GetArrayNum()
    -- The subsystem fills this array asynchronously after the world becomes
    -- visible. Writing as soon as Num() reaches 2017² races that final pass,
    -- which restores the initial cache pixels. Require fifteen seconds of unchanged
    -- sentinels before replacing the cache; this also covers the delayed
    -- worker completion observed on the supported game build.
    local fingerprint = table.concat({
        tostring(cache.SkiEOOriginZ), tostring(cache.SkiEOMaximumHeight),
        tostring(cache.SkiEOSpacingX), tostring(cache.SkiEOSpacingY),
        tostring(samples[1]), tostring(samples[math.floor(count / 2) + 1]),
        tostring(samples[count]),
    }, ":")
    if not stability or stability.fingerprint ~= fingerprint then
        stability = { fingerprint = fingerprint, count = 0 }
    else
        stability.count = stability.count + 1
    end
    if stability.count < 60 then
        if progress then progress("Waiting for native terrain initialization", 0.05) end
        schedule_populate(250, state, done, progress, is_current,
            attempt + 1, stability, retry_count)
        return
    end

    local started = os.clock()
    local origin_x_bits, origin_y_bits =
        double_to_bits(state.origin_x), double_to_bits(state.origin_y)
    local maximum_x_bits = double_to_bits(
        state.origin_x + (state.width - 1) * state.spacing_cm)
    local maximum_y_bits = double_to_bits(
        state.origin_y + (state.height - 1) * state.spacing_cm)
    local origin_z, maximum_height, vertical_scale = cache_height_limits(state)
    local spacing_x = (state.width - 1) * state.spacing_cm / (width - 1)
    local spacing_y = (state.height - 1) * state.spacing_cm / (height - 1)
    local sentinel_indices = {
        1, width, math.floor(count / 2) + 1, count - width + 1, count,
    }
    local sentinel_values = {}
    for _, index in ipairs(sentinel_indices) do
        local zero_based = index - 1
        local row = math.floor(zero_based / width)
        sentinel_values[index] = resampled_raw(
            state, zero_based - row * width, row, width, height)
    end

    if progress then progress("Reconstructing native terrain cache", 0.08) end
    local copied, copy_message, texture_path = copy_samples_native(
        state, cache, samples, width, height, spacing_x, state.height_scale_cm,
        state.origin_x + (state.width - 1) * state.spacing_cm,
        state.origin_y + (state.height - 1) * state.spacing_cm,
        origin_z, maximum_height, spacing_x, spacing_y)
    if not copied then
        done(false, copy_message)
        return
    end
    local ok, message = pcall(function()
        cache.SkiEOHeightMin = 0.0
        cache.SkiEOHeightRange = 1.0
        cache.SkiEOOriginXBits = origin_x_bits
        cache.SkiEOOriginYBits = origin_y_bits
        cache.SkiEOMaximumXBits = maximum_x_bits
        cache.SkiEOMaximumYBits = maximum_y_bits
        cache.SkiEOOriginZ = origin_z
        cache.SkiEOMaximumHeight = maximum_height
        cache.SkiEOSpacingX = spacing_x
        cache.SkiEOSpacingY = spacing_y
    end)
    if not ok then
        done(false, "native terrain reconstruction failed: " .. tostring(message))
        return
    end
    local texture_ok, texture_result, rendering, context = install_height_texture(
        texture_path, width, height)
    if not texture_ok then
        done(false, texture_result)
        return
    end
    if progress then progress("Reconstructing terrain slope and snow maps", 0.12) end
    local derived_ok, derived_result = install_derived_textures(
        cache, rendering, context, width, height)
    if not derived_ok then
        done(false, derived_result)
        return
    end
    local landscape_ok, landscape_result = finish_landscape(state)
    if not landscape_ok then
        done(false, landscape_result)
        return
    end
    NativeTerrain.render_wait = RenderMapping.install(function()
        return install_render_mapping(state, cache)
    end, function(mapping_ok, mapping_result)
        if not mapping_ok then
            done(false, mapping_result)
            return
        end

        if progress then progress("Validating native terrain cache", 0.16) end
        NativeTerrain.validation_callback = function()
            NativeTerrain.validation_game_callback = function()
                NativeTerrain.validation_handle = nil
                NativeTerrain.validation_callback = nil
                if is_current and not is_current() then return end
                local stable = valid(cache)
                    and cache.SkiEOOriginXBits == origin_x_bits
                    and cache.SkiEOOriginYBits == origin_y_bits
                    and cache.SkiEOMaximumXBits == maximum_x_bits
                    and cache.SkiEOMaximumYBits == maximum_y_bits
                    and float32_matches(cache.SkiEOOriginZ,origin_z)
                    and float32_matches(cache.SkiEOMaximumHeight,maximum_height)
                    and float32_matches(cache.SkiEOSpacingX,spacing_x)
                    and float32_matches(cache.SkiEOSpacingY,spacing_y)
                if stable then
                    for _, index in ipairs(sentinel_indices) do
                        if samples[index] ~= sentinel_values[index] then
                            stable = false
                            break
                        end
                    end
                end
                if not stable then
                    if retry_count < 2 then
                        NativeTerrain.populate(
                            state, done, progress, is_current, 1, nil,
                            retry_count + 1)
                    else
                        done(false, "native terrain cache changed after source initialization")
                    end
                    return
                end
                NativeTerrain.cache = cache
                state.native_cache = {
                    width = width,
                    height = height,
                    spacing_x = spacing_x,
                    spacing_y = spacing_y,
                    origin_z = origin_z,
                    vertical_scale = vertical_scale,
                    maximum_height = maximum_height,
                    height_texture = texture_result,
                    derived_textures = derived_result,
                    landscape = landscape_result,
                    render_mapping_status = mapping_result,
                    helper_status = copy_message,
                    elapsed_seconds = os.clock() - started,
                }
                if progress then progress("Native terrain cache ready", 0.18) end
                done(true, state.native_cache)
                NativeTerrain.validation_game_callback = nil
            end
            ExecuteInGameThread(NativeTerrain.validation_game_callback)
        end
        if type(ExecuteInGameThreadWithDelay) == 'function' then
            NativeTerrain.validation_handle = ExecuteInGameThreadWithDelay(
                2000, NativeTerrain.validation_callback)
        else
            NativeTerrain.validation_handle = ExecuteWithDelay(
                2000, NativeTerrain.validation_callback)
        end
    end, is_current, progress)
end

function NativeTerrain.reset()
    if NativeTerrain.render_wait then NativeTerrain.render_wait:cancel() end
    NativeTerrain.render_wait = nil
    if type(CancelDelayedAction) == "function" then
        if NativeTerrain.pending_handle then
            pcall(CancelDelayedAction, NativeTerrain.pending_handle)
        end
        if NativeTerrain.validation_handle then
            pcall(CancelDelayedAction, NativeTerrain.validation_handle)
        end
    end
    NativeTerrain.pending_handle = nil
    NativeTerrain.pending_callback = nil
    NativeTerrain.game_callback = nil
    NativeTerrain.validation_handle = nil
    NativeTerrain.validation_callback = nil
    NativeTerrain.validation_game_callback = nil
    NativeTerrain.cache = nil
    NativeTerrain.height_texture = nil
    NativeTerrain.previous_snow_height_texture = nil
    NativeTerrain.landscape = nil
    NativeTerrain.landscape_textures = {}
    NativeTerrain.landscape_materials = {}
    NativeTerrain.derived_textures = {}
end

-- Exported for deterministic unit tests of row order and resampling.
NativeTerrain.raw_at = raw_at
NativeTerrain.resampled_raw = resampled_raw
NativeTerrain.cache_height_limits = cache_height_limits
NativeTerrain.float32_matches = float32_matches

return NativeTerrain
