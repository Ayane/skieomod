-- Shared wheel frames. Local Z is the axle; local X is the contact radius and
-- local Y is cable travel. Radius and cable displacement determine rotation.
local P=require('surface_lift_pose_math')
local W={}
function W.frame(contact,tangent,radial,radius)
 tangent=P.unit(tangent)
 radial=P.unit(P.sub(radial,P.scale(tangent,P.dot(radial,tangent))))
 local a=P.between({X=1,Y=0,Z=0},radial)
 local q=P.mul(P.between(P.rotate(a,{X=0,Y=1,Z=0}),tangent),a)
 return {Translation=P.sub(contact,P.scale(radial,radius)),Rotation=q,Scale3D={X=radius/80,Y=radius/80,Z=1}}
end
function W.rotated(base,distance,radius,sign)
 local angle=(distance/radius*(sign or 1))%(2*math.pi)
 return {Translation=base.Translation,Rotation=P.mul(base.Rotation,{X=0,Y=0,Z=math.sin(angle/2),W=math.cos(angle/2)}),Scale3D=base.Scale3D}
end
function W.supports(route,supports,G,kind)
 local rows={}
 for i=2,#supports-1 do
  local s=supports[i]
  for _,lane in ipairs({-160,160})do if lane<0 or s.return_used then
   -- Poma platter heads use two individual pulleys: support then compression.
   -- The opposite branch has its own head on the other side of the mast.
   for _,offset in ipairs(lane<0 and {-65,65}or{0})do
    local d=s.distance+offset
    local p=G.cable(route,supports,d,lane)
    local a,b=G.cable(route,supports,d-1,lane),G.cable(route,supports,d+1,lane)
    local tangent={X=b.x-a.x,Y=b.y-a.y,Z=b.z-a.z}
    if lane>0 then tangent=P.scale(tangent,-1)end
    local radial={X=0,Y=0,Z=offset>0 and -1 or 1}
    if s.angle then
     local before,after=G.raw_cable(route,supports,s.distance-150,lane),G.raw_cable(route,supports,s.distance+150,lane)
     local bend=P.sub(P.unit({X=after.x-p.x,Y=after.y-p.y,Z=after.z-p.z}),P.unit({X=p.x-before.x,Y=p.y-before.y,Z=p.z-before.z}))
     if P.length(bend)>.01 then radial=P.scale(bend,offset>0 and 1 or -1)end
    end
    local radius=kind=='fixed_platter'and 30 or 45
    rows[#rows+1]={base=W.frame({X=p.x,Y=p.y,Z=p.z},tangent,radial,radius),radius=radius,sign=1,support=i,lane=lane,offset=offset,contact=p}
   end
  end end
 end
 return rows
end
function W.travel(previous,phase,length,seconds,speed,paused)
 if not previous then return 0 end
 local dt=seconds-previous.seconds
 if paused or dt<=0 or dt>2 or speed<=0 then return 0 end
 local delta=(phase-previous.phase)%length
 -- Rebuilt snow-following splines and native reloads are not cable rotation.
 if delta>math.max(500,speed*dt*8)then return 0 end
 return delta
end
function W.add(item,state,base,radius,sign,model)
 local Mesh=require('portable_mesh')
 local c=Mesh.component(item.visual,state.models[model or 'guide_wheel'],state.material)
 c:K2_SetWorldTransform(base,false,{},true)
 item.wheels=item.wheels or{};item.wheels[#item.wheels+1]={component=c,base=base,radius=radius,sign=sign or 1,travel=0}
 return c
end
function W.update(item,phase,length,seconds,speed,paused,camera)
 item.cable_step=W.travel(item.wheel_previous,phase,length,seconds,speed,paused)
 item.cable_travel=(item.cable_travel or 0)+item.cable_step
 item.wheel_previous={phase=phase,seconds=seconds}
 for _,w in ipairs(item.wheels or{})do
  local p=w.base.Translation
  if w.travel~=item.cable_travel and (not camera or (p.X-camera.x)^2+(p.Y-camera.y)^2+(p.Z-camera.z)^2<18000^2)then
   w.component:K2_SetWorldTransform(W.rotated(w.base,item.cable_travel,w.radius,w.sign),false,{},true)
   w.travel=item.cable_travel
  end
 end
end
return W
