package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function valid()return true end
local world={IsValid=valid,GetAddress=function()return 1 end}
local function object(o)o.IsValid=valid;o.GetWorld=function()return world end;o.GetFullName=function()return 'Current' end;return o end
package.preload.UEHelpers=function()return {GetWorld=function()return world end}end
local running,queries=true,0
local lift=object({IsLiftRunning=function()return running end,GetEffectiveOperatingSpeed=function()return running and 200 or 0 end,
    GetBottomTerminalLocation=function()return {X=0,Y=0,Z=100}end,
    GetTopTerminalLocation=function()return {X=10000,Y=0,Z=100}end})
local guests=object({GuestsHot={[1]={WorldPosition={X=5000,Y=1800,Z=100}},GetArrayNum=function()return 1 end}})
local selection=object({GetGuestNearPosition=function()queries=queries+1;return 0 end})
FindAllOf=function(name)return ({LiftActor={lift},GuestSimulationSubsystem={guests},GuestSelectionSubsystem={selection}})[name] or {}end
local D=require('map_disturbance');local state={}
local d=D.sample(state,5000,600,100,0)
assert(d.kind=='lift' and d.distance==600 and d.x==5000,'active cable corridor ignored')
assert(D.sample(state,5001,601,100,.2)==d and queries==1,'nearby behaviour repeated native queries')
running=false
d=D.sample(state,5000,600,100,1)
assert(d.kind=='person' and d.distance==1200,'nearest native guest missing after lift stopped')
guests.GuestsHot[1].WorldPosition.Z=10000
assert(D.sample(state,5000,600,100,2)==nil,'high, distant guest was treated as a nearby person')
guests.GuestsHot[1].WorldPosition.Z=100
assert(D.sample(state,0,0,100,3)==nil,'stopped lift still frightened wildlife')
running=true;d=D.sample(state,300,0,100,4)
assert(d.kind=='lift' and d.radius==3000 and d.distance==300,'terminal activity ignored')
-- World-owned sampler caches remain bounded during long excursions.
for i=1,600 do D.sample(state,i*300,5000,100,4) end
local count=0;for _ in pairs(state.disturbance_cache) do count=count+1 end
assert(count<=256,'disturbance cache grew without bound')
print('Map disturbance: operating terminals/corridors, native guests, vertical separation, stopped lifts and bounded cached queries OK')
