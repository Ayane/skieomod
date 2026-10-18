package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={IsValid=function() return true end}
local travelled
local gameplay={IsValid=function() return true end,OpenLevel=function(_,context,level,absolute,options)
    assert(context==world and absolute and options=='')
    travelled=level
end}
package.preload.UEHelpers=function() return {
    GetWorldContextObject=function() return world end,
    GetGameplayStatics=function() return gameplay end,
    FindOrAddFName=function(name) return name end,
} end
local loading
loading={active=true,update=function(stage) loading_stage=stage end,
    hide=function() loading.active=false end}
package.preload.loading=function() return loading end
local unloaded,cancelled,forests=0,0,0
package.preload.terrain=function() return {unload=function() unloaded=unloaded+1 end} end
package.preload.world=function() return {cancel=function() cancelled=cancelled+1 end} end
package.preload.vegetation=function() return {unload=function() forests=forests+1 end} end
package.preload.catalog=function() return {} end
local timers={}
ExecuteInGameThread=function() end
ExecuteInGameThreadWithDelay=function(delay,callback) timers[#timers+1]={delay,callback} end
local Runtime=require('runtime')
assert(Runtime.start({id='test.failure',metadata={name='Failed map',version='0.1.0'}}))
local api=Runtime.active_api
local pending_ran=false
api:after(10000,function() pending_ran=true end)
api:_finish_loading(false,'unsupported game build')
assert(timers[2][1]==1);timers[2][2]()
assert(loading.active and loading_stage:find('Loading failed',1,true))
assert(forests==1 and not travelled)
timers[1][2]();assert(not pending_ran,'failed load continued rebuilding its forest')
assert(timers[3][1]==5000);timers[3][2]()
assert(travelled=='/Game/Maps/MainMenu' and not loading.active)
assert(Runtime.active_api==nil and Runtime.active_map==nil and unloaded==2 and cancelled==2)

-- If native menu travel fails, retain the blocking error screen.
loading.active=true
gameplay.OpenLevel=function() error('travel rejected') end
assert(Runtime.start({id='test.failure-again',metadata={name='Failure',version='0.1.0'}}))
api=Runtime.active_api
api:_finish_loading(false,'station failure');timers[4][2]();timers[5][2]()
assert(loading.active and Runtime.active_api==api,'failed travel uncovered an incomplete map')
-- Save restoration uses inventory manifests too: corrupt installed payloads
-- must be rejected before any script/station is activated, with normal return.
loading.show=function(map) loading.active=true;loading.map=map end
require('catalog').load=function() return nil,'corrupt saved map terrain' end
local before=#timers
Runtime.restore({map={id='test.corrupt-save',metadata={name='Corrupt save',version='0.1.0'},__inventory_only=true,__manifest_path='corrupt.skieomap'}})
assert(Runtime.active_api._loading_finished and loading.active)
timers[before+1][2]()
gameplay.OpenLevel=function(_,context,level) travelled=level end
timers[before+2][2]()
assert(not Runtime.active_api and not loading.active and travelled=='/Game/Maps/MainMenu','invalid inventory save bypassed verification')
print('Loading failure: unfinished callbacks cancelled; return to menu; failed travel stays blocked OK')
