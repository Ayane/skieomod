-- Normal wind-down returns every retained detachable hanger to the lower
-- stock rail. Snow/event/emergency stops still release passengers immediately.
local Drain={}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local native,reviewed
local function parked(item)
 if not item.cycle then return true end
 for _,pole in ipairs(item.cycle.poles)do if pole.state~='stock'then return false end end
 return true
end
function Drain.request(item)
 if item.definition.kind~='detachable_platter'or not item.cycle then return end
 if not item.snow_blocked and not item.lift:IsEventDisabled()and not item.lift:IsManualRepairActive()and(item.evacuation_waiting or 0)==0 and(not parked(item)or item.lift:GetActiveRiderCount()>0)then
  item.draining=true;item.lift.OperatingSpeed=item.definition.speed_mps*100
  local saved=item.state.api:mod_state();saved.detachable_drains=saved.detachable_drains or{};saved.detachable_drains[item.id]=true
 end
end
function Drain.cancel(item)
 item.draining=false
 local saved=item.state.api:mod_state();if saved.detachable_drains then saved.detachable_drains[item.id]=nil end
end
function Drain.publish(state,dispose)
 local rows,keys={},{}
 for _,item in ipairs(state.items)do if not dispose and not item.disposed and item.draining then
  rows[#rows+1]=string.pack('<I8I8fI4',item.lift:GetAddress(),item.lift:GetClass():GetAddress(),item.definition.speed_mps*60,0)
  keys[#keys+1]=item.id
 end end
 table.sort(keys);local key=table.concat(keys,';')
 if key==state.drain_key then return end
 if not reviewed then
  local ok,detail=require('compatibility').check('surface_lifts.wind_down',{classes={
   ['/Script/SkiResortSimulator.LiftActor']={OperatingSpeed={type='FloatProperty',offset=0x464},CurrentSpeedSetting={type='EnumProperty',offset=0x474}}},
   functions={['/Script/SkiResortSimulator.LiftActor:IsWindingDown']={ReturnValue='BoolProperty'}}})
  assert(ok,detail);reviewed=true
 end
 native=native or assert(package.loadlib(directory..'skieo_surface_lifts.dll','skieo_surface_drain'))
 local f=assert(io.open(directory..'surface-drain.job','wb'))
 f:write(string.pack('<c4I4I4I4','SKDR',1,#rows,0),table.concat(rows),string.rep('\0',(16-#rows)*24));f:close()
 os.remove(directory..'surface-drain.status');native()
 f=assert(io.open(directory..'surface-drain.status','rb'));local status=f:read('*a');f:close();assert(status:sub(1,3)=='ok:',status)
 state.drain_key=key
end
function Drain.update(state,after_binding)
 for _,item in ipairs(state.items)do if not item.disposed and item.cycle then
  if item.snow_blocked or item.lift:IsEventDisabled()or item.lift:IsManualRepairActive()or(item.evacuation_waiting or 0)>0 then Drain.cancel(item)
  elseif after_binding and item.draining and parked(item)and item.lift:GetActiveRiderCount()==0 then
   Drain.cancel(item);if item.requested_speed==0 then item.lift.OperatingSpeed=0 end
  elseif not item.draining and(not parked(item)or item.lift:GetActiveRiderCount()>0)and(item.lift:IsWindingDown()
   or item.requested_speed==0 or not item.lift:IsWithinOperatingHours()or not item.lift:IsOpenForBusiness())then Drain.request(item)end
 end end
 Drain.publish(state)
end
function Drain.restore(item)
 local saved=item.state.api:mod_state();saved.detachable_drains=saved.detachable_drains or{}
 if saved.detachable_drains[item.id]or item.requested_speed==0 then Drain.request(item)end
end
Drain.parked=parked
return Drain
