package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
package.preload.UEHelpers = function() return {} end

local json = require("json")
local decoded = json.decode('{"name":"Veymont \\u26f7","values":[true,false,null,-1.25e2]}')
assert(decoded.name == "Veymont ⛷")
assert(decoded.values[1] == true)
assert(decoded.values[2] == false)
assert(tostring(decoded.values[3]) == "null")
assert(decoded.values[4] == -125)
assert(not pcall(json.decode, "1.e2"))

local catalog = require("catalog")
local map, load_error = catalog.load("mod/SkiEO-Veymont/custom-map.json")
assert(map, load_error)
assert(map.id == "community.veymont")
assert(map.__script_path:match("Scripts/main.lua$"))
assert(not catalog.is_safe_relative_path("../escape.lua"))
local discovered, discovery_errors = catalog.discover({
    first = { __files = {{
        __name = "custom-map.json",
        __absolute_path = "mod/SkiEO-Veymont/custom-map.json",
    }}},
    duplicate = { __files = {{
        __name = "custom-map.json",
        __absolute_path = "mod/SkiEO-Veymont/custom-map.json",
    }}},
})
assert(#discovered == 1 and #discovery_errors == 1)

local Heightmap = require("heightmap")
local function r16le(values)
    local bytes = {}
    for _, value in ipairs(values) do
        bytes[#bytes + 1] = string.char(value % 256, math.floor(value / 256))
    end
    return table.concat(bytes)
end
local heightmap_source = r16le({ 0, 100, 200, 300 })
local heightmap = Heightmap.load({
    terrain = {
        size_meters = { 10, 10 },
        origin_centimeters = { -500, -500, 100 },
        source = {
            file = "Terrain/test.r16", format = "r16le", vertices = { 2, 2 },
            spacing_meters = 10, row_order = "north_to_south",
            height_scale_meters = 0.5, height_offset_meters = 10,
        },
    },
    __read = function() return heightmap_source end,
})
assert(Heightmap.height_at(heightmap, -500, -500) == 1100)
assert(Heightmap.height_at(heightmap, 500, 500) == 16100)
assert(Heightmap.height_at(heightmap, 0, 0) == 8600)
assert(Heightmap.height_at(heightmap, 501, 0) == nil)

local NativeTerrain = require("native_terrain")
assert(NativeTerrain.raw_at(heightmap, 0, 0) == 0)
assert(NativeTerrain.raw_at(heightmap, 1, 1) == 300)
assert(NativeTerrain.resampled_raw(heightmap, 1, 1, 3, 3) == 150)
local native_minimum, native_maximum, native_amplitude =
    NativeTerrain.cache_height_limits(heightmap)
assert(native_minimum == 1100)
assert(native_amplitude == 3276800)
assert(native_maximum == 3277900)
heightmap.row_order = "south_to_north"
assert(NativeTerrain.raw_at(heightmap, 0, 0) == 200)
assert(NativeTerrain.raw_at(heightmap, 1, 1) == 100)
heightmap.row_order = "north_to_south"

local Terrain = require("terrain")
heightmap.runtime.placeable_below_ground_tolerance_centimeters = 5
heightmap.runtime.placeable_clearance_centimeters = 20
Terrain.active = heightmap
local terrain_world = {
    IsValid = function() return true end,
    GetAddress = function() return 1 end,
}
local function get_world() return terrain_world end
Terrain.actor = { IsValid = function() return true end, GetWorld = get_world }
local building_location = { X = 0, Y = 0, Z = 1000 }
local building_root = {
    Mobility = 0,
    IsValid = function() return true end,
    SetMobility = function(self, mobility) self.Mobility = mobility end,
}
local building = {
    GetWorld = get_world,
    RootComponent = building_root,
    IsValid = function() return true end,
    IsA = function(_, class_name)
        return class_name == "/Script/SkiResortSimulator.BuildingActor"
    end,
    K2_GetActorLocation = function() return building_location end,
    K2_SetActorLocation = function(_, location)
        if building_root.Mobility == 2 then building_location = location end
        return true
    end,
}
local aligned, delta, ground_z, aligned_delta = Terrain.align_building(building)
assert(aligned and delta == -7600 and ground_z == 8600 and aligned_delta == 20)
assert(building_location.Z == 8620)
assert(building_root.Mobility == 0)
local aligned_again, final_delta = Terrain.align_building(building)
assert(not aligned_again and final_delta == 20)
building_location.Z = 10000
assert(Terrain.align_building(building)) -- template-relative overshoot
assert(building_location.Z == 8620)

-- A small decoration must rest on the rendered surface, even where mesh
-- decimation differs from the simulation height, above the snow shell offset.
local original_surface = Terrain.surface_height_at
Terrain.surface_height_at = function() return 8725 end
building.GetClass = function() return {GetFullName=function() return 'BlueprintGeneratedClass /Game/Blueprints/Decorations/BP_ParkBench.BP_ParkBench_C' end} end
building.TerrainSnapBufferCm = 10
assert(Terrain.align_building(building))
assert(building_location.Z == 8765 and building_root.Mobility == 0)
assert(not Terrain.align_building(building))
Terrain.surface_height_at = original_surface
building.GetClass = nil
assert(Terrain.align_building(building) and building_location.Z == 8620)

-- Lifts keep world-space terminal/tower data and absolute mesh components;
-- moving just their actor cannot correct native Landscape-derived heights.
local function unreal_array(values)
    values.ForEach = function(self, callback)
        for index, value in ipairs(self) do
            callback(index, { get = function() return value end })
        end
    end
    return values
end
local tower_mesh = {
    Mobility = 0,
    IsValid = function() return true end,
    SetMobility = building_root.SetMobility,
    location = { X = 0, Y = 0, Z = 1500 },
    K2_GetComponentLocation = function(self) return self.location end,
    K2_SetWorldLocation = function(self, location)
        assert(self.Mobility == 2)
        self.location = location
    end,
}
local lift = {
    GetWorld = get_world,
    IsValid = function() return true end,
    IsA = function(_, name) return name == "/Script/SkiResortSimulator.LiftActor" end,
    GetAddress = function() return 123 end,
    GetFullName = function() return "TestLift" end,
    Waypoints = unreal_array({
        { position = { X = 0, Y = 0, Z = 1000 } },
        { position = { X = 500, Y = 500, Z = 17000 } },
    }),
    Towers = unreal_array({
        { BasePosition = { X = 0, Y = 0, Z = 1000 }, Height = 1200 },
    }),
    TowerMeshComponents = { tower_mesh },
    terminal_update_count = 0,
    UpdateTerminalPositions = function(self)
        self.terminal_update_count = self.terminal_update_count + 1
        assert(not Terrain.align_lift(self)) -- recursive native hook is guarded
    end,
    UpdateCableSpline = function(self)
        assert(self.Waypoints[1].position.Z == 8600)
        assert(self.Waypoints[2].position.Z == 16100)
        assert(self.Towers[1].BasePosition.Z == 8600)
    end,
    RebuildCableMeshes = function() end,
    RebuildChairMeshes = function() end,
}
assert(Terrain.align_lift(lift))
assert(lift.terminal_update_count == 1)
assert(lift.Waypoints[2].position.Z == 16100) -- template-relative overshoot removed
assert(lift.Towers[1].Height == 1200)
assert(tower_mesh.location.Z == 9100 and tower_mesh.Mobility == 0)
lift.Waypoints[1].position.Z = 1000
assert(Terrain.align_lift_waypoints(lift) == 1)
assert(lift.Waypoints[1].position.Z == 8600)
assert(lift.terminal_update_count == 2)
assert(not Terrain.align_lift(lift)) -- no second offset on repeated hooks
local custom_actor = Terrain.actor
Terrain.actor = nil -- terrain was destroyed by travel to a classic map
building_location.Z = 1000
assert(not Terrain.align_building(building))
assert(not Terrain.align_lift(lift))
Terrain.actor = custom_actor
Terrain.active = nil
assert(not Terrain.align_lift(lift)) -- no effect on classic maps

-- Real UE4SS native post-hook ABI includes the return value before all
-- function arguments, including WorldContextObject for these static helpers.
local hooks = {}
RegisterHook = function(path, _, post) hooks[path] = post end
local helpers = require("UEHelpers")
helpers.GetWorld = get_world
local previous_find=StaticFindObject
StaticFindObject=function(path)
    local parameters={WorldContextObject='ObjectProperty',ReturnValue='FloatProperty'}
    if path:find('GetGroundHeightAtLocation',1,true) then parameters.X='FloatProperty';parameters.Y='FloatProperty'
    else parameters.Location='StructProperty' end
    local names=parameters.X and {'WorldContextObject','X','Y','ReturnValue'} or {'WorldContextObject','Location','ReturnValue'}
    local fn=dofile('tests/support/reflection.lua').func(parameters)
    local original=fn.ForEachProperty
    fn.ForEachProperty=function(_,callback)
        local by_name={};original(fn,function(p)by_name[p:GetFName():ToString()]=p end)
        for _,name in ipairs(names) do callback(by_name[name]) end
    end
    return fn
end
Terrain.install_height_hooks()
StaticFindObject=previous_find
local function parameter(value) return { get = function() return value end } end
local ground_hook = hooks["/Script/SkiResortSimulator.SkiResortFunctionLibrary:GetGroundHeightAtLocation"]
local height_hook = hooks["/Script/SkiResortSimulator.TerrainUtils:GetHeightAtLocation"]
Terrain.active = heightmap
assert(ground_hook(parameter(building), parameter(1000), parameter(terrain_world),
    parameter(0), parameter(0)) == 8600)
assert(height_hook(parameter(building), parameter(1000), parameter(terrain_world),
    parameter({ X = 0, Y = 0 })) == 8600)
Terrain.actor = nil
assert(ground_hook(parameter(building), parameter(1000), parameter(terrain_world),
    parameter(0), parameter(0)) == nil)
Terrain.active = nil
RegisterHook = nil

local scheduled = {}
local actions = {}
local Api = require("api")
local api = Api.new({
    log = function() end,
    defer = function(delay, callback)
        scheduled[#scheduled + 1] = { delay = delay, callback = callback }
    end,
    action = function(name, value)
        actions[#actions + 1] = { name = name, value = value }
        return true
    end,
}, map)
local forest_bytes = api:read_asset("Vegetation/forest.skxy")
assert(#forest_bytes == 12 + 383500 * 8)
assert(not pcall(function() api:read_asset("../custom-map.json") end))

local Vegetation = require("vegetation")
assert(Vegetation.parse_skxy(forest_bytes) == 383500)
assert(not pcall(function() Vegetation.parse_skxy("SKXY") end))

local ready = false
api:on("map.ready", function(event) ready = event.map.id == map.id end)
api:_emit("map.ready", { map = { id = map.id } })
assert(ready)
assert(api.game:set_time_rate(5))
assert(actions[1].name == "set_time_rate" and actions[1].value == 5)
local timer_fired = false
api:after(25, function() timer_fired = true end)
assert(scheduled[1].delay == 25)
scheduled[1].callback()
assert(timer_fired)

local loading_results = {}
local loading_progress = {}
local loading_host = {
    log = function() end,
    loading_finished = function(_, success, message)
        loading_results[#loading_results + 1] = { success, message }
    end,
    loading_progress = function(_,stage,fraction)
        loading_progress[#loading_progress+1]={stage,fraction}
    end,
}
local loading_api = Api.new(loading_host, map)
loading_api:loading_progress('forest',0.7)
assert(loading_progress[1][1]=='forest' and loading_progress[1][2]==0.7)
assert(not pcall(function() loading_api:loading_progress('forest',0/0) end))
assert(not pcall(function() loading_api:loading_progress('forest',2) end))
local first_task = loading_api:hold_loading()
local second_task = loading_api:hold_loading()
loading_api:_terrain_ready()
assert(#loading_results == 0) -- terrain alone does not expose an incomplete station
first_task(); first_task()
assert(#loading_results == 0) -- task completion is idempotent
second_task()
assert(#loading_results == 1 and loading_results[1][1])
loading_api:loading_progress('old callback',0.8)
assert(#loading_progress==1,'completed loading still reported progress')
assert(not pcall(function() loading_api:hold_loading() end))
local stopped_api = Api.new(loading_host, map)
local stale_task = stopped_api:hold_loading()
stopped_api:_terrain_ready()
stopped_api:_stop()
stale_task()
assert(#loading_results == 1) -- old map callbacks cannot dismiss a new screen
local failed_api = Api.new(loading_host, map)
local failed_task = failed_api:hold_loading()
failed_task("station unavailable")
failed_api:_terrain_ready()
assert(#loading_results == 2 and not loading_results[2][1]
    and loading_results[2][2] == "station unavailable")
local empty_api = Api.new(loading_host, map)
empty_api:_terrain_ready()
assert(#loading_results == 3 and loading_results[3][1])
local throwing_api = Api.new(loading_host, map)
throwing_api:on("map.ready", function() error("builder failure") end)
throwing_api:_emit("map.ready", {})
throwing_api:_terrain_ready()
assert(#loading_results == 4 and not loading_results[4][1])

-- Veymont must be loadable as a map-owned runtime module without registering
-- its legacy F8/console entry points in the host mod's Lua state.
package.path = "mod/SkiEO-Veymont/Scripts/?.lua;" .. package.path
local trusted_environment = setmetatable({
    SKIEO_CUSTOM_MAP_RUNTIME = true,
}, { __index = _G })
trusted_environment._G = trusted_environment
local veymont_chunk, veymont_load_error = loadfile(
    "mod/SkiEO-Veymont/Scripts/main.lua", "t", trusted_environment)
assert(veymont_chunk, veymont_load_error)
local veymont_runtime = veymont_chunk()
assert(type(veymont_runtime) == "table" and type(veymont_runtime.on_event) == "function")

print("Lua custom-map modules: OK")
