-- Exercise the actual synchronous native slot reconstruction on Off/save load.
local f=assert(io.open('mod/SkiEO-CustomMaps/Scripts/surface_lifts.lua'));local text=f:read('*a');f:close()
local helper=assert(text:match('local function set_speed.-\nend\n'));local source=assert(text:match('local function transport.-\nend\n'))
local failed=false;local rebuilds=0
local a={OperatingSpeed=0,speed=0,GetSpeedSetting=function(self)return self.speed end,
 SetSpeedSetting=function(self,v)self.speed=v end,RebuildChairMeshes=function(self)
 assert(self.OperatingSpeed==350 and self.speed==2,'Off restored an empty native carrier array')
 rebuilds=rebuilds+1;if failed then error('native rebuild failed')end
 end,CableSpline={GetDistanceAlongSplineAtSplinePoint=function()return 5000 end,
 FindInputKeyClosestToWorldLocation=function()return 1 end,GetDistanceAlongSplineAtSplineInputKey=function()return 5000 end}}
local env=setmetatable({Entities={prefetch_snow=function()end},Refresh={create=function()return{groups={{name='CableSpline',points={{},{}}}},profile={},queries={},index=1,marker={}}end,step=function()return true end},
 set_spline=function()end,surface=function()end,Native={set=function()end},Cycle={boarding=function()return 490 end}},{__index=_G})
local transport=assert(load(helper..source..'\nreturn transport','transport-test','t',env))()
local item={lift=a,definition={speed_mps=3.5},route={points={{},{}}},phase=10,requested_speed=0}
transport({api={},clock_seconds=1},item,true)
assert(rebuilds==1 and a.OperatingSpeed==0 and a.speed==0 and item.requested_speed==0)
item.transport_groups=nil;failed=true
assert(not pcall(transport,{api={},clock_seconds=2},item,true))
assert(a.OperatingSpeed==0 and a.speed==0 and not item.setting_speed,'Failed reconstruction changed the saved manual stop')
print('Stopped native save: rebuild carrier slots synchronously, preserve intent and restore speed on failure OK')
