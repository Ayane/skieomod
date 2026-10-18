package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {} end
package.preload.catalog=function() return {} end
package.preload.terrain=function() return {} end
package.preload.loading=function() return {} end
local delayed=setmetatable({}, {__mode='v'})
local hooks={}
local in_game=false
ExecuteInGameThreadWithDelay=function(delay,callback)
 assert(delay==1);delayed[#delayed+1]=callback
end
ExecuteWithDelay=function() error('Widget injection must not run on the async Lua thread') end
RegisterHook=function(path,pre,post) hooks[path]=post or pre end
StaticFindObject=function(path)
 assert(path=='/Script/UMG.UserWidget:Construct' or path=='/Script/UMG.Widget:SetKeyboardFocus')
 return dofile('tests/support/reflection.lua').func({})
end
LoopInGameThreadWithDelay=function() return 1 end
local Runtime=require('runtime')
local UI=require('ui')
UI.install(Runtime)
local visits=0
for index=1,500 do
 local owner={IsValid=function()
  assert(in_game,'Widget accessed outside the game thread')
  visits=visits+1;collectgarbage('collect');return false
 end}
 hooks['/Script/UMG.UserWidget:Construct']({get=function() return owner end})
end
collectgarbage('collect')
assert(#delayed==500,'Widget callbacks were collected before dispatch')
in_game=true
for index=1,500 do
 assert(delayed[index],'Pending widget callback was collected during another injection')
 delayed[index]()
end
assert(visits==500 and next(Runtime.deferred_callbacks)==nil,'Widget callbacks leaked or ran more than once')
print('Widget timers: 500 callbacks retained through GC and dispatched on the game thread OK')
