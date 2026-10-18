local UEHelpers = require("UEHelpers")
local Api = require("api")
local Objects = require("object_edits")
local SceneObjects = require("scene_objects")
local Catalog = require("catalog")
local Terrain = require("terrain")
local NativeTerrain = require("native_terrain")
-- Resolve loader features before a trusted map prepends its own script path.
-- Old installations can contain stale helper copies beside the map script.
local Vegetation = require("vegetation")
local Loading = require("loading")
local World = require("world")
local Saves = require("saves")
local Workshop = require("workshop")
local Featured = require("featured")
local Repository = require("repository")
local Mods = require("mod_catalog")
local Versions = require("versions")

local Runtime = {
    maps = {},
    errors = {},
    selected_index = nil,
    active_map = nil,
    active_api = nil,
    active_script = nil,
    grounding_token = 0,
    grounding_handle = nil,
    grounding_callback = nil,
    placeable_alignment_callbacks = {},
    placeable_finalize_states = {},
    deferred_callbacks = {},
    game_callbacks = {},
}

local MOD_NAME = "Custom Map"
local PLACEABLE_CLASS = "/Script/SkiResortSimulator.PlaceableActor"
local PLACEMENT_STATE_PROPERTY = "SkiEOPlacementState30C"
local placement_state_property_installed = false

local function log(message)
    print(string.format("[%s] %s\n", MOD_NAME, tostring(message)))
end

local function valid(object)
    return object and object:IsValid()
end

local function find_current(class_name)
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

local function execute_in_game_thread(callback)
    local pending = {}
    Runtime.game_callbacks[pending] = pending
    pending.game = function()
        Runtime.completed_game_callback = pending
        local ok, message = pcall(callback)
        Runtime.game_callbacks[pending] = nil
        if not ok then log("game action failed: " .. tostring(message)) end
    end
    ExecuteInGameThread(pending.game)
    return true
end

local function enum_value(enum_path, requested)
    if type(requested) == "number" then return requested end
    if type(requested) ~= "string" then return nil end
    local enum = StaticFindObject(enum_path)
    if not valid(enum) then return nil end
    local wanted = requested:lower():gsub("[^a-z0-9]", "")
    local result = nil
    enum:ForEachName(function(name, value)
        local candidate = name:ToString():lower():gsub("[^a-z0-9]", "")
        if candidate == wanted or candidate:sub(-#wanted) == wanted then
            result = value
            return true
        end
        return false
    end)
    return result
end

local function perform_action(name, value)
    if name == "set_time_rate" then
        if type(value) ~= "number" or value < 0 or value > 100 then
            error("time rate must be within 0..100", 0)
        end
        return execute_in_game_thread(function()
            local subsystem = find_current("TimeSubsystem")
            assert(valid(subsystem), "TimeSubsystem is unavailable")
            subsystem:SetTimeRate(value)
        end)
    elseif name == "pause_time" then
        if type(value) ~= "boolean" then error("pause_time expects a boolean", 0) end
        return execute_in_game_thread(function()
            local subsystem = find_current("TimeSubsystem")
            assert(valid(subsystem), "TimeSubsystem is unavailable")
            if value then subsystem:PauseTime() else subsystem:ResumeTime() end
        end)
    elseif name == "force_weather" then
        local weather = enum_value("/Script/SkiResortSimulator.EWeatherType", value)
        if weather == nil then error("unknown weather type: " .. tostring(value), 0) end
        return execute_in_game_thread(function()
            local subsystem = find_current("WeatherSubsystem")
            assert(valid(subsystem), "WeatherSubsystem is unavailable")
            subsystem:ForceWeather(weather)
        end)
    elseif name == "release_weather" then
        return execute_in_game_thread(function()
            local subsystem = find_current("WeatherSubsystem")
            assert(valid(subsystem), "WeatherSubsystem is unavailable")
            subsystem:ReleaseForcedWeather()
        end)
    elseif name == "add_funds" then
        if type(value) ~= "number" or value ~= value then
            error("add_funds expects a finite number", 0)
        end
        return execute_in_game_thread(function()
            local subsystem = find_current("EconomySubsystem")
            assert(valid(subsystem), "EconomySubsystem is unavailable")
            -- Revenue category 0 is the neutral/general category in build 25551097.
            subsystem:AddFunds(value, 0)
        end)
    elseif name == "set_resort_status" then
        local status = enum_value(
            "/Script/SkiResortSimulator.EResortOperatingStatus", value)
        if status == nil then error("unknown resort status: " .. tostring(value), 0) end
        return execute_in_game_thread(function()
            local subsystem = find_current("ResortOperationsSubsystem")
            assert(valid(subsystem), "ResortOperationsSubsystem is unavailable")
            subsystem:SetOperatingStatus(status)
        end)
    end
    error("unknown game action: " .. tostring(name), 0)
end

local host = {
    bind_key = function(api, key, callback) return require('map_input').bind(api, key, callback) end,
    entity_action = function(api, name, ...) return require('map_entities')[name](api, ...) end,
    sync_state = function(api) Saves.sync_native(api) end,
    scenario_action = function(api, name, ...) return require('scenario_host').action(api, name, ...) end,
    place_objects = function(api, definitions) return SceneObjects.place(api, definitions) end,
    apply_object_edits = function(api, edits, meshes) return Objects.apply(api, edits, meshes) end,
    log = log,
    defer = function(milliseconds, callback)
        -- ExecuteWithDelay runs on UE4SS's async thread. Map callbacks spawn
        -- actors, load assets and update ISM buffers, so dispatch them to the
        -- game thread. Keep both closures alive until the queued work runs.
        local pending = {}
        Runtime.deferred_callbacks[pending] = pending
        pending.game = function()
            Runtime.completed_deferred_callback = pending
            local ok, message = pcall(callback)
            Runtime.deferred_callbacks[pending] = nil
            if not ok then log("deferred map callback failed: " .. tostring(message)) end
        end
        pending.delay = function()
            ExecuteInGameThread(pending.game)
        end
        if type(ExecuteInGameThreadWithDelay) == "function" then
            ExecuteInGameThreadWithDelay(milliseconds, pending.game)
        else
            ExecuteWithDelay(milliseconds, pending.delay)
        end
    end,
    action = perform_action,
    load_forest_skxy = function(bytes, api, options, done)
        Vegetation.load_skxy(bytes, api, options, done)
    end,
}

-- Share the retained, game-thread dispatcher with loader UI callbacks too.
-- UE4SS stores timer closures weakly; an unretained widget callback can be
-- collected while terrain/forest generation allocates its native arguments.
Runtime.defer = host.defer

local function public_map(map)
    return {
        id = map.id,
        name = map.metadata.name,
        version = map.metadata.version,
        description = map.metadata.description,
    }
end

local function event_payload(extra)
    local payload = { map = public_map(Runtime.active_map),
        restored = Runtime.active_api._restoring or false }
    for key, value in pairs(extra or {}) do payload[key] = value end
    return payload
end

function Runtime.emit(event_name, extra)
    if not Runtime.active_map or not Runtime.active_api then return end
    if event_name == "map.ready" then
        local ok, message = pcall(Objects.export)
        if not ok then log("object defaults export failed: " .. tostring(message)) end
    end
    local payload = event_payload(extra)
    Runtime.active_api:_emit(event_name, payload)
    local script = Runtime.active_script
    if type(script) == "table" and type(script.on_event) == "function" then
        local ok, message = pcall(script.on_event, event_name, payload, Runtime.active_api)
        if not ok then
            log(string.format("[%s] legacy event %s failed: %s",
                Runtime.active_map.id, event_name, tostring(message)))
            if event_name == "map.ready" or event_name == "map.terrain_loaded" then
                Runtime.active_api:_finish_loading(false, tostring(message))
            end
        end
    end
    if event_name == 'map.ready' and Runtime.active_api._loading_success ~= false then
        local ok,message=pcall(function() require('scenario_view').start(Runtime.active_api) end)
        if not ok then Runtime.active_api:_finish_loading(false,tostring(message)) end
    end
end

local function copy_library(library)
    local result = {}
    for key, value in pairs(library) do result[key] = value end
    return result
end

local function sandbox_environment()
    local environment = {
        assert = assert,
        error = error,
        ipairs = ipairs,
        next = next,
        pairs = pairs,
        pcall = pcall,
        select = select,
        tonumber = tonumber,
        tostring = tostring,
        type = type,
        xpcall = xpcall,
        math = copy_library(math),
        string = copy_library(string),
        table = copy_library(table),
        SKIEO_CUSTOM_MAP_RUNTIME = true,
    }
    environment._G = environment
    return environment
end

local function has_permission(map, permission)
    for _, candidate in ipairs((map.script and map.script.permissions) or {}) do
        if candidate == permission then return true end
    end
    return false
end

local function script_directory(path)
    return path:match("^(.*)[/\\][^/\\]+$") or "."
end

local function install_archive_require(map, environment, trusted)
    if not map.__read then return end
    local modules = {}
    local loading = {}
    local entry_directory = map.script.entry:match("^(.*)/[^/]+$")
    local declared={}
    for _,relative in ipairs((map.content and map.content.assets) or {}) do declared[relative]=true end
    environment.require = function(name)
        if type(name) ~= "string" or not name:match("^[A-Za-z0-9_.-]+$")
            or name:find("..", 1, true) then
            error("unsafe map module name: " .. tostring(name), 2)
        end
        if modules[name] ~= nil then return modules[name] end
        if loading[name] then error("circular map module: " .. name, 2) end
        local relative = name:gsub("%.", "/") .. ".lua"
        if entry_directory then relative = entry_directory .. "/" .. relative end
        local source = (trusted or declared[relative]) and map.__read(relative)
        if not source then
            -- Trusted historical maps keep access to host modules such as
            -- UEHelpers. Source files shipped in the archive take priority.
            if trusted or name == 'json' then return require(name) end
            error('map module is unavailable: ' .. name, 2)
        end
        local chunk, message = load(
            source, "@" .. map.__manifest_path .. "/" .. relative,
            "t", environment)
        if not chunk then error(message, 2) end
        loading[name] = true
        local ok, result = pcall(chunk)
        loading[name] = nil
        if not ok then error(result, 2) end
        if result == nil then result = true end
        modules[name] = result
        return result
    end
end

local function load_map_script(map, api)
    if not map.script then return nil end
    local trusted = has_permission(map, "skieo.unrestricted")
    local environment
    if trusted then
        environment = setmetatable({ SKIEO_CUSTOM_MAP_RUNTIME = true }, { __index = _G })
        environment._G = environment
        log(string.format("%s requests unrestricted UE4SS access", map.id))
    else
        environment = sandbox_environment()
    end
    if trusted or (map.script.api or '1.0') ~= '1.0' then install_archive_require(map, environment, trusted) end

    local old_package_path = package.path
    if trusted and map.__script_path then
        local directory = script_directory(map.__script_path)
        local separator = directory:find("\\", 1, true) and "\\" or "/"
        package.path = directory .. separator .. "?.lua;" .. package.path
    end
    local chunk, load_error
    if map.__script_path then
        chunk, load_error = loadfile(map.__script_path, "t", environment)
    else
        local source, read_error = map.__read(map.script.entry)
        if source then
            chunk, load_error = load(
                source, "@" .. map.__manifest_path .. "/" .. map.script.entry,
                "t", environment)
        else
            load_error = read_error
        end
    end
    if not chunk then
        package.path = old_package_path
        error("cannot load map script: " .. tostring(load_error), 0)
    end
    local ok, script = pcall(chunk)
    package.path = old_package_path
    if not ok then error("map script failed during load: " .. tostring(script), 0) end
    if type(script) == "function" then
        local registered, message = pcall(script, api)
        if not registered then error("map script registration failed: " .. tostring(message), 0) end
    elseif type(script) == "table" and type(script.register) == "function" then
        local registered, message = pcall(script.register, api)
        if not registered then error("map script registration failed: " .. tostring(message), 0) end
    elseif script ~= nil and type(script) ~= "table" then
        error("map script must return a registration function or table", 0)
    end
    return script
end

function Runtime.refresh()
    local previous = Runtime.selected()
    local previous_id = previous and (previous.__workshop and previous.__workshop.published_file_id or previous.id)
    -- Inspect manifests and file sizes here. Large terrain/mesh payloads are
    -- decompressed and verified under the loading screen when Play is pressed.
    local maps, errors = Catalog.discover(nil,true)
    local mods, mod_errors = Mods.discover(nil,true)
    Workshop.errors = {}
    local cached_maps, cached_mods = Workshop.local_packages(true)
    local featured_maps, featured_mods = Featured.local_packages(true)
    local function append(entries, cached, unique_ids)
        for _, package in ipairs(cached) do
            local found = false
            for index, existing in ipairs(entries) do
                if existing.__manifest_path == package.__manifest_path
                    or (unique_ids and existing.id == package.id) then
                    -- Discovery and the CLI/Workshop inventory can describe
                    -- the same map through different files. Its logical ID,
                    -- rather than its install path, defines a catalogue row.
                    if Versions.compare(package.metadata.version, existing.metadata.version) > 0 then
                        entries[index] = package
                    elseif existing.__manifest_path == package.__manifest_path then
                        existing.__workshop = package.__workshop or existing.__workshop
                    end
                    found = true; break
                end
            end
            if not found then entries[#entries + 1] = package end
        end
    end
    append(maps, cached_maps, true); append(mods, cached_mods, false)
    append(maps, featured_maps, true); append(mods, featured_mods, false)
    for _, entry in ipairs(mod_errors) do errors[#errors + 1] = entry end
    for _, entry in ipairs(Workshop.errors) do errors[#errors + 1] = entry end
    Runtime.mods = mods
    Runtime.workshop_mods = Workshop.merge(mods, "mod")
    maps = Repository.merge(Featured.merge(Workshop.merge(maps, "map")))
    Runtime.maps = maps
    Runtime.errors = errors
    local browsing = Runtime.browse_items()
    if #browsing > 0 then
        Runtime.selected_index = 1
        if previous_id then
            for index, map in ipairs(browsing) do
                if (map.__workshop and map.__workshop.published_file_id or map.id) == previous_id then
                    Runtime.selected_index = index
                    break
                end
            end
        end
    else
        Runtime.selected_index = nil
    end
    log(string.format("discovered %d custom map(s), %d invalid", #maps, #errors))
    for _, entry in ipairs(errors) do
        log(string.format("ignored %s: %s", entry.path, entry.message))
    end
    return maps, errors
end

function Runtime.refresh_workshop(callback)
    return Featured.refresh(function()
        Workshop.refresh(function()
            Runtime.refresh()
            if callback then execute_in_game_thread(callback) end
        end)
    end)
end

function Runtime.install_map(map, callback, progress)
    local function finished(failure)
        if failure then log(failure) end
        Runtime.refresh()
        if callback then execute_in_game_thread(function() callback(failure) end) end
    end
    if map and map.__featured then return Featured.ensure(map, Runtime.maps, Runtime.mods, finished, progress) end
    if map and (map.__remote or map.__update) then return Repository.install(map, finished, Runtime.mods, progress) end
    if map and not map.__workshop then return Repository.ensure_dependencies(map, Runtime.mods, finished, progress) end
    return Workshop.ensure(map, finished)
end

function Runtime.install_selected(callback)
    return Runtime.install_map(Runtime.selected(), callback)
end

function Runtime.catalog_busy() return Workshop.busy or Featured.busy or Repository.busy end
function Runtime.catalog_message()
    return Repository.busy and Repository.message or Featured.busy and Featured.message or Workshop.busy and Workshop.message
        or Featured.message ~= "" and Featured.message or Workshop.message
end

function Runtime.browse_items()
    return Runtime.browse_kind == "mod" and (Runtime.workshop_mods or {}) or Runtime.maps
end

function Runtime.select(selector)
    local index = tonumber(selector)
    if index and Runtime.maps[index] then
        Runtime.selected_index = index
        return Runtime.maps[index]
    end
    if type(selector) == "string" then
        local wanted = selector:lower()
        for candidate_index, map in ipairs(Runtime.maps) do
            if map.id:lower() == wanted or map.metadata.name:lower() == wanted then
                Runtime.selected_index = candidate_index
                return map
            end
        end
    end
    return nil
end

function Runtime.selected()
    return Runtime.selected_index and Runtime.browse_items()[Runtime.selected_index] or nil
end

local function clear_pending_session()
    local session = FindFirstOf("GameSessionSubsystem")
    if not valid(session) then
        log("GameSessionSubsystem unavailable; opening the independent world directly")
        return
    end
    session.PendingScenario = nil
    session.PendingInitialSave = nil
end

local function world_matches(map)
    return World.matches(map)
end

local function guard_loading_time(map, api)
    api:every(100, function()
        if Runtime.active_api ~= api or api._loading_finished then return false end
        -- Native save restoration can resume the clock after InitGameState.
        -- Keep it paused until terrain/forest construction has also finished.
        World.pause_loading(map)
        return true
    end)
end

local function wait_until_ready(map, api, previous_world, attempt)
    if Runtime.active_api ~= api or api._loading_finished then return end
    local world = UEHelpers.GetWorld()
    if world_matches(map) and world:GetAddress() ~= previous_world then
        if api._restoring then Runtime.emit("map.after_load") end
        Loading.update("Loading terrain data…", 0.04)
        Terrain.load(map, function(loaded, message)
            if Runtime.active_api ~= api or api._loading_finished then return end
            if not loaded then
                log("terrain loading failed for " .. map.id .. ": " .. tostring(message))
                api:_finish_loading(false, tostring(message))
                return
            end
            local initialized, failure = pcall(World.initialize_simulation, map)
            if not initialized then api:_finish_loading(false, tostring(failure)) return end
            Loading.update("Creating resort…", 0.95)
            Runtime.emit("map.terrain_loaded", { restored = api._restoring })
            Runtime.emit("map.ready", { attempts = attempt, restored = api._restoring })
            api:_terrain_ready()
        end, Loading.update, World.state(map))
    elseif attempt < 20 then
        api:after(500, function() wait_until_ready(map, api, previous_world, attempt + 1) end)
    else
        api:_finish_loading(false, "timed out waiting for independent world")
    end
end

local function deactivate_after_world_change(api, reason)
    if Runtime.active_api ~= api then return end
    Runtime.emit("map.unloading")
    Runtime.grounding_token = Runtime.grounding_token + 1
    api:_stop()
    World.cancel()
    Terrain.unload()
    Loading.hide()
    Runtime.active_map = nil
    Runtime.active_api = nil
    Runtime.active_script = nil
    Runtime.placeable_alignment_callbacks = {}
    Runtime.placeable_finalize_states = {}
    log("custom map runtime stopped after world change: " .. reason)
end

local function start_dynamic_grounding(api)
    Runtime.grounding_token = Runtime.grounding_token + 1
    local token = Runtime.grounding_token
    local frame = 0
    local loop_handle = nil
    local function stop_loop()
        if loop_handle and type(CancelDelayedAction) == "function" then
            pcall(CancelDelayedAction, loop_handle)
        end
        if Runtime.grounding_handle == loop_handle then
            Runtime.grounding_handle = nil
            Runtime.grounding_callback = nil
        end
    end
    local function ground_frame()
        if Runtime.grounding_token ~= token or Runtime.active_api ~= api
            or api._loading_finished == false or not Terrain.active then
            stop_loop()
            return true
        end
        if not Terrain.is_active_in_current_world() then
            stop_loop()
            deactivate_after_world_change(api, "source terrain belongs to the previous world")
            return true
        end
        frame = frame + 1
        local ok, message = pcall(Terrain.maintain_dynamic_grounding, frame)
        if not ok then
            log("dynamic terrain grounding failed: " .. tostring(message))
            Runtime.grounding_token = Runtime.grounding_token + 1
            stop_loop()
            return true
        end
        return false
    end
    if type(LoopInGameThreadWithDelay) == "function" then
        -- Retain the Lua closure explicitly as well as the native action
        -- handle. Some UE4SS builds only keep a weak registry reference.
        Runtime.grounding_callback = ground_frame
        loop_handle = LoopInGameThreadWithDelay(16, ground_frame)
        Runtime.grounding_handle = loop_handle
        log("dynamic source-terrain grounding started")
    else
        LoopAsync(16, function()
            if Runtime.grounding_token ~= token then return true end
            ExecuteInGameThread(ground_frame)
            return false
        end)
    end
end


local function start_world_guard(map, api)
    local expected_world = UEHelpers.GetWorld()
    local expected_address = valid(expected_world) and expected_world:GetAddress() or nil
    if not expected_address then return end
    api:every(250, function()
        if Runtime.active_api ~= api then return false end
        local world = UEHelpers.GetWorld()
        if not valid(world) or world:GetAddress() ~= expected_address
            or not world_matches(map) then
            deactivate_after_world_change(api,
                "the active world is no longer " .. World.level)
            return false
        end
        World.update_snow_lighting(map)
        return true
    end)
end

-- Calendar initialization in the stock template can enqueue its previous
-- month's report while the custom loading screen is still covering the
-- world. That report describes the template save, not the source map. Close
-- only reports visible during the short load-finalization window; later
-- reports produced by normal play remain untouched.
local function dismiss_load_time_month_reports(api)
    if Runtime.active_api ~= api then return end
    local dismissed = 0
    for _, widget in ipairs(FindAllOf("MonthReportWidget") or {}) do
        if valid(widget) and widget:IsInViewport() then
            local ok = pcall(function()
                widget:OnContinueClicked()
                if widget:IsInViewport() then widget:RemoveFromParent() end
            end)
            if ok then dismissed = dismissed + 1 end
        end
    end
    if dismissed > 0 then
        log(string.format(
            "dismissed %d template month report(s) during loading", dismissed))
    end
end

host.loading_progress = function(api, stage, fraction)
    if Runtime.active_api == api then Loading.update(stage, fraction) end
end

host.loading_finished = function(api, success, message)
    -- Leave native finalization and any map callback stacks, then verify all
    -- placeables once more before uncovering the playable world.
    api:after(1, function()
        if Runtime.active_api ~= api then return end
        local map = Runtime.active_map
        if success then
            local ok, failure = pcall(function()
                local world = UEHelpers.GetWorld()
                local restored_lifts, restored_buildings = {}, {}
                for _, class in ipairs({ "BuildingActor", "LiftActor" }) do
                    -- FindAllOf also returns destroyed template objects
                    -- until GC; Unreal's world iterator excludes them.
                    local actors = {}
                    UEHelpers.GetGameplayStatics():GetAllActorsOfClass(world,
                        StaticFindObject("/Script/SkiResortSimulator." .. class), actors)
                    for _, entry in ipairs(actors) do
                        local actor = entry:get()
                        if valid(actor) and not actor:IsActorBeingDestroyed() then
                            Terrain.align_building(actor)
                            Terrain.align_lift(actor)
                            if api._restoring then
                                if class == "LiftActor" then
                                    restored_lifts[#restored_lifts + 1] = actor
                                elseif not actor:GetClass():GetFullName():find("/Blueprints/Decorations/", 1, true) then
                                    restored_buildings[#restored_buildings + 1] = actor
                                end
                            end
                        end
                    end
                end
                if api._restoring and #restored_lifts + #restored_buildings > 0 then
                    -- Native restore registers entrances before the portable
                    -- terrain is ready. Replace those sources at their final
                    -- transforms before rebuilding trails and hub visuals.
                    local registered, detail = NativeTerrain.register_placeable_hubs(
                        restored_lifts, restored_buildings)
                    assert(registered, detail)
                    log("restored resort hub sources: " .. tostring(detail))
                end
                Terrain.align_native_trails()
                Terrain.clear_native_trail_obstacles()
                Terrain.rebuild_trail_visuals()
                Terrain.dismiss_buried_events()
                Terrain.maintain_dynamic_grounding(1)
                -- Native startup restores session bookkeeping after our
                -- InitGameState hook. Set a fresh id after construction,
                -- before play/save UI, and report metadata IO failures.
                if not api._restoring then Saves.start_new(map) end
            end)
            if not ok then success, message = false, tostring(failure) end
        end
        if success then
            World.finish_loading(map)
            if map.terrain.source then
                local attempts=0
                local function refresh_skiability()
                    if Runtime.active_api~=api then return end
                    attempts=attempts+1
                    local ok,message=NativeTerrain.refresh_skiability()
                    if ok then log(message)
                    elseif attempts<20 and message=='snow readback is not ready' then api:after(500,refresh_skiability)
                    else log('skiability refresh unavailable: '..tostring(message)) end
                end
                api:after(500,refresh_skiability)
            end
            start_dynamic_grounding(api)
            start_world_guard(map, api)
            dismiss_load_time_month_reports(api)
            for _, delay in ipairs({ 50, 250, 1000 }) do
                api:after(delay, function()
                    dismiss_load_time_month_reports(api)
                end)
            end
            Loading.hide()
            log(Runtime.active_map.metadata.name .. " is ready (terrain and station)")
        else
            log("map loading failed: " .. tostring(message))
            Runtime.emit("map.load_failed", { message = tostring(message) })
            -- Cancel unfinished station/forest work immediately. A failed
            -- initialization must never uncover an incomplete playable map.
            api:_stop()
            Vegetation.unload()
            Loading.update("Loading failed — see UE4SS.log", 0.0)
            host.defer(5000, function()
                if Runtime.active_api ~= api then return end
                local world = UEHelpers.GetWorldContextObject()
                local gameplay = UEHelpers.GetGameplayStatics()
                local returned, failure = pcall(function()
                    assert(valid(world) and valid(gameplay), "main menu travel is unavailable")
                    gameplay:OpenLevel(world, UEHelpers.FindOrAddFName("/Game/Maps/MainMenu"), true, "")
                end)
                if returned then
                    deactivate_after_world_change(api, "failed map initialization")
                else
                    log("could not return to main menu: " .. tostring(failure))
                end
            end)
        end
    end)
end

local function activate_map(map, restoring)
    local dependencies_ok, dependencies = pcall(Versions.resolve, map, Runtime.mods)
    if not dependencies_ok then log(dependencies) return nil end
    for _, mod in ipairs(dependencies) do
        if mod.runtime == "ue4ss" and not mod.__ue4ss_installed then
            log("required UE4SS mod " .. mod.id .. " is not active; install it with the CLI and restart the game")
            return nil
        end
    end
    if Runtime.active_map then
        Runtime.emit("map.unloading")
        Runtime.active_api:_stop()
    end
    Runtime.grounding_token = Runtime.grounding_token + 1
    Runtime.placeable_alignment_callbacks = {}
    Runtime.placeable_finalize_states = {}
    if Runtime.grounding_handle and type(CancelDelayedAction) == "function" then
        pcall(CancelDelayedAction, Runtime.grounding_handle)
        Runtime.grounding_handle = nil
        Runtime.grounding_callback = nil
    end
    World.cancel()
    Terrain.unload()
    Runtime.active_map = map
    Runtime.active_api = Api.new(host, map)
    Runtime.active_api._restoring = restoring or false
    Runtime.active_api._persistent = Runtime.pending_script_state
    Runtime.pending_script_state = nil
    Runtime.active_script = nil
    local script_ok, script_or_error = pcall(function()
        for _, mod in ipairs(dependencies) do
            if mod.runtime ~= "ue4ss" then
                local scoped = Api.new(host, mod)
                local api = Runtime.active_api
                scoped._session = api
                -- Dependency callbacks, timers and loading holds belong to
                -- the map session; assets and gameplay permissions stay scoped.
                local proxy = {game = scoped.game}
                proxy.log = function(_, message) return scoped:log(message) end
                proxy.read_asset = function(_, path) return scoped:read_asset(path) end
                proxy.load_forest_skxy = function(_, path, options) return scoped:load_forest_skxy(path, options) end
                for _, name in ipairs({'mapmod_options', 'mod_state', 'environment', 'spawn_animated', 'footprint', 'expire_footprints', 'bind_key', 'focus_camera'}) do
                    proxy[name] = function(_, ...) return scoped[name](scoped, ...) end
                end
                for _, name in ipairs({"on", "off", "after", "every", "loading_progress", "hold_loading"}) do
                    proxy[name] = function(_, ...) return api[name](api, ...) end
                end
                proxy.on_frame=function(_,callback)
                    assert(scoped._gameplay_allowed,"script permission 'gameplay' is required for frame loops")
                    return api:every(16,callback,true)
                end
                load_map_script(mod, proxy)
            end
        end
        return load_map_script(map, Runtime.active_api)
    end)
    if not script_ok then
        log(string.format("[%s] %s", map.id, tostring(script_or_error)))
        Runtime.active_api:_stop()
        Runtime.active_map = nil
        Runtime.active_api = nil
        return nil
    end
    Runtime.active_script = script_or_error
    local api = Runtime.active_api
    api._restoring = restoring or false
    return api
end

local function verify_installed_map(map)
    if map.__inventory_only then
        Loading.update("Verifying installed map…",0.035)
        local verified,failure=Catalog.load(map.__manifest_path)
        if not verified then log(failure);return nil,tostring(failure) end
        if verified.id~=map.id or verified.metadata.version~=map.metadata.version then
            return nil,"Local map changed; refresh the catalogue"
        end
        verified.__featured,verified.__workshop,verified.__update=map.__featured,map.__workshop,map.__update
        verified.__web=map.__web
        map=verified
    end
    local resolved,dependencies=pcall(Versions.resolve,map,Runtime.mods)
    if not resolved then log(dependencies);return nil,tostring(dependencies) end
    for _,mod in ipairs(dependencies) do
        if mod.__inventory_only then
            Loading.update("Verifying "..mod.metadata.name.."…",0.035)
            local verified,failure=Mods.load(mod.__manifest_path)
            if not verified then log(failure);return nil,tostring(failure) end
            if verified.id~=mod.id or verified.metadata.version~=mod.metadata.version then
                return nil,"Local mod changed; refresh the catalogue"
            end
            verified.__workshop=mod.__workshop
            for index,entry in ipairs(Runtime.mods) do if entry==mod then Runtime.mods[index]=verified end end
        end
    end
    if map.terrain and map.terrain.source then
        local ready,detail=NativeTerrain.check_compatibility()
        if not ready then log(detail);return nil,tostring(detail) end
    end
    return map
end

function Runtime.restore(saved)
    Loading.show(saved.map)
    local map,failure=verify_installed_map(saved.map)
    if not map then
        -- Reuse the normal failure lifecycle: keep the world covered, then
        -- return to the menu without executing scripts from unverified files.
        Runtime.active_map=saved.map
        Runtime.active_api=Api.new(host,saved.map)
        Runtime.active_api:_finish_loading(false,failure)
        return
    end
    Runtime.pending_script_state = saved.script_state
    local api = assert(activate_map(map,true), 'could not activate saved custom map')
    Loading.show(map)
    Runtime.emit("map.before_load", {restored=true})
    World.prepare(map, log, function(failure) api:_finish_loading(false,failure) end, true)
    guard_loading_time(map, api)
    api:after(100, function() wait_until_ready(map,api,nil,1) end)
    Loading.watch_timeout(api, function() return Runtime.active_api == api end)
    log("restoring independent world for " .. map.id .. (saved.legacy and " (legacy save)" or ""))
end

function Runtime.start(map)
    map = map or Runtime.selected()
    if not map then log("no custom map is selected") return false end
    if map.__unavailable then log("wait for the map and required mods to finish downloading") return false end
    if map.format and map.format.name == "skieo-mod" then log("select a map to play") return false end
    local verified,failure=verify_installed_map(map)
    if not verified then return false,failure end
    map=verified
    local api = activate_map(map,false)
    if not api then return false end

    execute_in_game_thread(function()
        if Runtime.active_api ~= api then return end
        local ok, message = pcall(function()
            Loading.show(map)
            Runtime.emit("map.before_load")
            clear_pending_session()
            Saves.prepare_new(map)
            World.prepare(map, log, function(failure)
                api:_finish_loading(false, failure)
            end)
            guard_loading_time(map, api)
            local world = UEHelpers.GetWorldContextObject()
            assert(valid(world), "no world context is available")
            local previous_world = UEHelpers.GetWorld():GetAddress()
            local gameplay_statics = UEHelpers.GetGameplayStatics()
            assert(valid(gameplay_statics), "GameplayStatics is unavailable")
            -- Allow the loading widget to render before synchronous travel.
            api:after(100, function()
                execute_in_game_thread(function()
                    if Runtime.active_api ~= api then return end
                    local opened, failure = pcall(function()
                        gameplay_statics:OpenLevel(
                            world, UEHelpers.FindOrAddFName(World.level), true, "game=/Game/Core/BP_SkiResortGameMode.BP_SkiResortGameMode_C")
                        Runtime.emit("map.after_load")
                        log("loading independent world " .. World.level)
                    end)
                    if not opened then api:_finish_loading(false, tostring(failure)) return end
                    api:after(100, function() wait_until_ready(map, api, previous_world, 1) end)
                end)
            end)
            Loading.watch_timeout(api, function() return Runtime.active_api == api end)
        end)
        if not ok then
            log("could not start " .. map.id .. ": " .. tostring(message))
            Loading.hide()
            if Runtime.active_map == map then
                Runtime.active_api:_stop()
                Runtime.active_map = nil
                Runtime.active_api = nil
                Runtime.active_script = nil
            end
        end
    end)
    return true
end

-- One loading screen owns acquisition and world initialization. Installed maps
-- with their required mods take the local path, even during a catalogue refresh.
function Runtime.play(map, callback, update)
    map = map or Runtime.selected()
    if not map or map.format and map.format.name == "skieo-mod" then return false end
    if Runtime.pending_play or Runtime.active_api and not Runtime.active_api._loading_finished then return false end
    local pending = {map=map}
    Runtime.pending_play = pending
    execute_in_game_thread(function()
        Loading.show(map)
        local function finish(failure, installed)
            if Runtime.pending_play ~= pending then return end
            if not failure then
                local started,reason=Runtime.start(installed or map)
                if not started then failure=reason or "Could not start the custom map" end
            end
            Runtime.pending_play = nil
            if failure then Loading.hide(); log(failure) end
            if callback then callback(failure) end
        end
        local function prepare()
            local ok,failure = pcall(function()
                if not update and Runtime.dependency_status(map) then finish(); return end
                local accepted = Runtime.install_map(map,function(error_message)
                    if error_message then finish(tostring(error_message)); return end
                    local installed
                    for _,entry in ipairs(Runtime.maps) do
                        if entry.id == map.id or map.__workshop and entry.__workshop
                            and entry.__workshop.published_file_id == map.__workshop.published_file_id then
                            installed=entry; break
                        end
                    end
                    local ready,reason = Runtime.dependency_status(installed)
                    finish(not ready and reason or nil,installed)
                end,function(stage,fraction)
                    if Runtime.pending_play == pending then Loading.update(stage,0.035*(fraction or 0)) end
                end)
                if not accepted then finish("Download unavailable; try again after the current operation") end
            end)
            if not ok then finish(tostring(failure)) end
        end
        Loading.update("Preparing map…",0.0)
        -- Give the viewport a frame before inspecting archives or downloading.
        host.defer(100,prepare)
    end)
    return true
end

local function object_summary(context)
    local object = context and context:get()
    if not valid(object) then return {} end
    local full_name = object:GetFullName()
    return {
        object_name = full_name:match("([^ .]+)$") or full_name,
        class_name = full_name:match("^(%S+)") or "UObject",
    }
end

local function install_post_hook(path, callback)
    local ok, message = require('compatibility').hook('event.post.'..path,path,'post',callback)
    if not ok then log("event hook unavailable " .. path .. ": " .. tostring(message)) end
end

local function install_pre_hook(path, callback)
    local ok, message = require('compatibility').hook('event.pre.'..path,path,'pre',callback)
    if not ok then log("event hook unavailable " .. path .. ": " .. tostring(message)) end
end

local function install_placement_state_property()
    if placement_state_property_installed then return true end
    local compatible,detail=require('compatibility').check('placement.private_layout',require('compatibility_contracts').placement)
    if not compatible then log(detail);return false end
    if type(RegisterCustomProperty) ~= "function"
        or type(PropertyTypes) ~= "table"
        or PropertyTypes.ByteProperty == nil then
        log("private placement guard unavailable; source-terrain finalization cannot be isolated")
        return false
    end
    local ok, message = pcall(RegisterCustomProperty, {
        Name = PLACEMENT_STATE_PROPERTY,
        Type = PropertyTypes.ByteProperty,
        BelongsToClass = PLACEABLE_CLASS,
        OffsetInternal = 0x30C,
    })
    if not ok then
        log("private placement guard unavailable: " .. tostring(message))
        return false
    end
    placement_state_property_installed = true
    return true
end

local function align_finalized_building(actor)
    local aligned, delta, ground_z, final_delta =
        Terrain.align_building(actor)
    if delta then
        local outcome = ""
        if aligned then
            outcome = string.format("; aligned to %.1f cm", final_delta)
        elseif final_delta then
            outcome = string.format("; alignment rejected at %.1f cm", final_delta)
        end
        log(string.format(
            "building ground check: delta=%.1f cm, ground=%.1f cm%s",
            delta, ground_z, outcome))
    end
end

local function defer_finalized_placeable_alignment(actor)
    if not valid(actor) then return end
    -- Initial station construction already grounds placeables before native
    -- registration and performs one complete alignment pass when all loading
    -- holds are released.  Scheduling one Lua callback per actor here can
    -- re-enter UE4SS while a map script is creating the following lift; on
    -- UE4SS 3.0.1 that corrupts the Lua VM after the first/second lift.
    local api = Runtime.active_api
    if api and api._loading_finished == false then return end
    local address = actor:GetAddress()
    if Runtime.placeable_alignment_callbacks[address] then return end
    local terrain_generation = Terrain.generation
    local callback = function()
        Runtime.placeable_alignment_callbacks[address] = nil
        if Terrain.generation ~= terrain_generation or not valid(actor) then
            return
        end
        -- Leave the finalizer's hook stack before changing native geometry.
        Terrain.align_lift(actor)
        align_finalized_building(actor)
    end
    -- UE4SS stores delayed callbacks weakly. Keep this closure (and therefore
    -- the actor wrapper) alive until it has run.
    Runtime.placeable_alignment_callbacks[address] = callback
    host.defer(1, callback)
end

function Runtime.install_event_hooks()
    Saves.install()
    World.restore_handler = Runtime.restore
    World.install()
    Runtime.travel_callback = function()
        if World.pending then return end -- explicit New Game travel
        local ok, saved = pcall(Saves.find_restore, Runtime.maps)
        if Runtime.active_api then
            deactivate_after_world_change(Runtime.active_api, "native level travel")
        end
        World.restore_candidate = ok and saved or nil
        if not ok then log("could not identify saved custom map: " .. tostring(saved)) end
    end
    RegisterLoadMapPreHook(Runtime.travel_callback)
    install_placement_state_property()
    install_post_hook("/Script/Engine.PlayerController:ClientRestart", function()
        -- Replace the travel screen before the first playable world frame.
        local ok, message = pcall(Loading.refresh)
        if not ok then log("loading screen refresh failed: " .. tostring(message)) end
    end)
    install_post_hook(
        "/Script/SkiResortSimulator.CalendarSubsystem:HandleMonthAdvanced",
        function(context)
            local calendar = context:get()
            local month = nil
            pcall(function() month = calendar:GetCurrentMonth() end)
            Runtime.emit("calendar.month_changed", { month = month })
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.CalendarSubsystem:HandleYearAdvanced",
        function(context)
            local calendar = context:get()
            local year = nil
            pcall(function() year = calendar:GetYearNumber() end)
            Runtime.emit("calendar.year_changed", { year = year })
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.LiftActor:Finalize",
        function(context)
            local actor = context:get()
            if not valid(actor) or not Terrain.is_active_in_current_world() then
                return
            end
            -- LiftActor::Finalize applies the template terrain offset to its
            -- world-space waypoints. Undo that mutation immediately: map
            -- scripts call FinalizePlacement next, and that function records
            -- the terminal component transforms in the native hub graph.
            local changed = Terrain.align_lift_waypoints(actor)
            if changed > 0 then
                log(string.format(
                    "lift terminals grounded after geometry finalization: %d terminal(s)",
                    changed))
            end
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.PlaceableActor:FinalizePlacement",
        function(context)
            local actor = context:get()
            if valid(actor) then
                local address = actor:GetAddress()
                local state = Runtime.placeable_finalize_states[address]
                Runtime.placeable_finalize_states[address] = nil
                if state then
                    if state.conforms ~= nil then
                        pcall(function()
                            actor.bConformsToTerrain = state.conforms
                        end)
                    end
                    if state.snap_buffer ~= nil then
                        pcall(function()
                            actor.TerrainSnapBufferCm = state.snap_buffer
                        end)
                    end
                end
            end
            defer_finalized_placeable_alignment(actor)
            Runtime.emit("placeable.built", object_summary(context))
        end)
    install_pre_hook(
        "/Script/Engine.Actor:K2_DestroyActor",
        function(context)
            local actor = context:get()
            if valid(actor) and actor:IsA("/Script/SkiResortSimulator.PlaceableActor") then
                Runtime.emit("placeable.removed", object_summary(context))
            end
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.TrailMapSubsystem:RegisterTrailFromCurve",
        function()
            Runtime.emit("trail.created")
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.TrailMapSubsystem:UnregisterTrail",
        function()
            Runtime.emit("trail.removed")
        end)
    install_pre_hook(
        "/Script/SkiResortSimulator.EventSubsystem:TriggerEvent",
        function(_, event_definition)
            Terrain.align_event_definition(event_definition)
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.TrailVisualizationSubsystem:SetVisualizationEnabled",
        function()
            local generation = Terrain.generation
            host.defer(1, function()
                if Terrain.generation == generation then
                    Terrain.sync_trail_visualization()
                end
            end)
        end)
    install_post_hook(
        "/Script/SkiResortSimulator.AchievementSubsystem:HandleWeatherChanged",
        function()
            local weather = nil
            pcall(function()
                local subsystem = find_current("WeatherSubsystem")
                if valid(subsystem) then weather = subsystem:GetWeatherType() end
            end)
            Runtime.emit("weather.changed", { weather = weather })
        end)
end

Runtime.log = log
Runtime.terrain = Terrain
Runtime.vegetation = Vegetation
Runtime.workshop = Workshop
Runtime.featured = Featured
Runtime.dependency_status = function(map)
    if not map or map.__unavailable then return false, "Map content not installed" end
    if map.__workshop and Workshop.provider then
        local state = Workshop.state(map.__workshop.published_file_id)
        if not state.installed or state.needs_update or state.downloading or state.download_pending then return false, "Wait for the Steam Workshop update to complete" end
    end
    local ok, result = pcall(Versions.resolve, map, Runtime.mods)
    if not ok then return false, tostring(result) end
    for _, mod in ipairs(result) do
        if mod.runtime == "ue4ss" and not mod.__ue4ss_installed then return false, "UE4SS dependency requires installation and restart: " .. mod.id end
    end
    return true
end

return Runtime
