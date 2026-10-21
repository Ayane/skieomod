package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local calls,queue={},{}
local hold_snow,snow_finished=false,nil
local world={IsValid=function() return true end,GetAddress=function() return 7 end}
local function actor(name)
    return {name=name,z=0,IsValid=function() return true end,IsActorBeingDestroyed=function() return false end,
        GetClass=function() return {GetFullName=function() return 'Class Buildings/'..name end} end}
end
local building,lift,dead=actor('office'),actor('lift'),actor('deleted')
dead.IsActorBeingDestroyed=function() return true end
StaticFindObject=function(path) return path end
FindAllOf=function() return {} end
local gameplay={GetAllActorsOfClass=function(_,w,class,entries)
    assert(w==world)
    local values=class:find('BuildingActor',1,true) and {building,dead} or {lift}
    for _,a in ipairs(values) do entries[#entries+1]={get=function() return a end} end
end}
package.loaded.UEHelpers={GetWorld=function() return world end,GetGameplayStatics=function() return gameplay end}
package.loaded.terrain={unload=function() end,
    refine_snow_for_placeables=function(owners,done)
        assert(#owners==2 and owners[1]==building and owners[2]==lift)
        if hold_snow then snow_finished=done else done(true) end
    end,
    align_building=function(a) a.z=20 end,align_lift=function() end,
    align_native_trails=function() calls[#calls+1]='trails' end,
    clear_native_trail_obstacles=function() end,rebuild_trail_visuals=function() end,
    dismiss_buried_events=function() end,maintain_dynamic_grounding=function() end}
package.loaded.world={cancel=function() end,finish_loading=function() calls[#calls+1]='uncover' end}
local failed=false
local ski_calls=0
local ready_after=2
package.loaded.native_terrain={refresh_placeable_pads=function(owners)
    assert(#owners==2 and owners[1]==building and owners[2]==lift)
    assert(building.z==20 and lift.z==99,'pads preceded saved lift origin restoration')
    calls[#calls+1]='pads'
    return not failed,'guarded pad result'
end,register_placeable_hubs=function()
    assert(calls[#calls]=='pads');calls[#calls+1]='hubs';return true,'native hubs'
end,refresh_skiability=function()
    ski_calls=ski_calls+1
    if ski_calls<=ready_after then return false,'snow readback is not ready' end
    return true,'native snow checked'
end}
package.loaded.saves={restore_placeable=function(a)
    assert(a.z==20,'save restoration preceded source alignment')
    if a==lift then a.z=99 end
end}
package.loaded.catalog={}
package.loaded.loading={hide=function() calls[#calls+1]='hide' end,update=function() end}
package.loaded.vegetation={unload=function() end}
ExecuteInGameThread=function() end
ExecuteInGameThreadWithDelay=function() return 1 end
LoopInGameThreadWithDelay=function() return 1 end
local Runtime=require('runtime')
assert(Runtime.start({id='test.bootstrap',metadata={name='Bootstrap',version='1.0.0'}}))
local host=Runtime.active_api._host
local function run()
    calls,queue={},{}
    local api={_restoring=true,_loading_finished=true,
        after=function(_,delay,fn) queue[#queue+1]={delay=delay,callback=fn} end,every=function() end,on=function() end,
        _emit=function() end,
        _stop=function() calls[#calls+1]='stop' end}
    Runtime.active_api=api
    Runtime.active_map={id='test.source',metadata={name='Snow'},terrain={source={}}}
    host.loading_finished(api,true)
    assert(#queue==1 and #calls==0,'native finalization ran inside its hook stack')
    queue[1].callback()
end
run()
assert(table.concat(calls,',')=='pads,hubs,trails,uncover,hide',table.concat(calls,','))
local index=2
while index<=#queue do
    if queue[index].delay==500 then queue[index].callback() end
    index=index+1
end
assert(ski_calls==6,'skiability stopped before four ready readbacks or kept running afterwards')
ski_calls=0;ready_after=math.huge;run();index=2
while index<=#queue do
    assert(index<30,'snow readback retry was unbounded')
    if queue[index].delay==500 then queue[index].callback() end
    index=index+1
end
assert(ski_calls==20,'unavailable snow cache was retried indefinitely')
hold_snow=true;run()
assert(table.concat(calls,',')=='pads,hubs,trails,uncover','loading overlay disappeared before snow was ready')
snow_finished(true)
assert(calls[#calls]=='hide','ready snow did not finish loading')
run();snow_finished(false,'mesh rebuild failed')
assert(Runtime.active_api._loading_success==false,'snow failure retained a successful loading result')
queue[#queue].callback()
assert(calls[#calls]=='stop' and not table.concat(calls,','):find('hide',1,true),'snow failure exposed an unfinished world')
hold_snow=false
failed=true;run()
assert(table.concat(calls,',')=='pads,stop','a rejected native pad guard exposed the world')
print('Runtime terrain pads: final saved transforms, live actor iterator, deferred ordering and fail-closed loading OK')
