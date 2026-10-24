-- Reuse the native seats/queues and correct their cable's direction and tower
-- passages. Static tower frames and moving rollers are separate components.
local G=require('surface_lift_geometry')
local P=require('surface_lift_pose_math')
local M=require('portable_mesh')
local W=require('surface_lift_wheels')
local Station=require('surface_lift_station')
local C={}
local function v(p)return{X=p.X,Y=p.Y,Z=p.Z}end
local function unwrap(p)local ok,x=pcall(function()return p:get()end);return ok and x or p end
local function reflected(route,p)
 local d=G.nearest(route,p.X,p.Y);local center=G.sample(route,d)
 local side=(p.X-center.x)*center.nx+(p.Y-center.y)*center.ny
 return{X=p.X-2*side*center.nx,Y=p.Y-2*side*center.ny,Z=p.Z}
end
function C.prepare(item,set_spline,Native)
 local a=item.lift;local spline=a.CableSpline
 local length=spline:GetSplineLength();local test=spline:GetLocationAtDistanceAlongSpline(length*.2,1)
 local d=G.nearest(item.route,test.X,test.Y);local center=G.sample(item.route,d)
 local flip=(test.X-center.x)*center.nx+(test.Y-center.y)*center.ny>0
 local board=v(spline:GetLocationAtDistanceAlongSpline(item.markers[2],1))
 local exit=v(spline:GetLocationAtDistanceAlongSpline(item.markers[3],1))
 item.chair_towers={}
 a.TowerMeshComponents:ForEach(function(_,value)
  local component=unwrap(value);local base=v(component:K2_GetComponentLocation());local heads={}
  for _,names in ipairs({{a.TowerCableEntranceLeftSocket,a.TowerCableExitLeftSocket},{a.TowerCableEntranceRightSocket,a.TowerCableExitRightSocket}})do
   local x,y=component:GetSocketLocation(names[1]),component:GetSocketLocation(names[2])
   heads[#heads+1]=P.scale(P.add(v(x),v(y)),.5)
  end
  item.chair_towers[#item.chair_towers+1]={base=base,heads=heads,component=component}
 end)
 local groups={};local points={}
 for _,p in ipairs(item.splines.CableSpline.points)do
  local group
  for i,t in ipairs(item.chair_towers)do for lane,h in ipairs(t.heads)do
   if (p.X-h.X)^2+(p.Y-h.Y)^2<350^2 and math.abs(p.Z-h.Z)<200 then group=i..':'..lane end
  end end
  if not group or not groups[group]then
   local q={X=p.X,Y=p.Y,Z=p.Z,type=3}
   if group then groups[group]=true
    local i,j=group:match('(%d+):(%d+)');q=v(item.chair_towers[tonumber(i)].heads[tonumber(j)]);q.type=3
   end
   if flip then local f=reflected(item.route,q);q.X,q.Y=f.X,f.Y end
   points[#points+1]=q
  end
 end
 set_spline(spline,points,true)
 if flip then
  board=reflected(item.route,board);exit=reflected(item.route,exit)
  for _,key in ipairs({'StartLoopSpline','EndLoopSpline'})do
   local out={}
   for _,p in ipairs(item.splines[key].points)do
    local q=reflected(item.route,p);q.type=p.type
    -- Mirrored custom tangents keep the native embarkation arcs continuous.
    local at=G.sample(item.route,G.nearest(item.route,p.X,p.Y))
    for _,name in ipairs({'arrive','leave'})do if p[name]then
     local t=p[name];local side=t.X*at.nx+t.Y*at.ny
     q[name]={X=t.X-2*side*at.nx,Y=t.Y-2*side*at.ny,Z=t.Z}
    end end
    out[#out+1]=q
   end
   set_spline(a[key],out,item.splines[key].closed)
  end
 end
 local function distance(p)return spline:GetDistanceAlongSplineAtSplineInputKey(spline:FindInputKeyClosestToWorldLocation(p))end
 Native.set_loop(a,distance(board),distance(exit));a:RebuildChairMeshes(item.phase or 0);a:RebuildCableMeshes()
 item.chair_mirrored=flip
end
function C.towers(item,state)
 local supports={guides={},wheels={}};local spline=item.lift.CableSpline
 for _,t in ipairs(item.chair_towers)do
  local d=G.nearest(item.route,t.base.X,t.base.Y);local at=G.sample(item.route,d)
  local height=(t.heads[1].Z+t.heads[2].Z)*.5-t.base.Z;local maximum=-math.huge
  local support={x=t.base.X,y=t.base.Y,z=t.base.Z,height=height,return_height=height}
  supports[#supports+1]=support
  for _,h in ipairs(t.heads)do
   local key=spline:FindInputKeyClosestToWorldLocation(h);local center=spline:GetDistanceAlongSplineAtSplineInputKey(key)
   local before=spline:GetLocationAtDistanceAlongSpline(center-500,1);local after=spline:GetLocationAtDistanceAlongSpline(center+500,1)
   local change=(after.Z-h.Z)-(h.Z-before.Z)
   for _,offset in ipairs({-105,-63,-21,21,63,105})do
    local distance=center+offset;local p=spline:GetLocationAtDistanceAlongSpline(distance,1)
    local a,b=spline:GetLocationAtDistanceAlongSpline(distance-1,1),spline:GetLocationAtDistanceAlongSpline(distance+1,1)
    local tangent=P.sub(v(b),v(a));local radial={X=0,Y=0,Z=change>0 and -1 or 1}
    local base=W.frame(v(p),tangent,radial,18)
    maximum=math.max(maximum,base.Translation.Z+18)
    W.add(item,state,base,18)
    supports.wheels[#supports.wheels+1]={base=base,support=#supports,lane=-160}
   end
  end
  local deck=maximum+50
  support.height=deck-t.base.Z-104;support.return_height=support.height
  M.component(item.visual,state.models.chair_tower,state.material,t.base,math.deg(at.yaw),{X=1,Y=1,Z=(deck-t.base.Z-24)/900})
  M.component(item.visual,state.models.chair_head,state.material,{X=t.base.X,Y=t.base.Y,Z=deck},math.deg(at.yaw))
 end
 M.component(item.visual,Station.mounts(item.route,supports,G),state.material,{0,0,0})
end
function C.cable_mesh(item)
 local spline=item.lift.CableSpline;local length=spline:GetSplineLength();local points={}
 local count=math.ceil(length/80)
 for i=0,count-1 do points[#points+1]=v(spline:GetLocationAtDistanceAlongSpline(length*i/count,1))end
 return G.path_mesh(points,1.4)
end
return C
