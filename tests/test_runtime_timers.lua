package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
package.preload.UEHelpers = function() return {} end
package.preload.terrain = function() return {unload = function() end} end
package.preload.catalog = function() return {} end
package.preload.loading = function() return {} end

-- UE4SS keeps weak callback references. Simulate both its async delay queue
-- and its game-thread queue, including collection between dispatches.
local async = setmetatable({}, {__mode = "v"})
local game = setmetatable({}, {__mode = "v"})
local async_count, game_count = 0, 0
local in_game_thread = false
ExecuteWithDelay = function(delay, callback)
    assert(delay == 25)
    async_count = async_count + 1
    async[async_count] = callback
end
ExecuteInGameThread = function(callback)
    game_count = game_count + 1
    game[game_count] = callback
end

local Runtime = require("runtime")
assert(Runtime.vegetation == package.loaded.vegetation,
    "loader vegetation must be resolved before map script paths are added")
assert(Runtime.start({id = "test.timers", metadata = {name = "Timers"}}))
local api = Runtime.active_api
local fired = 0
api:after(25, function()
    assert(in_game_thread, "map callback ran on the async thread")
    collectgarbage('collect')
    assert(next(Runtime.deferred_callbacks),'executing callback released before its native call returned')
    fired = fired + 1
end)
collectgarbage("collect")
assert(game[1], "initial map loading callback was collected")
assert(async[1], "pending delayed callback was collected")
async[1]()
assert(fired == 0, "async delay performed game work directly")
collectgarbage("collect")
assert(game[2], "queued game callback was collected")
in_game_thread = true
game[2]()
in_game_thread = false
assert(fired == 1 and next(Runtime.deferred_callbacks) == nil)

-- Prefer the native game-thread timer when available, with the same lifetime
-- guarantees. Stopping a map must still suppress its pending callbacks.
local native = setmetatable({}, {__mode = "v"})
local native_count = 0
ExecuteInGameThreadWithDelay = function(delay, callback)
    assert(delay == 25)
    native_count = native_count + 1
    native[native_count] = callback
end
api:after(25, function() assert(in_game_thread); fired = fired + 1 end)
collectgarbage("collect")
assert(native[1] and async_count == 1)
in_game_thread = true
native[1]()
in_game_thread = false
assert(fired == 2 and next(Runtime.deferred_callbacks) == nil)
api:after(25, function() error("stopped map callback executed") end)
api:_stop()
collectgarbage("collect")
assert(native[2])
in_game_thread = true
native[2]()
assert(fired == 2 and next(Runtime.deferred_callbacks) == nil)
print("Runtime timers: game-thread dispatch, GC retention and cancellation OK")
