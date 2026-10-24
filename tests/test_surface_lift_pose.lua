package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local P=require('surface_lift_pose_math');local G=require('surface_lift_geometry')
local function close(a,b,tolerance)assert(math.abs(a-b)<(tolerance or 1e-6),a..' differs from '..b)end
-- The native equipped mesh has a sole below its skeletal origin. Test slopes,
-- cross slopes and compressed tracks at several snow depths and world yaws.
local bones={
 {hip={X=-3.73,Y=-17.14,Z=113.45},knee={X=2.14,Y=-22.01,Z=66.05},foot={X=-2.23,Y=-28.75,Z=18.65}},
 {hip={X=-3.73,Y=14.96,Z=113.45},knee={X=.61,Y=21.25,Z=66.05},foot={X=-2.28,Y=28.77,Z=18.65}},
}
for _,yaw in ipairs({0,.7,2,-2.5})do for _,grade in ipairs({-.35,0,.15,.45})do for _,depth in ipairs({5,80,200})do
 local x,y=17000,-83000;local c,s=math.cos(yaw),math.sin(yaw)
 local function surface(wx,wy)
  local localx=(wx-x)*c+(wy-y)*s;local localy=-(wx-x)*s+(wy-y)*c
  local z=125000+localx*grade+localy*.2+depth
  return z,z
 end
 local legs={}
 for _,b in ipairs(bones)do
  local t,q,contact=P.ski_contact(b.foot,x,y,yaw,surface,-4.85)
  legs[#legs+1]={hip=b.hip,knee=b.knee,foot=b.foot,target=t,q=q,contact=contact}
 end
 local root=P.grounded_root(legs)
 for _,b in ipairs(legs)do
  local target={X=b.target.X,Y=b.target.Y,Z=b.target.Z-root}
  local knee,ankle=P.arm(b.hip,b.knee,b.foot,target,{X=1,Y=0,Z=0})
  close(P.length(P.sub(ankle,target)),0)
  close(P.length(P.sub(knee,b.hip)),P.length(P.sub(b.knee,b.hip)))
  close(P.length(P.sub(ankle,knee)),P.length(P.sub(b.foot,b.knee)))
  local sole=P.sub(ankle,P.rotate(b.q,{X=0,Y=0,Z=b.foot.Z+4.85}))
  local wx,wy=x+sole.X*c-sole.Y*s,y+sole.X*s+sole.Y*c
  close(root+sole.Z,surface(wx,wy))
 end
end end end
-- Independently synthesize a depth image of a known world-space plane.
local side,width,eye=64,3200,{X=1234,Y=-5678,Z=30000};local bytes={}
for row=0,side-1 do for col=0,side-1 do
 local x=eye.X+(.5-(row+.5)/side)*width;local y=eye.Y+((col+.5)/side-.5)*width
 bytes[#bytes+1]=string.pack('<f',eye.Z-(500+x*.1-y*.2))
end end
bytes=table.concat(bytes)
for _,xy in ipairs({{0,0},{321,-765},{-1150,420}})do local x,y=eye.X+xy[1],eye.Y+xy[2]
 close(P.depth_height(bytes,side,width,eye,x,y),500+x*.1-y*.2,.003)
end
assert(P.depth_height(bytes,side,width,eye,eye.X+width,eye.Y)==nil)
-- The wrist may slide along a strongly inclined shaft instead of dropping
-- the grip at an unreachable fixed height. The chosen point stays on it.
for _,angle in ipairs({0,.3,.6,.9})do
 local a={X=140*math.sin(angle)-15,Y=3,Z=230}
 local b={X=-25,Y=3,Z=112}
 local shoulder={X=-7,Y=29,Z=182};local reach=72
 local grip=P.shaft_grip(a,b,shoulder,reach,150)
 close(P.length(P.cross(P.sub(grip,a),P.sub(b,a))),0,1e-5)
 assert(P.length(P.sub(grip,shoulder))<=reach+.0001)
 local _,hand=P.arm(shoulder,{X=-17,Y=38,Z=148},{X=-6,Y=42,Z=114},grip,{X=0,Y=1,Z=0})
 close(P.length(P.sub(hand,grip)),0)
end
-- Changing extension preserves the rigid sleeve, disc and underside contact.
for _,yaw in ipairs({0,1.2,-2})do for _,height in ipairs({400,600,1000})do
 local seat={X=10,Y=20,Z=90};local clamp={x=seat.X+180*math.cos(yaw),y=seat.Y+180*math.sin(yaw),z=height}
 local t,length,parts=G.towing_parts(clamp,seat,yaw,60)
 local disc=P.point(parts.lower,{X=-60,Y=0,Z=0})
 close(P.length(P.sub(disc,seat)),0)
 for _,part in ipairs({parts.upper,parts.lower})do close(part.Scale3D.Z,1)end
 local shaft_end=P.point(parts.shaft,{X=-12,Y=0,Z=-1})
 close(P.length(P.sub(shaft_end,P.point(parts.lower,{X=-12,Y=0,Z=173}))),0)
 local shaft_axis=P.rotate(t.Rotation,{X=0,Y=0,Z=1})
 local disc_normal=P.rotate(parts.lower.Rotation,{X=0,Y=0,Z=1})
 close(P.dot(shaft_axis,disc_normal),1)
 close(P.dot(shaft_axis,P.rotate(parts.lower.Rotation,{X=1,Y=0,Z=0})),0)
 local released=G.release_length(length,.1);assert(released>=295 and released<length)
 close(G.release_length(released,0),released)
end end
print('Grounded native skis, leg lengths, rendered depth sampling and telescopic rigid parts OK')
-- A snowboard is one rigid board: both bindings and the underside share the
-- same pitched plane even though the rider's torso faces sideways.
for _,grade in ipairs({-.2,0,.25,.5})do for _,yaw in ipairs({0,.8,-2})do
 local x,y=3000,-7000;local c,s=math.cos(yaw),math.sin(yaw)
 local function surface(wx,wy)return 12000+((wx-x)*c+(wy-y)*s)*grade end
 local z,q=P.board_frame(x,y,yaw,surface,-3.803546)
 local a=P.rotate(q,{X=37.414,Y=-2.180,Z=18.638})
 local b=P.rotate(q,{X=-39.885,Y=-2.162,Z=18.665})
 close(P.length(P.sub(a,b)),P.length({X=37.414+39.885,Y=-.018,Z=-.027}))
 for _,along in ipairs({-100,-39.885,0,37.414,100})do
  local v=P.rotate(q,{X=along,Y=0,Z=-3.803546})
  close(z+v.Z,surface(x+c*v.X-s*v.Y,y+s*v.X+c*v.Y))
 end
end end
print('Rigid native snowboard bindings and sole plane follow the piste OK')
