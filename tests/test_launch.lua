local json = require('mod.SkiEO-CustomMaps.Scripts.json')
local root = assert(arg[1], 'temporary fixture directory required')
local scripts = root .. '/Scripts/'
assert(os.execute('mkdir -p "' .. scripts .. '"'))
local loaded, started, ready, queued = {}, {}, false, {}
package.preload.json = function() return json end
package.preload.catalog = function() return {load = function(path)
    loaded[#loaded + 1] = path
    return {id = 'test.alpine', metadata = {version = '1.0.0'}}
end} end
package.preload.UEHelpers = function() return {
    GetWorld = function() return {IsValid = function() return ready end} end,
    GetPlayerController = function() return {IsValid = function() return ready end} end,
} end
ExecuteWithDelay = function(_, callback) queued[#queued + 1] = callback end
ExecuteInGameThread = function(callback) callback() end
local source = assert(io.open('mod/SkiEO-CustomMaps/Scripts/launch.lua')):read('*a')
local launch = assert(load(source, '@' .. scripts .. 'launch.lua'))()
local runtime = {refresh = function() end, log = function() end, start = function(map) started[#started + 1] = map; return true end}
local function request(overrides)
    local value = {format = 'skieomod-launch', version = 1, id = 'test.alpine', map_version = '1.0.0',
        created = os.time(), request_id = string.rep('a', 32), package_path = '../../../test.alpine-1.0.0.skieomap'}
    for key, entry in pairs(overrides or {}) do value[key] = entry end
    local file = assert(io.open(scripts .. 'launch-request.json', 'wb')); file:write(json.encode(value)); file:close()
    return value
end
local function pump() local callback = table.remove(queued, 1); assert(callback); callback() end
launch.install(runtime)
local value = request()
assert(launch.validate(value, os.time()))
pump(); assert(#started == 0 and #loaded == 0) -- wait for world and controller
ready = true
pump(); assert(#started == 1 and #loaded == 1)
assert(loaded[1] == scripts .. value.package_path)
assert(not io.open(scripts .. 'launch-request.json', 'rb'))
local result = json.decode(assert(io.open(scripts .. 'launch-result.json')):read('*a'))
assert(result.status == 'started' and result.request_id == value.request_id)
pump(); assert(#started == 1) -- no repeat on the next timer tick
request({created = os.time() - 301}); pump(); assert(#started == 1)
request({map_version = '2.0.0'}); pump(); assert(#started == 1)
local failed = json.decode(assert(io.open(scripts .. 'launch-result.json')):read('*a'))
assert(failed.status == 'error')
collectgarbage(); pump(); assert(#started == 1 and #queued == 1)

-- On recent UE4SS, recurring launch polling must stay on the game thread.
-- An async callback allocating in this Lua state can race terrain generation.
local native_callback, native_count = nil, 0
LoopInGameThreadWithDelay = function(delay, callback)
    assert(delay == 1000)
    native_callback, native_count = callback, native_count + 1
    return 17
end
local native_launch = assert(load(source, '@' .. scripts .. 'launch.lua'))()
local async_count = #queued
native_launch.install(runtime)
native_launch.install(runtime)
assert(native_count == 1 and native_launch.poll_handle == 17)
request()
collectgarbage('collect')
assert(native_launch.poll == native_callback and native_callback() == false)
assert(#started == 2 and #queued == async_count)
native_callback()
assert(#started == 2 and #queued == async_count)
print('Desktop launch: ready-world handoff, exact map version, one-shot consumption, expiry, failures and callback retention OK')

-- A test process reads only its editor's inbox. An ordinary game's request
-- remains untouched, and another editor cannot redirect this instance.
local getenv=os.getenv
local token=string.rep('c',32)
os.getenv=function(name) return name=='SKIEOMOD_EDITOR_SESSION' and token or getenv(name) end
local owned=assert(load(source,'@'..scripts..'launch.lua'))()
owned.install(runtime)
local generic=request()
owned.poll();assert(#started==2 and io.open(scripts..'launch-request.json'))
local function owned_request(target)
 local value=request({editor_session=target or token})
 os.rename(scripts..'launch-request.json',scripts..'launch-request-'..token..'.json')
 return value
end
local value=owned_request()
owned.poll();assert(#started==3)
local accepted=json.decode(assert(io.open(scripts..'launch-result-'..token..'.json')):read('*a'))
assert(accepted.request_id==value.request_id and accepted.status=='started')
owned_request(string.rep('d',32));owned.poll();assert(#started==3)
runtime.active_api={_loading_finished=false};owned_request();owned.poll();assert(#started==3)
local heartbeat=json.decode(assert(io.open(scripts..'editor-session-'..token..'.json')):read('*a'))
assert(heartbeat.session==token and heartbeat.state=='loading')
runtime.active_api._loading_finished=true;owned.poll();assert(#started==4)
os.getenv=getenv
print('Editor test sessions: isolated inboxes, ownership, reload and loading guard OK')
