package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {} end
package.preload.catalog=function() return {} end
package.preload.terrain=function() return {} end
local loading={}
loading.show=function(map) loading.active=true;loading.map=map;loading.shown=(loading.shown or 0)+1 end
loading.update=function(stage,fraction) loading.stage=stage;loading.fraction=fraction end
loading.hide=function() loading.active=false end
package.preload.loading=function() return loading end
ExecuteInGameThread=function(callback) callback() end
local timers=setmetatable({}, {__mode='v'})
ExecuteInGameThreadWithDelay=function(delay,callback) assert(delay==100);timers[#timers+1]=callback end
local R=require('runtime')
local start=R.start
local local_map={id='test.local',metadata={name='Local'},__featured=true,__update={}}
local started,installs={},0
R.start=function(map,options)
    assert(loading.active and loading.map.id==map.id,'world loading did not continue acquisition screen')
    R.started_options=options
    started[#started+1]=map;return true
end
local completion,progress
R.install_map=function(map,callback,report)
    assert(loading.active and loading.shown>0,'download started before loading UI')
    installs=installs+1;completion,progress=callback,report;return true
end
local function tick()
    collectgarbage('collect')
    local callback=assert(table.remove(timers,1),'loading handoff callback was collected');callback()
end
R.featured.busy,R.workshop.busy=true,true
local result
assert(R.play(local_map,function(failure) result=failure or 'ready' end))
assert(loading.active and installs==0 and #started==0)
assert(not R.play(local_map),'double Play was accepted')
tick()
assert(result=='ready' and #started==1 and installs==0 and not R.pending_play)
assert(R.dependency_status(local_map),'an optional update prevented offline playback')
local remote={id='test.remote',metadata={name='Remote'},__unavailable=true,__featured=true}
local sandbox_options={seed=123,day_length=2,days_per_month=3,sandbox=true}
assert(R.play(remote,nil,false,sandbox_options))
sandbox_options.sandbox=false
tick();assert(installs==1 and loading.active and #started==1)
progress('Downloading map…',0.5)
assert(loading.stage=='Downloading map…' and loading.fraction>0)
local downloaded={id=remote.id,metadata=remote.metadata}
R.maps={local_map,downloaded};R.selected_index=1
completion()
assert(started[2]==downloaded and loading.active and not R.pending_play,'download launched the changed selection')
assert(R.started_options.sandbox and R.started_options.days_per_month==3,'download lost the captured game options')
assert(R.play(remote,function(failure) result=failure end));tick()
completion('offline')
assert(result=='offline' and not loading.active and #started==2 and not R.pending_play)
assert(R.play(local_map));tick();assert(started[3]==local_map,'failed download prevented retry')
R.maps={local_map}
assert(R.play(local_map,nil,true));tick()
assert(installs==3,'explicit Update used the offline Play path')
completion();assert(started[4]==local_map and not R.pending_play)
R.start=start
require('catalog').load=function() return nil,'terrain CRC mismatch' end
local invalid={id='test.invalid',metadata={name='Invalid',version='0.1.0'},__inventory_only=true,__manifest_path='invalid.skieomap'}
assert(R.play(invalid,function(failure) result=failure end));tick()
assert(result=='terrain CRC mismatch' and not R.active_map and not loading.active,'unverified inventory reached the world')
print('Play: offline installed maps, optional updates, retained loading handoff, progress, captured selection and retry OK')
