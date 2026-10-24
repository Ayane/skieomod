package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local C=require('surface_lift_cycle');local Snow=require('surface_lift_snow');local G=require('surface_lift_geometry')
local function close(a,b)assert(math.abs(a-b)<1e-7,tostring(a)..' differs from '..tostring(b))end
for _,drive in ipairs({'covered','open'}) do
 local item={definition={kind='detachable_platter',drive=drive},supports={{x=0,y=0,z=0,height=500,yaw=0}}}
 local exit=C.exit(item.definition);local tail=exit-300-C.stock*C.pitch
 local x,y=C.path(0,tail);close(x,0);close(y,160)
 x,y=C.path(1,tail);close(x,tail);close(y,-160)
 -- The entering hanger fills the back; the front hanger becomes the outgoing
 -- carrier. Every other retained hanger occupies its predecessor's location.
 local front=C.position(item,{X=0,Y=-160},0,-160,0)
 x=C.queue(exit,C.stock,1);close(front.x,x)
 for j=2,C.stock do close(C.queue(exit,j-1,1),C.queue(exit,j,0)) end
 local last
 for i=0,100 do
  local p=C.position(item,{X=exit*i/100,Y=-160},exit*i/100,-160,0)
  if p then assert(not last or p.x>=last);last=p.x end
 end
 local p=C.position(item,{X=exit-.00001,Y=-160},exit-.00001,-160,0)
 assert(math.abs(p.x-exit)<.001)
 item.definition.kind='fixed_platter';assert(C.exit(item.definition)==0 and C.position(item,{X=0,Y=-160},0,-160,0)==nil)
end
-- A platter's end must touch the passenger's pelvis for arbitrary yaw and
-- cable height, not merely rotate a vertical pole alongside a moving skier.
for _,yaw in ipairs({0,.8,2.9,-2}) do for _,height in ipairs({400,600,1000}) do
 local rider={X=100,Y=200,Z=30};local clamp={x=100+180*math.cos(yaw),y=200+180*math.sin(yaw),z=height}
 local t=G.towing_transform(clamp,rider,yaw);local q=t.Rotation
 local v={X=-36,Y=0,Z=-409*t.Scale3D.Z}
 local tx=2*(q.Y*v.Z-q.Z*v.Y);local ty=2*(q.Z*v.X-q.X*v.Z);local tz=2*(q.X*v.Y-q.Y*v.X)
 close(t.Translation.X+v.X+q.W*tx+q.Y*tz-q.Z*ty,rider.X)
 close(t.Translation.Y+v.Y+q.W*ty+q.Z*tx-q.X*tz,rider.Y)
 close(t.Translation.Z+v.Z+q.W*tz+q.X*ty-q.Y*tx,rider.Z+108)
 assert(math.abs(q.X)+math.abs(q.Y)>.05)
end end
local item={route={points={}}};for i=1,401 do item.route.points[i]={x=i*200,y=0,nx=0,ny=1}end
local depth,bare,known,calls=15,201,true,0
local function sample(x,y)calls=calls+1;assert(y==-160);return{snow_ready=known,snow_cm=x==bare*200 and 0 or depth}end
local status
repeat local before=calls;status=Snow.scan(item,sample,32);assert(calls-before<=32)until status=='blocked'
assert(calls==201,'A bare middle section must stop the lift before finishing the scan')
bare=-1;local complete
repeat status,_,complete=Snow.scan(item,sample,32);assert(status~='clear')until complete
repeat status,_,complete=Snow.scan(item,sample,32)until complete
assert(status=='clear','Reopening requires a complete snow-covered scan')
depth=4;repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status=='pending')
known=false;depth=15;repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status=='pending')
-- Excess accumulation anywhere stops immediately. Reopening requires all
-- samples below a lower threshold; an unknown sample cannot clear the stop.
known=true;item.definition={kind='fixed_platter'};depth=120;bare=-1
repeat status,_,complete=Snow.scan(item,sample,32)until complete
local maximum=select(3,Snow.limits(item));assert(maximum==150)
local reason
local function drift(x,y)
 local e=sample(x,y);if x==201*200 then e.snow_cm=151 end;return e
end
repeat status,_,complete,reason=Snow.scan(item,drift,32)until status=='blocked'
assert(reason=='excess'and item.snow_scan.index==202)
repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status~='clear')
depth=140;repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status=='pending')
depth=130;repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status=='clear')
item.definition.kind='detachable_platter';depth=251
status,_,complete,reason=Snow.scan(item,sample,32);assert(status=='blocked'and reason=='excess')
depth=220;known=false;repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status=='pending')
known=true;repeat status,_,complete=Snow.scan(item,sample,32)until complete;assert(status=='clear')
print('Excess snow closes fixed and detachable lifts, with full-line hysteresis and unknown readback protection OK')
print('Detachable circulation, fixed grips, loaded platter contact and complete-route snow closure OK')
local P=require('surface_lift_pose_math')
local shoulder={X=0,Y=30,Z=180};local elbow={X=-10,Y=40,Z=145};local hand={X=0,Y=42,Z=112}
local target={X=40,Y=3,Z=150}
local e,h,uq,lq=P.arm(shoulder,elbow,hand,target,{X=0,Y=1,Z=0})
close(P.length(P.sub(shoulder,e)),P.length(P.sub(shoulder,elbow)))
close(P.length(P.sub(e,h)),P.length(P.sub(elbow,hand)))
close(P.length(P.sub(h,target)),0)
local v=P.rotate(uq,P.sub(elbow,shoulder));close(P.length(P.sub(v,P.sub(e,shoulder))),0)
print('Towing arm IK reaches the shaft without changing bone lengths OK')
-- A released hanger follows the descending guide, not a height discontinuity
-- when its native carrier crosses from the return lane to the departure lane.
local high={definition={kind='detachable_platter',drive='covered'},route={length=10000},supports={
 {x=0,y=0,z=1000,height=600,return_height=900,yaw=0},
 {x=10000,y=0,z=3000,height=600,return_height=900,yaw=0}}}
local previous
for i=1,999 do
 local a=math.pi*i/1000
 local p=C.position(high,{X=-160*math.sin(a),Y=160*math.cos(a)},0,i<500 and 160 or -160,0)
 assert(p and p.z>=1590 and p.z<=1890)
 if previous then assert(math.abs(p.z-previous.z)<1)end;previous=p
end
close(G.station_guide(high.supports[1],0,520).z,1890)
close(G.station_guide(high.supports[1],math.pi,520).z,1590)
print('High return hangers descend continuously through the inclined station guide OK')
-- A detachable stock does not move or dispatch merely because an empty native
-- carrier passes. Every pole retains identity and returns at the back of FIFO.
local rail={length=2000,points={{x=0,y=0,z=900,s=0},{x=2000,y=0,z=600,s=2000}}}
local s=C.create(20,rail,1500);local count=#s.poles
for i=1,100 do C.advance(s,rail,10)end
assert(s.dispatches==0 and s.returns==0 and #s.poles==count)
local p=assert(C.dispatch(s,rail,3,'guest-a'));local id=p.id
assert(not C.dispatch(s,rail,4,'guest-b'),'Two guests dispatched without minimum separation')
C.advance(s,rail,1499);assert(not C.dispatch(s,rail,4,'guest-b'))
C.advance(s,rail,1);assert(C.dispatch(s,rail,4,'guest-b'))
local target={x=2300,y=0,z=600};local before=p.anchor.x
local anchor=C.anchor(p,target,p.launch_travel+10);assert(anchor.x>before and anchor.x-before<=20.001,'Departure did not advance continuously from stock')
local arrived=assert(C.arrive(s,3,0));assert(arrived.id==id and arrived.state=='rail'and arrived.order==s.order)
local at=C.at(rail,arrived.s);C.advance(s,rail,20);local next_at=C.at(rail,arrived.s)
assert(math.sqrt((at.x-next_at.x)^2+(at.y-next_at.y)^2+(at.z-next_at.z)^2)<21,'Returning pole teleported to the front')
local frozen=arrived.s;C.advance(s,rail,0);assert(arrived.s==frozen)
assert(#s.poles==count and s.dispatches==2 and s.returns==1)
local W=require('surface_lift_wheels')
local base={Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}}
local t=W.rotated(base,math.pi*80/2,80)
assert(P.length(P.sub(P.rotate(t.Rotation,{X=1,Y=0,Z=0}),{X=0,Y=1,Z=0}))<1e-7,'Wheel peripheral speed differs from cable speed')
assert(W.travel({phase=990,seconds=0},10,1000,.1,200,false)==20)
assert(W.travel({phase=990,seconds=0},10,1000,.1,200,true)==0)
assert(W.travel({phase=990,seconds=0},10,1000,.1,0,false)==0)
print('Conserved detachable FIFO, guest-only dispatch, safe spacing, continuous return and wheel peripheral speed OK')
local saved=C.create(124,rail,1500)
for i=1,120 do
 C.advance(saved,rail,1500)
 assert(C.dispatch(saved,rail,i,string.format('%08x-%08x-%08x-%08x',i,0x12345678,0,1),false,1500))
end
local encoded=C.encode(saved);local restored=C.decode(encoded,rail,1500)
assert(C.encode(restored)==encoded,'Hanger identities, guests and FIFO order changed on restore')
assert(#encoded*6<27000,'All six detachable lifts exceed the state budget')
assert(not pcall(C.decode,encoded:sub(1,-3),rail,1500),'Truncated retained stock accepted')
assert(not pcall(C.decode,encoded..'AAAA',rail,1500),'Trailing hanger bytes accepted')
print('Compact retained hanger state roundtrips inside the 32 KiB map state limit')
local negative_guid=string.format('%08x-%08x-%08x-%08x',-1,-2,123,0)
local signed=C.create(4,rail,1500);assert(C.dispatch(signed,rail,0,negative_guid,false,1500))
assert(C.guest(C.decode(C.encode(signed),rail,1500),negative_guid),'Signed UE guest GUID was changed by serialization')
-- A camera cut must produce the same launch position as rendering every tick.
-- The absolute cable clock includes all travel while the hanger was culled.
local seen,culled=C.create(4,rail,1500),C.create(4,rail,1500)
C.advance(seen,rail,12000);C.advance(culled,rail,12000)
local a=C.dispatch(seen,rail,0,'rider');local b=C.dispatch(culled,rail,0,'rider')
local actual,target
for _=1,100 do
 C.advance(seen,rail,10);C.advance(culled,rail,10)
 target={x=5000+(seen.travel-12000),y=0,z=600}
 actual=C.anchor(a,target,seen.travel)
end
local recovered=C.anchor(b,target,culled.travel)
close(actual.x,recovered.x);close(actual.y,recovered.y);close(actual.z,recovered.z)
local repeated=C.anchor(b,target,culled.travel);close(repeated.x,recovered.x)
assert(recovered.x>3000,'Off-screen hanger lost its launch travel')
-- Native simulation/ISM phase disagreement must not move the same rider to
-- another hanger. A delayed launch must still pull in front of its rider.
assert(C.dispatch(seen,rail,2,'rider')==a and a.index==0)
assert(C.carrier(seen,0)==a and not C.carrier(seen,2))
local seat={X=5500,Y=0,Z=100}
local lead=C.anchor(b,target,culled.travel,seat,0)
assert(lead.x-seat.X>=60 and not b.launching,'Skier dragged the departing pole behind them')
C.release(seen,a);assert(not C.guest(seen,'rider'))
C.arrive(seen,0);assert(not C.carrier(seen,0))
print('Off-screen launch travel, stable passenger/carrier identity and forward traction OK')
