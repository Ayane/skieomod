package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local G=require('surface_lift_geometry')
local Refresh=require('surface_lift_refresh')
local Riders=require('surface_lift_riders')
local function close(a,b)assert(math.abs(a-b)<1e-6,tostring(a)..' differs from '..tostring(b))end

-- Long profiles used to read thousands of snow cells synchronously in one
-- frame. Include terminal loops and the return marker in the same work budget.
local definition={name='Long lift',route={{0,0,0},{120000,0,0}},ascent_side='right',
 kind='detachable_platter',speed_mps=3,capacity_per_hour=720,pylons=8}
local route=G.route(definition,function(x,y)return x*.1+y*.2 end)
local item={route=route,splines={
 StartLoopSpline={points={{X=-100,Y=240,Z=200},{X=0,Y=-240,Z=200}},closed=true},
 EndLoopSpline={points={{X=120100,Y=240,Z=200},{X=120000,Y=-240,Z=200}},closed=false}}}
local job=Refresh.create(item);local calls=0
local function sample(x,y)calls=calls+1;local ground=x*.1+y*.2;return ground+50,ground end
local done=false
while not done do
 local before=calls;done=Refresh.step(job,sample,8)
 assert(calls-before<=8,'Snow refresh exceeded its per-frame budget')
end
assert(calls==#job.queries and calls>1000)
assert(job.groups[2].closed and not job.groups[3].closed)
assert(job.groups[2].points[1].Y==-240,'Terminal loop mirror was lost')
for _,group in ipairs(job.groups)do for _,p in ipairs(group.points)do close(p.Z,p.X*.1+p.Y*.2+53)end end
for _,depth in ipairs(job.profile)do close(depth,50)end
assert(#job.profile==#job.groups[1].points)
close(job.marker.Z,job.marker.X*.1+job.marker.Y*.2+53)
assert(not pcall(Refresh.step,Refresh.create(item),function()return nil end,8))
print('Long snow profiles, terminal loops and marker readback stay within eight samples per frame OK')

-- A busy resort should scan all guests four times per second, while current
-- passenger positions continue to update at the full frame rate.
local function id(n)return{A=n,B=0,C=0,D=0}end
local function key(n)return string.format('%08x-%08x-%08x-%08x',n,0,0,0)end
local hot,cold={},{};local scans,reads=0,0;local size=10000;local cold_size
for i=1,size do
 hot[i]={ActivityState=0,WorldPosition={X=0,Y=0,Z=0},ColorIndex=0}
 cold[i]={GuestId=id(i+99),QueueLiftId=id(1),Discipline=0}
end
hot[1].ActivityState=3;hot[38].ActivityState=3;hot[size].ActivityState=3
hot[81].ActivityState=3;cold[81].QueueLiftId=id(2) -- ordinary chairlift
local function array(rows,is_hot)
 return setmetatable({GetArrayNum=function()return not is_hot and cold_size or size end,ForEach=function(_,callback)
  assert(is_hot);scans=scans+1
  for i=1,size do local row=rows[i];callback(i,{get=function()return row end})end
 end},{__index=function(_,i)
  assert(type(i)=='number'and i>=1 and i<=(not is_hot and cold_size or size),'Out-of-range UE4SS access would grow the native array')
  reads=reads+1;return rows[i]
 end})
end
local guests={GuestsHot=array(hot,true),Guests=array(cold,false)}
local state={items={{id=key(1),definition={kind='detachable_platter'}},{id=key(2),definition={kind='fixed_chair'}}}}
local started=os.clock()
for frame=0,119 do
 hot[1].WorldPosition.X=frame*11
 local rows=Riders.read(state,guests,frame/120)[key(1)]
 assert(#rows==3)
 local found=false
 for _,r in ipairs(rows)do if r.key==key(100)then close(r.X,frame*11);found=true end end
 assert(found,'Passenger position froze between discovery scans')
end
local elapsed=os.clock()-started
assert(scans==4,'Guest discovery ran at render frequency')
assert(reads<1000,'Unrelated guests were read between discovery scans')
-- Reordering and shrinking must never pose another guest under an old GUID.
hot[1],hot[2]=hot[2],hot[1];cold[1],cold[2]=cold[2],cold[1]
local rows=Riders.read(state,guests,1.001)[key(1)]
-- This timestamp triggers discovery, so the moved rider is found immediately.
assert(#rows==3)
hot[2],hot[3]=hot[3],hot[2];cold[2],cold[3]=cold[3],cold[2]
rows=Riders.read(state,guests,1.01)[key(1)];assert(#rows==2 and not state.rider_scan)
rows=Riders.read(state,guests,1.02)[key(1)];assert(#rows==3)
size=2
rows=Riders.read(state,guests,1.03)[key(1)];assert(not rows)
size=10000;Riders.read(state,guests,1.04)
hot[3].ActivityState=4
rows=Riders.read(state,guests,1.05)[key(1)];assert(#rows==2)
cold_size=2;state.rider_scan=nil
assert(not Riders.read(state,guests,1.06)[key(1)],'Unequal hot/cold arrays caused an unsafe read')
print(string.format('10,000 guests at 120 frames: four discovery scans, %d indexed reads in %.3f s; live positions, reorder and removal OK',reads,elapsed))

-- The carrier can be more than 80 cm from the current simulation position
-- when its ISM updates on another tick. Association follows guest identity.
local Cycle=require('surface_lift_cycle')
local rail={length=2000,points={{x=0,y=0,z=600,s=0},{x=2000,y=0,z=600,s=2000}}}
local projections=0
local spline={FindInputKeyClosestToWorldLocation=function(_,p)projections=projections+1;return p.X end,
 GetDistanceAlongSplineAtSplineInputKey=function(_,key)return key end}
local binding={definition=definition,route=route,rail=rail,cycle=Cycle.create(10,rail,1500),
 native_phase=0,native_length=240000,return_entry=239000,
 lift={CableSpline=spline,ChairISM={GetInstanceCount=function()return 10 end},CableComp={SkiEOTowBoard=490}}}
local rider={X=30000,Y=160,Z=3000,key='on-line'}
Riders.bind(binding,{rider})
local pole=Cycle.guest(binding.cycle,rider.key);assert(pole and not pole.launching)
local index=pole.index;assert(binding.passengers[index]==rider)
rider.X=rider.X+1000;binding.native_phase=14000
Riders.bind(binding,{rider})
assert(binding.passengers[index]==rider and pole.index==index and projections==1)
close(rider.distance,G.nearest(route,rider.X,rider.Y))
Riders.bind(binding,{})
assert(not next(binding.passengers)and not Cycle.guest(binding.cycle,rider.key))
print('Delayed uphill discovery recovers the hanger; native phase skew keeps the same guest and live towing position OK')

local Wheels=require('surface_lift_wheels');local changes={0,0}
local function wheel(i,x)
 return{base={Translation={X=x,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}},radius=80,travel=0,
 component={K2_SetWorldTransform=function()changes[i]=changes[i]+1 end}}
end
local wheels={wheels={wheel(1,0),wheel(2,40000)}}
Wheels.update(wheels,0,100000,0,300,false,{x=0,y=0,z=0})
Wheels.update(wheels,30,100000,.1,300,false,{x=0,y=0,z=0})
assert(changes[1]==1 and changes[2]==0)
Wheels.update(wheels,60,100000,.2,300,false,{x=40000,y=0,z=0})
assert(changes[1]==1 and changes[2]==1 and wheels.cable_travel==60)
Wheels.update(wheels,60,100000,.3,300,true,{x=40000,y=0,z=0})
assert(changes[2]==1)
Wheels.update(wheels,60,100000,.4,300,true,{x=0,y=0,z=0})
assert(changes[1]==2 and wheels.wheels[1].travel==60,'Paused camera cut left a culled wheel at its old phase')
print('Distant/stopped wheels avoid Unreal transform calls while retaining absolute cable travel OK')

-- Exercise the real capture scheduler with reflected/native calls replaced.
-- Rapid camera movement must not bypass the 2 Hz limit or allocate a second
-- wide view; distant crowd riders must not cause any capture.
local captures,readbacks,targets,releases=0,0,0,0
local rt={IsValid=function()return true end,GetAddress=function()return 4 end,
 GetClass=function()return{GetAddress=function()return 5 end}end}
local component={}
for _,name in ipairs({'ClearShowOnlyComponents','ShowOnlyComponent','K2_SetWorldLocationAndRotation'})do component[name]=function()end end
function component:CaptureScene()captures=captures+1 end
local destroyed=false
local actor={AddComponentByClass=function()return component end,K2_DestroyActor=function()destroyed=true end}
local fields={WorldContextObject={0,'ObjectProperty'},TextureRenderTarget={8,'ObjectProperty'},
 MinX={16,'IntProperty'},MinY={20,'IntProperty'},MaxX={24,'IntProperty'},MaxY={28,'IntProperty'},
 bNormalize={32,'BoolProperty'},ReturnValue={40,'ArrayProperty'}}
local function property(name,field)
 return{GetFName=function()return{ToString=function()return name end}end,
 GetOffset_Internal=function()return field[1]end,
 GetClass=function()return{GetFName=function()return{ToString=function()return field[2]end}end}end}
end
local reader={ForEachProperty=function(_,fn)for name,field in pairs(fields)do fn(property(name,field))end end,
 GetAddress=function()return 6 end,GetClass=function()return{GetAddress=function()return 7 end}end}
local library={GetAddress=function()return 2 end,GetClass=function()return{GetAddress=function()return 3 end}end,
 CreateRenderTarget2D=function(_,_,w,h)targets=targets+1;assert(w==128 and h==128);return rt end,
 ReleaseRenderTarget2D=function()releases=releases+1 end}
package.loaded.portable_mesh={actor=function()return actor end,transform=function()return{}end,load=function(path)
 if path:find('ReadRenderTargetRawPixelArea',1,true)then return reader end
 if path:find('Default__KismetRenderingLibrary',1,true)then return library end
 return {}
end}
package.loaded.UEHelpers={GetWorld=function()return{GetAddress=function()return 1 end}end}
package.loaded.terrain={component={},snow_component={},active={}}
local original_open,original_loadlib=io.open,package.loadlib
local memory={};local directory
io.open=function(path,mode)
 if mode=='wb'then return{write=function(_,s)memory[path]=s end,close=function()end}end
 return{read=function()return assert(memory[path])end,close=function()end}
end
package.loadlib=function(path,symbol)
 assert(symbol=='skieo_surface_contact');directory=path:match('^(.*[/\\])')
 return function()
  readbacks=readbacks+1
  local magic,version,side=string.unpack('<c4I4I4',memory[directory..'surface-contact.job'])
  assert(magic=='SKSC'and version==1 and side==128)
  memory[directory..'surface-contact.bin']=string.rep(string.pack('<f',30000),side*side)
 end
end
local Contact=require('surface_lift_contact');local contact={}
Contact.update(contact,{x=0,y=0},{{{X=7000,Y=0,Z=50,discipline=0}}},0,false)
assert(targets==0,'Distant rider allocated a capture')
for frame=0,180 do
 local now=frame/120;local x=now*100000
 Contact.update(contact,{x=x,y=0},{{{X=x,Y=0,Z=50,discipline=0}}},now,false)
end
assert(targets==1 and captures<=3 and readbacks<=3,'Camera movement bypassed capture/readback budget')
local view=contact.contact[1]
assert(view.bytes and #view.bytes==128*128*4)
close(Contact.sample(contact,view.eye.X,view.eye.Y),50)
local before=captures
Contact.update(contact,{x=view.eye.X,y=0},{{{X=view.eye.X,Y=0,Z=50,discipline=0}}},10,true)
Contact.update(contact,{x=view.eye.X,y=0},{{{X=view.eye.X,Y=0,Z=50,discipline=0}}},11,true)
assert(captures==before,'Paused stationary scene kept capturing')
Contact.dispose(contact)
assert(destroyed and releases==1 and not contact.contact and component.TextureTarget==nil)
io.open,package.loadlib=original_open,original_loadlib
print('One 128-square contact view: bounded readback during camera cuts, distant LOD, pause and cleanup OK')
