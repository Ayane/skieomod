package.path = 'mod/SkiEO-CustomMaps/Scripts/?.lua;' .. package.path
package.preload.UEHelpers = function() return {} end
local async,game = setmetatable({}, {__mode='v'}),setmetatable({}, {__mode='v'})
ExecuteWithDelay = function(delay,callback) assert(delay==1);async[#async+1]=callback end
ExecuteInGameThread = function(callback) game[#game+1]=callback end
local Terrain=require('terrain')
local fired,in_game=0,false
Terrain.schedule(1,function()
 assert(in_game)
 collectgarbage('collect')
 assert(next(Terrain.callbacks),'active wrapper was released during the native invocation')
 fired=fired+1
end)
collectgarbage('collect')
assert(async[1],'delayed terrain callback was collected')
async[1]()
collectgarbage('collect')
assert(game[1],'game-thread terrain callback was collected')
in_game=true;game[1]();in_game=false
assert(fired==1 and next(Terrain.callbacks)==nil)
assert(Terrain.completed_callback and Terrain.completed_callback.game,'last native callback was not retained through return')
Terrain.schedule(1,function() error('unloaded terrain callback executed') end)
local cancelled=async[#async]
Terrain.unload()
cancelled()
in_game=true;game[#game]();in_game=false
assert(fired==1)
local native=require('native_terrain')
native.cache='fresh world bootstrap'
Terrain.unload(true)
assert(native.cache=='fresh world bootstrap','prepared native world was discarded')
Terrain.unload()
assert(native.cache==nil,'unloaded world retained its native cache')
print('Terrain timers: callback retention, game-thread dispatch and unload cancellation OK')
