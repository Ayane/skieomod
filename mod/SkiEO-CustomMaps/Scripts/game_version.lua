-- Exact executable recognition is independent of optional native capabilities.
-- Never infer full build support from an engine version or a matching hook.
local supported = require('supported_game_builds')
local Version = {}
local directory = debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local started, deadline, result, native, next_poll
local labels = {}
for _, entry in pairs(supported) do labels[#labels+1] = entry.build end
table.sort(labels)
local advice = 'Supported Steam build: '..table.concat(labels,', ')..'. Update Custom Map at skieomod.emillon.fr.'

function Version.classify(status)
    local digest = type(status)=='string' and status:match('^ok ([0-9a-f]+)$')
    local entry = digest and #digest==64 and supported[digest]
    if entry then return {supported=true, build=entry.build, app_id=entry.app_id} end
    return {supported=false, title=digest and #digest==64 and 'Unsupported game version' or 'Game version could not be verified',
        detail='Map loading may fail with this game version. '..advice}
end

function Version.poll()
    if result then return result end
    local now = os.time()
    if not started then
        started, deadline = true, now+30
        local ok, failure = pcall(function()
            assert(directory,'loader path unavailable')
            -- Remove an earlier process's result before starting the worker.
            local path=directory..'game_identity.status'
            local previous=io.open(path,'rb')
            if previous then
                previous:close()
                assert(os.remove(path),'cannot clear previous game version check')
            end
            native = assert(package.loadlib(directory..'skieo_repository.dll','skieo_game_identity'))
            native()
        end)
        if not ok then result=Version.classify(tostring(failure)); return result end
    end
    if not next_poll or now>=next_poll then
        next_poll=now+1
        local file=io.open(directory..'game_identity.status','rb')
        if file then
            local status=file:read(256);file:close()
            if status then result=Version.classify(status) end
        end
        if not result and now>=deadline then result=Version.classify('timeout') end
    end
    return result or {checking=true}
end
return Version
