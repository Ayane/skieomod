package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local A,G,J=require('animated_mesh'),require('animated_ground'),require('json')
local function read(p)local f=assert(io.open(p,'rb'));local b=f:read('*a');f:close();return b end
local model=A.decode(read('mod/SkiEO-Foxes/Assets/fox.skan'))
local bytes=read('mod/SkiEO-Foxes/Assets/fox-ground.json');local rig=G.decode(bytes,model)
local function surface(dx,dy,fresh)
    return function(x,y)return {inside=true,z=200+x*dx+y*dy,ground=x*dx+y*dy,snow_cm=100+(fresh or 0),fresh_cm=fresh or 0}end
end
local function pose(clip,time,x,y,jump,yaw,env,state,emit)
    local vv,nn=A.sample(model,1,clip,time)
    local z,pitch,contacts=G.solve(rig,vv,nn,clip,time,x,y,jump,yaw,env,state,emit)
    local axes=G.axes(yaw,pitch)
    return vv,z,pitch,contacts,axes,nn
end
-- Test the actual soles, not a bounding box or an assumed model origin.
for _,slope in ipairs({{0,0},{.5,0},{-.5,0},{0,.5},{-.3,.2}}) do
    for _,yaw in ipairs({0,45,90,180}) do
        local env=surface(slope[1],slope[2])
        local vv,z,pitch,_,axes,nn=pose('idle',0,100,200,0,yaw,env,{},false)
        local expected=math.atan(slope[1]*math.cos(yaw*math.pi/180)+slope[2]*math.sin(yaw*math.pi/180))*180/math.pi
        assert(math.abs(pitch-expected)<.001,'torso does not follow the longitudinal slope')
        for _,paw in ipairs(rig.paws) do
            local gap=math.huge
            for _,i in ipairs(paw.sole) do
                local q=G.rotate(axes,vv[i]);q.X=q.X+100;q.Y=q.Y+200;q.Z=q.Z+z
                gap=math.min(gap,q.Z-env(q.X,q.Y).z)
            end
            assert(math.abs(gap)<.001,'actual paw sole floats or clips into compact snow: '..gap)
        end
        for _,n in ipairs(nn) do assert(math.abs(n.X*n.X+n.Y*n.Y+n.Z*n.Z-1)<1e-5,'IK normal lost normalization') end
    end
end
local _,packed=pose('idle',0,0,0,0,0,surface(0,0),{},false)
local vv,fresh=pose('idle',0,0,0,0,0,surface(0,0,20),{},false)
assert(math.abs(packed-fresh-17)<.001,'fresh powder penetration ignored or compact snow compressed')
local state={};local env=surface(0,0);local prints=0;local planted={}
for frame=0,90 do
    local t=frame/60;local x=rig.clips.walk.stride*t
    local vertices,z,pitch,contacts,axes=pose('walk',t,x,0,0,0,env,state,frame>0)
    prints=prints+#contacts
    for i,paw in ipairs(rig.paws) do
        if state[i].stance then
            local center={X=0,Y=0,Z=0}
            for _,j in ipairs(paw.sole) do local q=G.rotate(axes,vertices[j]);center.X=center.X+q.X+x;center.Y=center.Y+q.Y end
            center.X=center.X/#paw.sole;center.Y=center.Y/#paw.sole
            local old=planted[i]
            if old then assert(math.abs(center.X-old.X)+math.abs(center.Y-old.Y)<.01,'planted paw slides during stance') end
            planted[i]=center
        else planted[i]=nil end
    end
    for _,c in ipairs(contacts) do
        assert(#c.profile.triangles>=140,'paw print no longer uses the model sole profile')
        local min,max=math.huge,-math.huge
        for _,p in ipairs(c.profile.vertices) do min=math.min(min,p.X);max=math.max(max,p.X) end
        assert(max-min>6 and max-min<8,'paw print scale differs from fox model')
    end
end
assert(prints>=5 and prints<=7,'contacts are not tied to four gait cycles: '..prints)
local _,_,_,contacts=pose('bound',.1,0,0,18,0,env,{},true)
assert(#contacts==0,'airborne paws left tracks')
-- Drive the real AI and geometry together: deep-snow bounds must actually
-- clear the fresh surface and still have a finite landing/contact phase.
package.path='mod/SkiEO-Foxes/Scripts/?.lua;'..package.path
local F=require('behaviour');local config=F.config({count=1})
config.gaits=rig.clips;config.leg_height_cm=rig.leg_height_cm
local fox_state=F.new(config,{});local fox=fox_state.foxes[1]
fox.x,fox.y,fox.yaw,fox.mode,fox.clip,fox.gait_clip,fox.anim_time=0,0,0,'roam','bound','bound',0
fox.target={x=2000,y=0};local powder=surface(0,0,60)
state={};local cleared,landings=false,0
for frame=1,160 do
    F.step(fox_state,config,1/30,{hour=12},powder)
    local vv,z,_,hits,axes=pose(fox.clip,fox.anim_time,fox.x,fox.y,fox.jump,fox.yaw,powder,state,frame>1)
    landings=landings+#hits
    local lowest=math.huge
    for _,p in ipairs(rig.paws) do for _,i in ipairs(p.sole) do local q=G.rotate(axes,vv[i]);lowest=math.min(lowest,q.Z+z) end end
    cleared=cleared or lowest>200
    if fox.jump>.1 then assert(#hits==0,'flight emitted a contact without landing') end
end
assert(cleared and landings>=8,'powder bounds never cleared the surface or never landed')
local raw=J.decode(bytes);raw.paws[1].sole[1]=99999
assert(not pcall(G.decode,J.encode(raw),model),'unbounded sole accepted')
raw=J.decode(bytes);raw.paws[1].vertices[1][2]=2
assert(not pcall(G.decode,J.encode(raw),model),'invalid skin weight accepted')
-- No hidden/far leg work: baked vertices stay exactly intact while height,
-- pitch, powder penetration and model-derived contact profiles still work.
assert(G.visibility(500,surface(0,0)(0,0))==1 and G.visibility(1200,surface(0,0)(0,0))==0)
assert(G.visibility(200,surface(0,0,20)(0,0))==0,'buried paws still request IK')
local base_v,base_n=A.sample(model,1,'walk',.4)
local original={};for i,q in ipairs(base_v) do original[i]={q.X,q.Y,q.Z} end
local queries=0;local quiet_surface=surface(0,0,20)
G.solve(rig,base_v,base_n,'walk',.4,100,0,0,0,function(x,y)queries=queries+1;return quiet_surface(x,y)end,{},true,0,1/30)
assert(queries==8,'disabled adaptation still samples leg normals/anchors')
for i,q in ipairs(base_v) do local p=original[i];assert(q.X==p[1] and q.Y==p[2] and q.Z==p[3],'hidden/far baked leg was modified') end
-- Measure real model soles on either side of every stance/swing boundary.
-- No hard velocity reversal, teleport or excessive spread at close range.
for _,name in ipairs({'walk','trot'}) do
 local gait=rig.clips[name]
 for i,paw in ipairs(rig.paws) do
  local function center(t)
   local vv,z,_,_,axes=pose(name,t,gait.stride*t/gait.duration,0,0,0,surface(0,0),{},false)
   local q={X=0,Y=0,Z=0}
   for _,j in ipairs(paw.sole) do local v=G.rotate(axes,vv[j]);q.X=q.X+v.X+gait.stride*t/gait.duration;q.Y=q.Y+v.Y;q.Z=q.Z+v.Z+z end
   return {X=q.X/#paw.sole,Y=q.Y/#paw.sole,Z=q.Z/#paw.sole}
  end
  for _,boundary in ipairs({gait.stance,1}) do
   local t=(1+boundary-gait.offsets[i])*gait.duration;local eps=.0001
   local a,b,c=center(t-eps),center(t),center(t+eps)
   assert(math.abs((b.X-a.X)-(c.X-b.X))/eps<1,'paw snaps/reverses at takeoff/landing')
   assert(math.abs((b.Z-a.Z)-(c.Z-b.Z))/eps<1,'paw lift has a hard takeoff/landing')
   assert(math.abs(b.Y-paw.rest[2]*rig.paw_spacing)<.01,'paw spacing widened beyond the narrow stance')
  end
 end
end
-- The prior 24 cm replant threshold must not teleport paws during turns.
state={};local previous
for frame=0,120 do
 local t=frame/120;local yaw=t*70;local a=yaw*math.pi/180
 local x,y=36*t*math.cos(a),36*t*math.sin(a)
 local vv,z,_,_,axes=pose('walk',t,x,y,0,yaw,surface(0,0),state,false)
 local positions={}
 for i,paw in ipairs(rig.paws) do
  local q={X=0,Y=0,Z=0}
  for _,j in ipairs(paw.sole) do local v=G.rotate(axes,vv[j]);q.X=q.X+v.X+x;q.Y=q.Y+v.Y+y;q.Z=q.Z+v.Z+z end
  positions[i]={X=q.X/#paw.sole,Y=q.Y/#paw.sole,Z=q.Z/#paw.sole}
  if previous then
   local old=previous[i];local d=math.sqrt((positions[i].X-old.X)^2+(positions[i].Y-old.Y)^2+(positions[i].Z-old.Z)^2)
   assert(d<2,'turning paw teleported by '..d..' cm')
  end
 end
 previous=positions
end
print('Ground rig: real sole contact, pitch/devers, powder sinking, planted feet, model profiles, airborne collision and validation OK')
