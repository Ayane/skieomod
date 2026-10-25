package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Drain=require('surface_lift_drain')
local saved={};local state={api={mod_state=function()return saved end},items={}}
local lift={GetActiveRiderCount=function(self)return self.riders or 0 end,IsEventDisabled=function()return false end,IsManualRepairActive=function()return false end,IsWithinOperatingHours=function()return true end,IsOpenForBusiness=function()return true end,OperatingSpeed=0,IsWindingDown=function(self)return self.wind end}
local item={id='one',state=state,lift=lift,definition={kind='detachable_platter',speed_mps=3},cycle={poles={{state='line'},{state='stock'}}},requested_speed=0};state.items={item}
local publish=Drain.publish;Drain.publish=function()end
Drain.request(item);assert(item.draining and lift.OperatingSpeed==300 and saved.detachable_drains.one)
item.cycle.poles[1].state='rail';Drain.update(state,true);assert(item.draining,'A hanger still travelling along the rail must keep winding down')
item.cycle.poles[1].state='stock';Drain.update(state,true);assert(not item.draining and lift.OperatingSpeed==0 and not saved.detachable_drains.one)
item.cycle.poles[1].state='line';lift.wind=true;item.requested_speed=2;Drain.update(state,false);assert(item.draining)
item.snow_blocked=true;Drain.update(state,false);assert(not item.draining,'Hard snow stop must override wind-down')
item.snow_blocked=false;item.evacuation_waiting=1;Drain.request(item);assert(not item.draining)
item.evacuation_waiting=0;saved.detachable_drains.one=true;Drain.restore(item);assert(item.draining,'Saved wind-down must resume with native rider count zero')
Drain.cancel(item);assert(not saved.detachable_drains.one)
item.cycle.poles[1].state='stock';lift.riders=1
Drain.request(item);Drain.update(state,true);assert(item.draining,'An undiscovered native rider must finish the trip')
lift.riders=0;Drain.update(state,true);assert(not item.draining)
item.cycle.poles[1].state='line'
item.definition.kind='fixed_platter';Drain.request(item);assert(not item.draining)
Drain.publish=publish
print('Detachable winding-down: empty return, guide rail, saved state, hard stops and fixed grips OK')
