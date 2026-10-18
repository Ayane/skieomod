-- Run the shipped example through the real sandbox and dependency proxy.
package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function()return {}end
package.preload.terrain=function()return {unload=function()end}end
package.preload.loading=function()return {}end
package.preload.saves=function()return {sync_native=function()end}end
local pending,keys,key_registrations={}, {},0
ExecuteInGameThread=function(callback)pending[#pending+1]=callback end
Key={F7=118}
RegisterKeyBind=function(key,callback)keys[key]=callback;key_registrations=key_registrations+1 end
ExecuteWithDelay=function()end
local loops,frames={},{}
EngineTickAvailable=true
LoopInGameThreadAfterFrames=function(count,callback)assert(count==1);frames[#frames+1]=callback;return #frames end
LoopInGameThreadWithDelay=function(_,callback)loops[#loops+1]=callback;return #loops end
CancelDelayedAction=function()end
local created,poses,disposed,looks=0,0,0,0
local inspections={}
local focused,paused,seconds,ready={},false,0,true
package.preload.map_entities=function()return {
    environment=function(_,x,y)return {inside=true,ground=0,z=30,snow_cm=12,trail=false,hour=22,paused=paused,rate=1,hours=0,seconds=seconds,ready=ready}end,
    focus_camera=function(_,x,y,z,distance)focused[#focused+1]={x=x,y=y,z=z,distance=distance}end,
    spawn=function(api,path,textures,options)
        assert(path=='Assets/fox.skan','a rodent model was spawned above the snow')
        assert(api:read_asset(path) and api:read_asset(textures[1]))
        if options then assert(api:read_asset(options.aim_rig)) end
        created=created+1;local session=api._session
        assert(session,'dependency lost its map session')
        session._cleanups=session._cleanups or {};session._cleanups[#session._cleanups+1]=function()disposed=disposed+1 end
        return {pose=function()poses=poses+1 end,look_at=function()looks=looks+1 end,
            inspect=function(_,provider)inspections[#inspections+1]=provider end}
    end,footprint=function()end,expire=function()end,
}end
local Json,Runtime=require('json'),require('runtime')
require('map_input').install()
local input_poll=frames[1]
local function read(path)local f=assert(io.open(path,'rb'));local b=f:read('*a');f:close();return b end
local mod=Json.decode(read('mod/SkiEO-Foxes/custom-mod.json'))
mod.__manifest_path='fox-example';mod.__read=function(path)return read('mod/SkiEO-Foxes/'..path)end
Runtime.mods={mod}
local map={id='test.fox-map',metadata={name='Fox sandbox',version='1.0.0'},
    dependencies={{id='community.foxes',version='=0.4.0'}},extensions={['community.foxes']={count=3}}}
assert(Runtime.start(map));Runtime.emit('map.ready')
assert(created==3 and poses==3,'fox population did not start through dependency API')
assert(#inspections==3 and inspections[1]().title=='Renard roux' and #inspections[1]().properties==2,'fox inspection panel is missing or excessive')
local state=Runtime.active_api._persistent.__mapmods['community.foxes']
assert(#state.foxes==3,'map-specific configuration was lost')
local function press()
    keys[Key.F7]()
    input_poll()
end
press();assert(#focused==0,'hotkey moved the camera before loading finished')
Runtime.active_api._loading_success=true
local seed=state.seed
for i=1,4 do
    local before=#focused;keys[Key.F7]()
    assert(#focused==before,'key callback accessed the camera outside the game thread')
    input_poll()
    local fox=state.foxes[(i-1)%3+1]
    assert(math.abs(focused[i].x-fox.x)<.0001 and math.abs(focused[i].y-fox.y)<.0001
        and focused[i].z==65,'F7 did not cycle through existing foxes')
end
assert(state.seed==seed and created==3,'camera shortcut changed the population or random state')
assert(#frames==2,'input polling and fox rendering did not use the engine frame loop')
local function frame(dt) seconds=seconds+dt;for _,tick in ipairs(frames) do tick() end end
local before=poses
for _=1,120 do frame(1/60) end
assert(poses-before>=175 and poses-before<=185,'nearby animation did not run at 30 Hz independent of 10 Hz AI: '..(poses-before))
paused=true;local old_poses=poses;local old_looks=looks
for _=1,300 do frame(.4) end
for _,tick in ipairs(loops) do tick() end
assert(poses==old_poses and looks==old_looks,'long pause advanced the animation or gaze')
press();assert(#focused==5 and poses==old_poses,'paused map could not focus a fox')
paused=false
for _=1,100 do frame(1/60) end
for _,tick in ipairs(loops) do tick() end
assert(poses>100,'animation timer did not run')
assert(looks>100,'behaviour did not drive the gaze handle')
state=Runtime.active_api._persistent.__mapmods['community.foxes']
press();assert(math.abs(focused[6].x-state.foxes[3].x)<.0001,'shortcut used an old position after the fox moved')
keys[Key.F7]()
Runtime.active_api:_stop();assert(disposed==created,'stopped session kept mapmod actors')
local queued_before=#pending
input_poll();keys[Key.F7]();input_poll();assert(#focused==6 and #pending==queued_before,'unloaded map retained a keyboard callback')
local count=poses;frame(1/60);for _,tick in ipairs(loops) do tick() end;assert(poses==count,'old session timer continued')
ready=false;paused=true;local old=poses
assert(Runtime.start(map));Runtime.emit('map.ready');Runtime.active_api._loading_success=true
frame(1);assert(poses==old,'fox was positioned before native snow initialization')
ready=true;frame(1/60);assert(poses==old+3,'initially paused map did not place foxes above snow')
frame(2);assert(poses==old+3,'initial placement kept moving while paused')
press();assert(#focused==7 and key_registrations==1,'map reload stacked native key registrations')
Runtime.active_api:_stop()
print('Fox mapmod: sandbox, options, save state, animation, F7 cycling/current positions/pause/game thread/loading/unload/reload and cleanup OK')
