package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local native=setmetatable({}, {__mode='v'})
local handles,cancelled=0,{}
LoopInGameThreadWithDelay=function(delay,callback)
    assert(delay==100);handles=handles+1;native[handles]=callback;return handles
end
CancelDelayedAction=function(handle) cancelled[handle]=true end
local logs={}
local api=require('api').new({log=function(message) logs[#logs+1]=message end}, {id='test.loops'})
local calls=0
api:every(100,function()
    calls=calls+1
    return calls<2
end)
collectgarbage('collect')
assert(native[1],'repeating loading guard was collected before its first tick')
native[1]()
collectgarbage('collect')
assert(native[1],'repeating loading guard was collected between ticks')
native[1]()
assert(calls==2 and cancelled[1])
collectgarbage('collect')
assert(not native[1],'cancelled repeating callback remained rooted')
api:every(100,function() error('loop failure') end)
collectgarbage('collect');assert(native[2]);native[2]()
assert(cancelled[2] and #logs==1 and logs[1]:find('loop failure',1,true))
assert(logs[1]:find('stack traceback:',1,true) and logs[1]:find('test_api_loops.lua',1,true),'timer errors lost their source traceback')
api:every(100,function() error('stopped map callback executed') end)
collectgarbage('collect');assert(native[3])
local stale=native[3]
api:_stop()
assert(cancelled[3] and not next(api._loop_callbacks))
stale();assert(#logs==1)
EngineTickAvailable=true
LoopInGameThreadAfterFrames=function(delay,callback)
    assert(delay==1);handles=handles+1;native[handles]=callback;return handles
end
local syncs=0
local frame_api=require('api').new({log=function()end,sync_state=function()syncs=syncs+1 end},
    {id='test.frames',script={permissions={'gameplay'}}})
frame_api:state({})
local rendered=0
frame_api:on_frame(function()rendered=rendered+1 end)
local frame_handle=handles
collectgarbage('collect');assert(native[frame_handle],'frame callback was not retained')
for _=1,120 do native[frame_handle]() end
assert(rendered==120 and syncs==0,'frame loop serialized save state on every image')
frame_api:_stop();assert(cancelled[frame_handle],'frame loop survived unloading')
local denied=require('api').new({}, {id='test.denied'})
assert(not pcall(denied.on_frame,denied,function()end),'frame callback bypassed gameplay permission')
print('API loops: weak UE4SS references, collection between ticks, errors and map cancellation OK')
