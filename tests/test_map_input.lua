package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local registered,polled,commands={},{},{}
Key={F7=118,F9=120}
RegisterKeyBind=function(key,callback)registered[key]=callback end
ExecuteInGameThread=function()error('native input must not create cross-thread callback references')end
LoopInGameThreadWithDelay=function(delay,callback)assert(delay==16);polled[#polled+1]=callback;return #polled end
RegisterConsoleCommandHandler=function(name,callback)commands[name]=callback end
local Api,Input=require('api'),require('map_input')
local registering=true
RegisterKeyBind=function(key,callback)
    assert(registering,'native input was registered from a map callback')
    registered[key]=callback
end
Input.install();registering=false
Input.install()
assert(#polled==1,'input polling was registered more than once')
local poll=polled[1]
local errors={}
local host={log=function(message)errors[#errors+1]=message end,bind_key=Input.bind}
local map={id='test.input',script={permissions={'gameplay'}}}
local api=Api.new(host,map)
local presses=0
assert(not pcall(api.bind_key,api,'W',function()end),'ordinary gameplay key accepted')
assert(not pcall(api.bind_key,api,'F13',function()end),'unbounded function-key range accepted')
assert(not pcall(api.bind_key,api,'F7',false),'non-function callback accepted')
local release=api:bind_key('F7',function()presses=presses+1 end)
assert(not pcall(api.bind_key,api,'F7',function()end),'two owners claimed the same map hotkey')
registered[Key.F7]();poll();assert(presses==0,'hotkey ran before map loading')
api._loading_success=true
registered[Key.F7]();registered[Key.F7]();assert(presses==0,'key event called map code outside the game-thread poll')
collectgarbage('collect');poll();poll();assert(presses==1,'key flags were lost or stacked game-thread work')
commands.custommap_test_hotkey(nil,{'F7'});assert(presses==1,'QA command bypassed game-thread input polling')
poll();assert(presses==2,'QA command did not use the native key mailbox')
for _=1,100 do registered[Key.F7]();collectgarbage('collect');poll() end
assert(presses==102,'repeated F7 requests stopped cycling after GC')
registered[Key.F7]();release();release();poll();assert(presses==102,'released input flag still ran')
local scoped=Api.new(host,map);scoped._session=api
scoped:bind_key('F7',function()error('intentional callback error')end)
registered[Key.F7]();poll();assert(#errors==1 and errors[1]:find('intentional callback error',1,true),'hotkey error escaped its callback')
api:_stop();registered[Key.F7]();poll();assert(#errors==1,'dependency callback outlived its enclosing map')
print('Map input: bounded keys, callback validation, ownership, readiness, queued work, GC, release, errors and dependency cleanup OK')
Key.LEFT_MOUSE_BUTTON=1;Key.ESCAPE=27
registering=true;Input.install();registering=false
local mouse=Api.new(host,map);local actions={}
local detach=Input.bind_pointer(mouse,function(action)actions[#actions+1]=action end)
registered[1]();poll();assert(#actions==0,'mouse input ran before loading')
mouse._loading_success=true
registered[1]();registered[1]();assert(#actions==0,'mouse event called map code outside the game-thread poll')
collectgarbage('collect');poll();poll();assert(#actions==1 and actions[1]=='click','mouse flags were lost or stacked')
registered[1]();registered[27]();poll();assert(actions[2]=='close','Escape did not cancel a pending selection')
registered[1]();detach();poll();assert(#actions==2,'released mouse input still ran')
Input.bind_pointer(mouse,function(action)actions[#actions+1]=action end)
mouse:_stop();registered[1]();poll();assert(#actions==2,'mouse input survived its map session')
print('Entity input: native mouse/Escape dispatch, readiness, coalescing, close priority, GC, release and map cleanup OK')
