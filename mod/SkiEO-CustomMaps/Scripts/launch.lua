-- Local, one-shot handoff from skieomod. No URL or command is executed here.
local json, Catalog, UEHelpers = require('json'), require('catalog'), require('UEHelpers')
local Launch = {installed = false, dispatch_pending = false}
local directory = debug.getinfo(1, 'S').source:match('^@(.*[/\\])[^/\\]+$')
local session = os.getenv('SKIEOMOD_EDITOR_SESSION')
if not (session and #session==32 and session:match('^[0-9a-f]+$')) then session=nil end
local suffix = session and '-' .. session or ''
local function read(path)
    local file = io.open(path, 'rb'); if not file then return nil end
    local source = file:read(4097); file:close(); return source
end
local function valid(object) return object and object:IsValid() end
local function result(request, status, message)
    local path = directory .. 'launch-result' .. suffix .. '.json'
    local file = io.open(path .. '.part', 'wb')
    if not file then return end
    file:write(json.encode({request_id = request.request_id, status = status, message = message}))
    file:close(); os.remove(path); os.rename(path .. '.part', path)
end
function Launch.validate(request, now)
    assert(type(request) == 'table' and request.format == 'skieomod-launch' and request.version == 1, 'invalid launch request')
    assert(type(request.id) == 'string' and #request.id <= 120 and request.id:match('^[a-z0-9]+[._-][a-z0-9._-]+$'), 'invalid map identifier')
    assert(type(request.map_version) == 'string' and #request.map_version <= 80, 'invalid map version')
    assert(type(request.request_id) == 'string' and #request.request_id == 32 and request.request_id:match('^[0-9a-f]+$'), 'invalid request identifier')
    assert(type(request.created) == 'number' and request.created % 1 == 0 and now - request.created <= 300 and request.created - now <= 30, 'expired launch request')
    assert(type(request.package_path) == 'string' and #request.package_path <= 1024 and request.package_path:match('%.skieomap$') and not request.package_path:find('[%z\1-\31]'), 'invalid package path')
    if request.editor_session ~= nil then
        assert(type(request.editor_session)=='string' and #request.editor_session==32 and request.editor_session:match('^[0-9a-f]+$'), 'invalid editor session')
    end
    return request
end
function Launch.install(runtime)
    if Launch.installed or not directory then return end
    Launch.installed = true
    Launch.dispatch = function()
        Launch.dispatch_pending = false
        if session then
            local path=directory .. 'editor-session-' .. session .. '.json'
            local file=io.open(path .. '.part','wb')
            if file then
                file:write(json.encode({session=session,updated=os.time(),state=runtime.active_api and not runtime.active_api._loading_finished and 'loading' or 'ready'}))
                file:close();os.remove(path);os.rename(path .. '.part',path)
            end
        end
        local path = directory .. 'launch-request' .. suffix .. '.json'
        local source = read(path)
        if not source then return end
        local accepted, request = pcall(function()
            assert(#source <= 4096, 'launch request is too large')
            return Launch.validate(json.decode(source), os.time())
        end)
        if not accepted then
            os.remove(path); runtime.log('ignored launch request: ' .. tostring(request)); return
        end
        if request.editor_session ~= session then
            os.remove(path);runtime.log('ignored launch request belonging to another editor session');return
        end
        if runtime.active_api and not runtime.active_api._loading_finished then return end
        local ready, available = pcall(function()
            return valid(UEHelpers.GetWorld()) and valid(UEHelpers.GetPlayerController())
        end)
        if not ready or not available then return end
        -- Consume once before scheduling world travel; keep the requested version,
        -- even when a newer version is also in the catalogue.
        os.remove(path)
        local started, failure = pcall(function()
            runtime.refresh()
            local absolute = request.package_path:match('^[A-Za-z]:[/\\]') or request.package_path:sub(1, 1) == '/'
            local map, problem = Catalog.load(absolute and request.package_path or directory .. request.package_path)
            assert(map, problem)
            assert(map.id == request.id and map.metadata.version == request.map_version, 'installed map differs from launch request')
            assert(runtime.start(map), 'map could not be started; inspect the Custom Map log')
        end)
        result(request, started and 'started' or 'error', started and request.id or tostring(failure))
        if not started then runtime.log('skieomod launch failed: ' .. tostring(failure)) end
    end
    -- Both Lua stacks share one allocator and registry. Polling on the async
    -- thread can race terrain generation even when it only queues game work.
    -- Use a single game-thread timer, as the map and UI already do.
    if type(LoopInGameThreadWithDelay) == 'function' then
        Launch.poll = function() Launch.dispatch(); return false end
        Launch.poll_handle = LoopInGameThreadWithDelay(1000, Launch.poll)
        return
    end
    Launch.poll = function()
        if not Launch.dispatch_pending then
            Launch.dispatch_pending = true
            ExecuteInGameThread(Launch.dispatch)
        end
        ExecuteWithDelay(1000, Launch.poll)
    end
    ExecuteWithDelay(1000, Launch.poll)
end
return Launch
