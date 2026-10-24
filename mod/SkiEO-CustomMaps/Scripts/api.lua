local Api = {}
Api.__index = Api

Api.EVENTS = {
    ["map.before_load"] = true,
    ["map.after_load"] = true,
    ["map.ready"] = true,
    ["map.terrain_loaded"] = true,
    ["map.load_failed"] = true,
    ["map.unloading"] = true,
    ["calendar.month_changed"] = true,
    ["calendar.year_changed"] = true,
    ["weather.changed"] = true,
    ["placeable.built"] = true,
    ["placeable.removed"] = true,
    ["trail.created"] = true,
    ["trail.removed"] = true,
}

local function checked_callback(callback, label)
    if type(callback) ~= "function" then
        error(label .. " expects a function", 3)
    end
end

function Api.new(host, map)
    local asset_paths = {}
    for _, relative in ipairs((map.content and map.content.assets) or {}) do
        asset_paths[relative] = true
    end
    local self = setmetatable({
        _host = host,
        _map = map,
        _asset_paths = asset_paths,
        _handlers = {},
        _timer_generation = 0,
        _loading_pending = 0,
        _loading_ready = false,
        _loading_finished = false,
        _loop_handles = {},
        _loop_callbacks = {},
    }, Api)

    local gameplay_allowed = false
    for _, permission in ipairs((map.script and map.script.permissions) or {}) do
        gameplay_allowed = gameplay_allowed or permission == "gameplay"
            or permission == "skieo.unrestricted"
    end
    local game = {}
    local function action(name, ...)
        if not gameplay_allowed then
            error("script permission 'gameplay' is required for " .. name, 3)
        end
        return host.action(name, ...)
    end
    function game:set_time_rate(rate) return action("set_time_rate", rate) end
    function game:pause_time(paused) return action("pause_time", paused) end
    function game:force_weather(weather) return action("force_weather", weather) end
    function game:release_weather() return action("release_weather") end
    function game:add_funds(amount) return action("add_funds", amount) end
    function game:set_resort_status(status) return action("set_resort_status", status) end
    -- These synchronous operations are called from map callbacks on the game
    -- thread. A purchase returns its actual result before a script changes state.
    local function scenario_action(name, ...)
        if not gameplay_allowed then error("script permission 'gameplay' is required for " .. name, 3) end
        assert(host.scenario_action, "scenario host is unavailable")
        return host.scenario_action(self._session or self, name, ...)
    end
    function game:configure(options) return scenario_action("configure", options) end
    function game:snapshot() return scenario_action("snapshot") end
    function game:charge(amount, category, mandatory) return scenario_action("charge", amount, category, mandatory) end
    function game:record_revenue(amount) return scenario_action("revenue", amount) end
    function game:set_weather(weather, temperature) return scenario_action("weather", weather, temperature) end
    function game:placeables() return scenario_action("placeables") end
    function game:set_installation(id, properties) return scenario_action("installation", id, properties) end
    function game:place_resort(definitions, trails) return scenario_action("place_resort", definitions, trails) end
    function game:set_hub_names(anchors) return scenario_action('hub_names',anchors) end
    function game:set_trail_rating_system(options) return scenario_action('trail_rating_system',options) end
    function game:get_trail_rating_system() return scenario_action('get_trail_rating_system') end
    function game:get_trail_rating_capabilities() return scenario_action('get_trail_rating_capabilities') end
    self.game = game
    self._gameplay_allowed = gameplay_allowed
    return self
end

-- State is serialized inside each native save, including manual saves and
-- autosaves. UI callbacks and functions belong in the panel definition, never here.
function Api:state(defaults)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for state")
    local session = self._session or self
    if not session._persistent then session._persistent = defaults or {}
    elseif session._mapmod_only_state then
        for key, value in pairs(defaults or {}) do
            assert(key ~= '__mapmods', '__mapmods is reserved for dependency state')
            session._persistent[key] = value
        end
    end
    session._mapmod_only_state = nil
    assert(type(session._persistent) == 'table', 'state must be a JSON-compatible table')
    return session._persistent
end

function Api:building_properties(provider)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for building properties")
    checked_callback(provider, "api:building_properties")
    local session = self._session or self
    session._building_properties = provider
end

function Api:resort_panel(definition)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for resort controls")
    assert(type(definition) == 'table', 'resort panel must be a table')
    local session = self._session or self
    session._resort_panel = definition
end

function Api:scenario(definition)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for scenarios")
    assert(type(definition) == 'table' and type(definition.title) == 'string'
        and type(definition.objectives) == 'table' and #definition.objectives > 0
        and #definition.objectives <= 4, 'scenario needs a title and one to four objectives')
    local session = self._session or self
    if session._sandbox then return false end
    session._scenario = definition
end

function Api:on(event_name, callback)
    if not Api.EVENTS[event_name] then
        error("unknown Ski-E-O map event: " .. tostring(event_name), 2)
    end
    checked_callback(callback, "api:on")
    local handlers = self._handlers[event_name] or {}
    handlers[#handlers + 1] = callback
    self._handlers[event_name] = handlers
    return callback
end

function Api:off(event_name, callback)
    local handlers = self._handlers[event_name]
    if not handlers then return false end
    for index, registered in ipairs(handlers) do
        if registered == callback then
            table.remove(handlers, index)
            return true
        end
    end
    return false
end

function Api:log(message)
    self._host.log(string.format("[%s] %s", self._map.id, tostring(message)))
end

function Api:bind_key(key, callback)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for hotkeys")
    checked_callback(callback, "api:bind_key")
    return self._host.bind_key(self, key, callback)
end

-- Read only portable source data explicitly declared by content.assets.  This
-- works identically for a development directory and a store-only .skieomap,
-- without exposing arbitrary filesystem access to sandboxed map scripts.
function Api:read_asset(relative)
    if type(relative) ~= "string" or not self._asset_paths[relative] then
        error("asset is not declared by content.assets: " .. tostring(relative), 2)
    end
    local bytes, message = self._map.__read(relative)
    if not bytes then
        error("could not read map asset " .. relative .. ": "
            .. tostring(message), 2)
    end
    return bytes
end

-- Each dependency reads its own configuration and save-state namespace while
-- resources and timers are owned by the enclosing map session.
function Api:mapmod_options()
    local session = self._session or self
    local options = (session._map.extensions or {})[self._map.id] or {}
    local json = require('json')
    return json.decode(json.encode(options))
end

function Api:mod_state(defaults)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for state")
    local session = self._session or self
    if not session._persistent then
        session._persistent = {}
        session._mapmod_only_state = true
    end
    local states = session._persistent.__mapmods or {}
    session._persistent.__mapmods = states
    states[self._map.id] = states[self._map.id] or defaults or {}
    return states[self._map.id]
end

function Api:_entity_action(name, ...)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for entities")
    return self._host.entity_action(self, name, ...)
end
function Api:environment(x, y) return self:_entity_action('environment', x, y) end
function Api:spawn_animated(path, textures, options) return self:_entity_action('spawn', path, textures, options) end
function Api:footprint(x, y, yaw, texture) return self:_entity_action('footprint', x, y, yaw, texture) end
function Api:expire_footprints() return self:_entity_action('expire') end
function Api:focus_camera(x, y, z, distance) return self:_entity_action('focus_camera', x, y, z, distance) end

function Api:configure_surface_lifts(definitions, assets)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for surface lifts")
    assert(self._host.surface_lifts, 'This loader does not support surface lifts')
    return self._host.surface_lifts(self, definitions, assets)
end

function Api:place_objects(definitions)
    if not self._gameplay_allowed then error("script permission 'gameplay' is required for scene objects", 2) end
    if self._scene_started then error('Scene objects may be placed only once per map session', 2) end
    assert(type(definitions)=='table' and #definitions<=1024, 'Invalid scene objects')
    self._scene_started=true
    return self._host.place_objects(self,definitions)
end

function Api:apply_object_edits(edits, meshes)
    if not self._gameplay_allowed then error("script permission 'gameplay' is required for object edits", 2) end
    if self._object_edits_started then error('Object edits may be applied only once per map session', 2) end
    assert(type(edits) == 'table' and type(meshes) == 'table', 'Invalid object edits')
    self._object_edits_started = true
    return self._host.apply_object_edits(self, edits, meshes)
end

-- The CLI compiles JSON positions into SKXY before packaging. The runtime
-- reads only binary trees and reserves loading until native batches finish.
function Api:load_forest_skxy(relative, options)
    if not self._gameplay_allowed then
        error("script permission 'gameplay' is required for load_forest_skxy", 2)
    end
    local session = self._session or self
    if session._forest_requested then error("load_forest_skxy can only be called once per map session", 2) end
    if options ~= nil and type(options) ~= "table" then error("forest options must be a table", 2) end
    if type(relative) ~= "string" or not relative:match("%.skxy$") then
        error("load_forest_skxy requires a built .skxy asset", 2)
    end
    local bytes = self:read_asset(relative)
    local done = session:hold_loading()
    session._forest_requested = true
    local ok, message = pcall(self._host.load_forest_skxy, bytes, session, options, done)
    if not ok then
        done(tostring(message))
        error("could not load forest " .. relative .. ": " .. tostring(message), 2)
    end
end

-- Reserve a loading task synchronously in map.ready, then complete it from
-- the asynchronous station builder. The screen closes when all tasks finish.
function Api:loading_progress(stage, fraction)
    if type(stage) ~= "string" or type(fraction) ~= "number"
        or fraction ~= fraction or fraction < 0 or fraction > 1 then
        error("loading_progress expects a stage and a fraction between 0 and 1", 2)
    end
    if not self._loading_finished and self._host.loading_progress then
        self._host.loading_progress(self, stage, fraction)
    end
end

function Api:hold_loading()
    if self._loading_finished then error("map loading has already finished", 2) end
    self._loading_pending = self._loading_pending + 1
    local generation, completed = self._timer_generation, false
    return function(message)
        if completed or generation ~= self._timer_generation or self._loading_finished then return end
        completed = true
        self._loading_pending = self._loading_pending - 1
        if message then self:_finish_loading(false, tostring(message))
        else self:_try_finish_loading() end
    end
end

function Api:_finish_loading(success, message)
    if self._loading_finished then return end
    self._loading_finished = true
    self._loading_success = success
    if self._host.loading_finished then self._host.loading_finished(self, success, message) end
end

function Api:_try_finish_loading()
    if self._loading_ready and self._loading_pending == 0 then self:_finish_loading(true) end
end

function Api:_terrain_ready()
    self._loading_ready = true
    self:_try_finish_loading()
end

function Api:after(milliseconds, callback)
    if type(milliseconds) ~= "number" or milliseconds < 0 then
        error("api:after expects a non-negative delay", 2)
    end
    checked_callback(callback, "api:after")
    local generation = self._timer_generation
    self._host.defer(math.floor(milliseconds), function()
        if generation ~= self._timer_generation then return end
        local ok, message = pcall(function() callback();self:_sync_state() end)
        if not ok then self:log("timer error: " .. tostring(message)) end
    end)
end

function Api:every(milliseconds, callback, frame_loop)
    if type(milliseconds) ~= "number" or milliseconds < 16 then
        error("api:every expects a delay of at least 16 ms", 2)
    end
    checked_callback(callback, "api:every")
    local generation = self._timer_generation
    local handle = nil
    local tick
    local function cancel()
        self._loop_callbacks[tick] = nil
        if handle and type(CancelDelayedAction) == "function" then
            pcall(CancelDelayedAction, handle)
            handle = nil
        end
    end
    tick = function()
        if generation ~= self._timer_generation then cancel(); return false end
        local ok, keep_running = xpcall(function() local result=callback();if not frame_loop then self:_sync_state() end;return result end,
            function(message)return debug.traceback(tostring(message),2)end)
        if not ok then
            self:log("repeating timer error: " .. tostring(keep_running))
            cancel()
            return false
        end
        if keep_running == false then cancel() end
        return false
    end
    if frame_loop and EngineTickAvailable and type(LoopInGameThreadAfterFrames)=="function" then
        self._loop_callbacks[tick]=true
        handle=LoopInGameThreadAfterFrames(1,tick)
        self._loop_handles[#self._loop_handles+1]=handle
    elseif type(LoopInGameThreadWithDelay) == "function" then
        -- UE4SS may retain only a weak callback reference. A native handle
        -- alone does not keep loading/world guards alive through Lua GC.
        self._loop_callbacks[tick] = true
        handle = LoopInGameThreadWithDelay(math.floor(milliseconds), tick)
        self._loop_handles[#self._loop_handles + 1] = handle
    else
        local function fallback_tick()
            if generation ~= self._timer_generation then return end
            local ok, keep_running = xpcall(function() local result=callback();if not frame_loop then self:_sync_state() end;return result end,
                function(message)return debug.traceback(tostring(message),2)end)
            if not ok then
                self:log("repeating timer error: " .. tostring(keep_running))
            elseif keep_running ~= false then
                self._host.defer(math.floor(milliseconds), fallback_tick)
            end
        end
        self._host.defer(math.floor(milliseconds), fallback_tick)
    end
end

-- Frame loops are session scoped, retained through Lua GC, and cancelled by
-- the same generation guard as timers. Fall back to 16 ms on older UE4SS.
function Api:on_frame(callback)
    assert(self._gameplay_allowed, "script permission 'gameplay' is required for frame loops")
    return self:every(16,callback,true)
end

function Api:_emit(event_name, payload)
    local handlers = self._handlers[event_name] or {}
    for _, callback in ipairs(handlers) do
        local ok, message = pcall(callback, payload)
        if not ok then
            self:log(string.format("event %s failed: %s", event_name, tostring(message)))
            if event_name == "map.ready" or event_name == "map.terrain_loaded" then
                self:_finish_loading(false, tostring(message))
            end
        end
    end
    if event_name~='map.unloading' then self:_sync_state() end
end

function Api:_sync_state()
    if self._persistent and self._host.sync_state then self._host.sync_state(self._session or self) end
end

function Api:_stop()
    self._timer_generation = self._timer_generation + 1
    for _, cleanup in ipairs(self._cleanups or {}) do
        local ok, message = pcall(cleanup)
        if not ok then self:log('cleanup failed: ' .. tostring(message)) end
    end
    self._cleanups = {}
    if type(CancelDelayedAction) == "function" then
        for _, handle in ipairs(self._loop_handles) do
            pcall(CancelDelayedAction, handle)
        end
    end
    self._loop_handles = {}
    self._loop_callbacks = {}
    self._handlers = {}
end

return Api
