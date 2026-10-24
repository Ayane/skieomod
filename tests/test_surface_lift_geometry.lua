package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local G=require('surface_lift_geometry');local Mesh=require('portable_mesh');local json=require('json')
local function read(path)local f=assert(io.open(path,'rb'));local s=f:read('*a');f:close();return s end
local manifest=json.decode(read('mod/SkiEO-Veymont/custom-map.json'))
local terrain=manifest.terrain
local bytes=read('mod/SkiEO-Veymont/Terrain/heightmap.r16')
local function ground(x,y)
 local col=(x-terrain.origin_centimeters[1])/400;local row=(y-terrain.origin_centimeters[2])/400
 local w,h=table.unpack(terrain.source.vertices)
 if col<0 or row<0 or col>=w-1 or row>=h-1 then return nil end
 local c,r=math.floor(col),math.floor(row);local u,v=col-c,row-r
 local function z(xx,yy)return string.unpack('<I2',bytes,1+2*(yy*w+xx))*2.5+72398.75 end
 return (z(c,r)*(1-u)+z(c+1,r)*u)*(1-v)+(z(c,r+1)*(1-u)+z(c+1,r+1)*u)*v
end
local total,worst=0,0
for _,d in ipairs(manifest.extensions['community.surface-lifts'].lifts) do
 local route=G.route(d,ground);local supports=G.supports(route,d.pylons,d.kind,d)
 -- Compare the accelerated XY projection against every original dense
 -- interval, including bends, lateral offsets and positions beyond terminals.
 for at=-500,route.length+500,731 do for _,side in ipairs({-600,0,600})do
  local p=G.sample(route,at)
  local x,y=p.x+p.nx*side+23,p.y+p.ny*side-17
  local fast,error=G.nearest(route,x,y)
  local dense,dense_error=G.nearest({points=route.points},x,y)
  assert(math.abs(fast-dense)<1e-5 and math.abs(error-dense_error)<1e-5,'Sparse projection changed the exact route distance')
 end end
 assert(#supports==d.pylons+2)
 local angle={};for i,p in ipairs(supports) do if p.angle then angle[#angle+1]=i-1 end end
 if d.name=='Pré Levé' then assert(#angle==2 and angle[1]==6 and angle[2]==9,'Pré Levé must turn at P6 and P9') end
 if d.name=='Pierre Blanche' then assert(#angle==1 and angle[1]==8,'Pierre Blanche must turn at P8') end
 local transport=G.transport(route,ground)
 for _,p in ipairs(transport) do assert(math.abs(p.Z-ground(p.X,p.Y)-3)<.001,'Tow path must stay on the surface') end
 for i=2,#transport do
  local a,b=transport[i-1],transport[i]
  worst=math.max(worst,math.abs((a.Z+b.Z)/2-ground((a.X+b.X)/2,(a.Y+b.Y)/2)-3))
 end
 for _,lane in ipairs({-160,160}) do
  for i=0,math.floor(route.length/400) do
   local p=G.cable(route,supports,i*400,lane)
   assert(p.z>ground(p.x,p.y)+380,d.name..' clearance '..(p.z-ground(p.x,p.y))..' at '..i*400)
  end
 end
 local cable=G.cable_mesh(route,supports)
 for _,n in ipairs(cable.triangles) do assert(n>=0 and n<#cable.vertices) end
 local P=require('surface_lift_pose_math');local Station=require('surface_lift_station')
 for terminal,group in ipairs(supports.guides)do for lane,g in pairs(group)do
  for n=0,16 do
   local angle=g.theta*n/16;local point=Station.arc(g,angle)
   local on_wheel=P.point(g.transform,{X=80*math.sin(angle),Y=-80*math.cos(angle),Z=0})
   assert(P.length(P.sub(point,on_wheel))<1e-6,'Guide cable missed the wheel groove')
  end
  local contact=G.cable(route,supports,g.distance,lane)
  assert(P.length(P.sub({X=contact.x,Y=contact.y,Z=contact.z},g.tangent))<.001,'Guide arc did not join the line')
  local next_point=G.cable(route,supports,g.distance+(terminal==1 and .01 or -.01),lane)
  local line=P.unit(P.sub({X=next_point.x,Y=next_point.y,Z=next_point.z},g.tangent))
  local tangent=P.add(P.scale(g.direction,math.cos(g.theta)),P.scale(g.up,math.sin(g.theta)))
  assert(P.dot(line,tangent)>.999999,'Cable enters a guide wheel obliquely')
 end end
 local W=require('surface_lift_wheels')
 local wheels=W.supports(route,supports,G,d.kind)
 for _,w in ipairs(wheels)do
  local contact=P.point(w.base,{X=80,Y=0,Z=0})
  assert(P.length(P.sub(contact,{X=w.contact.x,Y=w.contact.y,Z=w.contact.z}))<1e-5,'Cable misses pulley groove')
  local a=G.cable(route,supports,supports[w.support].distance+w.offset-.01,w.lane)
  local b=G.cable(route,supports,supports[w.support].distance+w.offset+.01,w.lane)
  local tangent=P.unit({X=b.x-a.x,Y=b.y-a.y,Z=b.z-a.z})
  if w.lane>0 then tangent=P.scale(tangent,-1)end
  assert(P.dot(P.rotate(w.base.Rotation,{X=0,Y=1,Z=0}),tangent)>.99999,'Inclined wheel does not follow cable tangent')
  if not supports[w.support].angle then
   assert(math.abs(P.rotate(w.base.Rotation,{X=0,Y=0,Z=1}).Z)<1e-5,'Ordinary pylon pulley plane must remain vertical')
  end
 end
 for _,support in ipairs(supports)do
  local side=(support.nx*-160)*(-math.sin(support.yaw))+(support.ny*-160)*math.cos(support.yaw)
  assert(side*(d.ascent_side=='right'and 1 or -1)>0,'Ascent differs from UE +Y right vector')
 end
 for _,s in ipairs({supports[1],supports[#supports]})do
  local base=G.wheel_transform(s);local radius=200*base.Scale3D.X
  local contact={X=0,Y=-200*route.mirror,Z=0}
  local before=P.point(base,contact);local after=P.point(W.rotated(base,.1,radius,route.mirror),contact)
  local motion=P.scale(P.sub(after,before),10)
  assert(P.dot(motion,{X=math.cos(s.yaw),Y=math.sin(s.yaw),Z=0})>.9999,'Drive wheel runs against uphill cable')
 end
 if d.kind=='fixed_platter' then
  for _,snow in ipairs({3,100,200,300})do for at=1000,route.length-1000,200 do
   local p=G.sample(route,at);local x,y=p.x-p.nx*160,p.y-p.ny*160
   local seat={X=x-math.cos(p.yaw)*42,Y=y-math.sin(p.yaw)*42,Z=ground(x,y)+snow+18+88}
   local clamp=assert(G.fixed_clamp(route,supports,at,-160,seat),d.name..' fixed rod cannot reach at '..at)
   if clamp.sag then
    local p=G.flex_cable(route,supports,clamp.distance,-160,{clamp})
    assert(math.abs(p.z-clamp.z)<.001,'Loaded clamp left the flexible cable')
    for _,support in ipairs(supports)do
     local a=G.cable(route,supports,support.distance,-160)
     local b=G.flex_cable(route,supports,support.distance,-160,{clamp})
     assert(a.z==b.z,'Cable flex moved a support')
    end
   end
   local yaw=math.atan(clamp.y-seat.Y,clamp.x-seat.X)
   local t,length=G.towing_parts(clamp,seat,yaw,60)
   assert(math.abs(length-300)<.001 and t.Scale3D.Z==1,'A fixed pole must never telescope')
  end end
 else
  for _,snow in ipairs({3,120,300})do for at=1000,route.length-1000,1000 do
   local p=G.sample(route,at);local x,y=p.x-p.nx*160,p.y-p.ny*160
   local seat={X=x-math.cos(p.yaw)*22,Y=y-math.sin(p.yaw)*22,Z=ground(x,y)+snow+87}
   local clamp=G.detachable_clamp(route,supports,at,-160,seat)
   local t,length=G.towing_parts(clamp,seat,math.atan(clamp.y-seat.Y,clamp.x-seat.X),60)
   assert(length>=295 and length<1400,'TKD spring outside its modelled travel')
   local axis=P.rotate(t.Rotation,{X=0,Y=0,Z=1})
   assert(axis.Z<=math.cos(math.rad(25))+.001,'Occupied TKD does not lean into traction')
  end end
 end
 total=total+1
end
assert(total==8)
assert(worst<20,'Towing path cuts too far across terrain bends: '..worst)
for _,name in ipairs({'platter','platter-upper','platter-shaft','platter-lower','poles-bundle','tower','angle-tower','poma-drive','pre-leve-drive','floating-return','release-return',
 'motor','chair-tower','chair-head','guide-wheel','return-support','return-angle','fixed-return-support','inclined-wheel','fixed-drive','pras-drive','lattice-return','blanchon-drive','blanchon-return'}) do
 local bytes=read('mod/SkiEO-SurfaceLifts/Assets/'..name..'.skpm');local m=Mesh.decode(bytes)
 assert(#m.vertices>0 and #m.triangles%3==0)
 assert(not pcall(Mesh.decode,bytes:sub(1,-2)),'Truncated meshes must fail')
 assert(not pcall(Mesh.decode,bytes..'x'),'Trailing bytes must fail')
end
local d={name='bad',route={{0,0,0},{0/0,100,0}},speed_mps=3,capacity_per_hour=720,kind='detachable_platter',pylons=3}
assert(not pcall(G.validate,d),'NaN coordinates must fail')
d.route={{0,0,0},{9000000,0,0}}
local calls=0
assert(not pcall(G.route,d,function() calls=calls+1;return 0 end),'Oversized routes must fail before sampling')
assert(calls==2,'Invalid route allocated unbounded terrain samples')
print('Eight Veymont lifts: surveyed bends, surface contact, rigid TKF reach and twenty-four Blender models OK')
-- The unloaded return bridges a hollow; its high terminal cannot be connected
-- to the departure by a flat circle. Test independent geometry, including a
-- bend which must retain its return sheave despite being below the chord.
local function supports(angle)
 local s={}
 for i,z in ipairs({0,-300,0,-250,0})do s[i]={x=(i-1)*2000,y=0,z=z,height=600,nx=0,ny=1,yaw=0,distance=(i-1)*2000,angle=i==4 and angle}end
 G.return_supports(s,'detachable_platter');return s
end
local s=supports(true);assert(not s[2].return_used and s[4].return_used)
assert(s[1].return_height==900 and s[5].return_height==600)
local P=require('surface_lift_pose_math')
for _,p in ipairs(s)do
 local t=G.wheel_transform(p)
 for _,angle in ipairs({-math.pi/2,0,math.pi/2,math.pi})do
  local world=P.point(t,{X=200*math.cos(angle),Y=200*math.sin(angle)*(p.mirror or 1),Z=0})
  local expected=G.wheel(p,angle)
  assert(P.length(P.sub(world,{X=expected.x,Y=expected.y,Z=expected.z}))<1e-6,'Wheel and cable disagree')
 end
 local empty=G.empty_perch({x=p.x,y=p.y,z=p.z+900},.7,295,100000)
 local down=P.rotate(empty.Rotation,{X=0,Y=0,Z=-295})
 assert(math.abs(down.X)<1e-8 and math.abs(down.Y)<1e-8 and down.Z==-295,'Empty perch tilted')
end
print('Independent high return, bypassed low support, retained bend and circular inclined wheels OK')
-- Both paired lines face the piste: ascent spacing is smaller than mast-axis
-- spacing, while the unloaded return branches lie outside both masts.
local definitions=manifest.extensions['community.surface-lifts'].lifts;local byname={}
for _,d in ipairs(definitions)do byname[d.name]=d end
for _,pair in ipairs({{'Pras 1','Pras 2'},{'Bessards 1','Bessards 2'}})do
 local a,b=G.route(byname[pair[1]],ground),G.route(byname[pair[2]],ground)
 local x,y=a.points[1],b.points[1]
 local function gap(lane)return math.sqrt((x.x+x.nx*lane-y.x-y.nx*lane)^2+(x.y+x.ny*lane-y.y-y.ny*lane)^2)end
 local axes=math.sqrt((x.x-y.x)^2+(x.y-y.y)^2)
 assert(gap(-160)<axes and gap(160)>axes,'Paired lift return is inside the uphill tracks')
end
for name,side in pairs({['Pré Levé']='left',Blavet='left',Alleyrons='left',['Pierre Blanche']='right',
 ['Pras 1']='right',['Pras 2']='left',['Bessards 1']='right',['Bessards 2']='left'})do assert(byname[name].ascent_side==side)end
print('Mirrored paired ascents and all user-specified single-line directions OK')
