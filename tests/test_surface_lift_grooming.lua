package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={GetAddress=function()return 1 end,IsValid=function()return true end}
package.preload.UEHelpers=function()return{GetWorld=function()return world end}end
package.preload.terrain=function()return{}end
package.preload.portable_mesh=function()return{}end
local snow={snow_ready=true,snow_cm=300}
package.preload.map_entities=function()return{environment=function()return snow end}end
local G=require('surface_lift_geometry');local Groom=require('surface_lift_grooming')
local definition={name='test',route={{1000,1000,0},{1000,6000,0},{5000,6000,0}},kind='fixed_platter',pylons=2,speed_mps=2,capacity_per_hour=600,ascent_side='right'}
local route=G.route(definition,function()return 0 end)
local curves=Groom.curves(route)
assert(#curves>=4)
local first,last=curves[1],curves[#curves]
assert(math.abs(first.StartPoint.X-(route.points[#route.points].x-route.points[#route.points].nx*350))<1e-8)
assert(math.abs(last.Endpoint.Y-(route.points[1].y-route.points[1].ny*350))<1e-8)
for i,c in ipairs(curves)do
 assert(c.CorridorWidth==500)
 if i>1 then assert(c.StartPoint==curves[i-1].Endpoint,'Maintenance corridor disconnected')end
 assert(c.ControlPoint.X==(c.StartPoint.X+c.Endpoint.X)*.5)
end
local actor={x=650,y=2000,IsValid=function()return true end,IsActorBeingDestroyed=function()return false end,
 GetFullName=function()return 'SnowcatVehicleActor test'end,GetWorld=function()return world end,
 K2_GetActorLocation=function(self)return{X=self.x,Y=self.y,Z=0}end,GetAddress=function()return 2 end}
local job=true
local groom={IsValid=function()return true end,GetFullName=function()return 'GroomingSubsystem test'end,GetWorld=function()return world end,
 HasActiveGroomingEvent=function()return job end}
local member={ID={A=1,B=2,C=3,D=4},bExternallyDriven=true}
local staff={IsValid=function()return true end,GetFullName=function()return 'StaffSubsystem test'end,GetWorld=function()return world end,
 GetStaffByRole=function()return{member}end,TryGetStaffWorldPosition=function(_,_,p)p.X=actor.x;p.Y=actor.y;p.Z=0;return true end}
FindAllOf=function(c)return c=='GroomingSubsystem'and{groom}or c=='StaffSubsystem'and{staff}or{}end
local item={route=route,groom_trail=1,groom_next=100,groom_stamps=0}
local state={items={item},api={}}
Groom.remove({groom_hidden={[1]=true}}, {}) -- chairlifts own no maintenance trail
local grade=Groom.grade
local draws=0
Groom.grade=function(_,stamps)draws=draws+#stamps end
local env={hours=1,paused=false}
Groom.update(state,env);assert(draws==0,'An initial placement is not a blade passage')
Groom.update(state,env);assert(draws==0,'Parked snowcat changed snow')
actor.y=2300;Groom.update(state,env);assert(draws>0,'A moving native snowcat on the job must grade the ascent')
local before=draws
actor.y=5900;Groom.update(state,env);assert(draws==before,'A teleport changed the snow')
actor.x=8000;actor.y=6000;Groom.update(state,env);actor.x=8100;Groom.update(state,env);assert(draws==before,'A snowcat outside the ascent graded the line')
actor.x=650;actor.y=2500;Groom.update(state,env)
job=false;actor.y=2800;Groom.update(state,env);assert(draws==before,'Snow changed without a native maintenance job')
job=true;snow.snow_cm=50;actor.y=3000;Groom.update(state,env);assert(draws==before,'Blade added snow to a shallow track')
snow.snow_cm=300;snow.snow_ready=false;actor.y=3200;Groom.update(state,env);assert(draws==before,'Unknown snow was overwritten')
snow.snow_ready=true;item.evacuation_waiting=1;actor.y=3300;Groom.update(state,env);assert(draws==before,'Snowcat graded an evacuation corridor')
item.evacuation_waiting=0
snow.snow_ready=true;env.paused=true;actor.y=3400;Groom.update(state,env);assert(draws==before,'Paused snowcat changed snow')
-- Exercise the real packet writer: a long blade sweep must retain its last
-- samples, and an old success file must never validate a silent native call.
local storage,batches={},{}
local native_snow={IsValid=function()return true end,GetFullName=function()return 'SnowSimulationSubsystem test'end,
 GetWorld=function()return world end,GetAddress=function()return 4 end,GetClass=function()return{GetAddress=function()return 5 end}end}
FindAllOf=function(c)return c=='SnowSimulationSubsystem'and{native_snow}or{}end
local original_open,original_remove,original_load=io.open,os.remove,package.loadlib
local reply=true
io.open=function(path,mode)
 if mode=='wb'then return{write=function(_,...)storage[path]=table.concat({...})end,close=function()end}end
 if not storage[path]then return nil end
 return{read=function()return storage[path]end,close=function()end}
end
os.remove=function(path)storage[path]=nil;return true end
package.loadlib=function()return function()
 local job,status;for k in pairs(storage)do if k:match('surface%-grade.job$')then job=k;status=k:gsub('%.job$','.status')end end
 assert(not storage[status],'Stale native status was not removed')
 batches[#batches+1]=storage[job]
 if reply then storage[status]='ok: native snowcat blade'end
end end
local stamps={};for i=1,300 do stamps[i]={x=i*100,y=0,radius=250}end
grade(state,stamps)
assert(#batches==2)
local total=0
for _,bytes in ipairs(batches)do
 local magic,version,count,_,owner,cls=string.unpack('<c4I4I4I4I8I8',bytes)
 assert(magic=='SKSG'and version==2 and owner==4 and cls==5 and count<=256)
 assert(#bytes==32+count*24);total=total+count
end
assert(total==300,'Long native movement lost blade samples')
local x,y,radius=string.unpack('<ddf',batches[2],#batches[2]-23)
assert(x==30000 and y==0 and radius==250,'Last bounded blade footprint was dropped')
reply=false;assert(not pcall(grade,state,{{x=0,y=0}}),'A stale native success validated a failed call')
io.open,os.remove,package.loadlib=original_open,original_remove,original_load
print('Native snowcat maintenance: connected ascent, movement, snow and pause guards, complete bounded blade packets and stale-result rejection OK')
-- A saved skier may still reference the duplicate trail during migration.
-- Never delete its route or send its held snowcat home before clearance.
local retired={['7']={owner='old',x=1,y=2,name='owned'}}
local old_trail={TrailId=7,bManuallyDisabled=true,DisplayName={ToString=function()return'owned'end},Curve={StartPoint={X=1,Y=2}}}
local occupied=true;local canceled,removed=0,0
local native_guests={IsValid=function()return true end,GuestsHot={ForEach=function(_,fn)if occupied then fn(1,{get=function()return{CurrentTrailId=7}end})end end}}
local native_groom={IsValid=function()return true end,GetFullName=function()return'GroomingSubsystem'end,GetWorld=function()return world end,
 HasActiveGroomingEvent=function()return true end,OnTrailUnregistered=function(_,id)assert(id==7);canceled=canceled+1 end}
FindAllOf=function(name)return name=='GroomingSubsystem'and{native_groom}or{}end
local migration={api={mod_state=function()return{grooming_retired=retired}end},guests=native_guests,groom_hidden={},evacuation_records={saved={trail=7}},
 groom_trails={RegisteredTrails={ForEach=function(_,fn)fn(1,{get=function()return old_trail end})end},
 SetTrailGroomed=function()end,UnregisterTrail=function(_,id)assert(id==7);removed=removed+1 end}}
Groom.finalize(migration);assert(removed==0 and canceled==0 and retired['7'])
occupied=false;Groom.finalize(migration);assert(removed==0,'A saved route disappeared before native guests finished restoring')
migration.evacuation_records={};Groom.finalize(migration);assert(removed==1 and canceled==1 and not retired['7'])
print('Shared corridor save migration: saved route and snowcat remain held until clearance OK')
