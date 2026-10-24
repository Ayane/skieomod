local P={}
function P.add(a,b)return{X=a.X+b.X,Y=a.Y+b.Y,Z=a.Z+b.Z}end
function P.sub(a,b)return{X=a.X-b.X,Y=a.Y-b.Y,Z=a.Z-b.Z}end
function P.scale(a,k)return{X=a.X*k,Y=a.Y*k,Z=a.Z*k}end
function P.dot(a,b)return a.X*b.X+a.Y*b.Y+a.Z*b.Z end
function P.length(a)return math.sqrt(P.dot(a,a))end
function P.unit(a)local n=P.length(a);assert(n>1e-8,'Degenerate pose vector');return P.scale(a,1/n)end
function P.cross(a,b)return{X=a.Y*b.Z-a.Z*b.Y,Y=a.Z*b.X-a.X*b.Z,Z=a.X*b.Y-a.Y*b.X}end
function P.mul(a,b)return{X=a.W*b.X+a.X*b.W+a.Y*b.Z-a.Z*b.Y,Y=a.W*b.Y-a.X*b.Z+a.Y*b.W+a.Z*b.X,Z=a.W*b.Z+a.X*b.Y-a.Y*b.X+a.Z*b.W,W=a.W*b.W-a.X*b.X-a.Y*b.Y-a.Z*b.Z}end
function P.rotate(q,v)
 local t=P.scale(P.cross(q,v),2)
 return P.add(v,P.add(P.scale(t,q.W),P.cross(q,t)))
end
function P.between(a,b)
 a=P.unit(a);b=P.unit(b);local c=P.cross(a,b);local w=1+P.dot(a,b)
 if w<1e-7 then c=P.cross(a,math.abs(a.Z)<.9 and {X=0,Y=0,Z=1} or {X=1,Y=0,Z=0});w=0 end
 local n=math.sqrt(P.dot(c,c)+w*w);return{X=c.X/n,Y=c.Y/n,Z=c.Z/n,W=w/n}
end
function P.arm(shoulder,elbow,hand,target,bend)
 local l1,l2=P.length(P.sub(elbow,shoulder)),P.length(P.sub(hand,elbow))
 local v=P.sub(target,shoulder);local d=P.length(v);local dir=P.unit(v)
 d=math.max(math.abs(l1-l2)+.001,math.min(l1+l2-.001,d))
 target=P.add(shoulder,P.scale(dir,d))
 local side=P.unit(P.sub(bend,P.scale(dir,P.dot(bend,dir))))
 local a=(l1*l1-l2*l2+d*d)/(2*d)
 local e=P.add(shoulder,P.add(P.scale(dir,a),P.scale(side,math.sqrt(math.max(0,l1*l1-a*a)))))
 return e,target,P.between(P.sub(elbow,shoulder),P.sub(e,shoulder)),P.between(P.sub(hand,elbow),P.sub(target,e))
end
function P.point(t,p)return P.add(t.Translation,P.rotate(t.Rotation,{X=p.X*t.Scale3D.X,Y=p.Y*t.Scale3D.Y,Z=p.Z*t.Scale3D.Z}))end
function P.local_point(t,p)
 local q=t.Rotation;local v=P.rotate({X=-q.X,Y=-q.Y,Z=-q.Z,W=q.W},P.sub(p,t.Translation))
 return{X=v.X/t.Scale3D.X,Y=v.Y/t.Scale3D.Y,Z=v.Z/t.Scale3D.Z}
end
-- Choose a point on the shaft that is inside the arm's reach, preferring a
-- relaxed hand height. A fixed height alone loses the grip on steep pulls.
function P.shaft_grip(a,b,shoulder,reach,height)
 local v=P.sub(b,a);local w=P.sub(a,shoulder);local vv=P.dot(v,v)
 local center=-P.dot(w,v)/vv
 local closest=P.add(a,P.scale(v,center))
 local radius2=reach*reach-P.dot(P.sub(closest,shoulder),P.sub(closest,shoulder))
 local lo,hi=0,1
 if radius2>=0 then
  local span=math.sqrt(radius2/vv);lo=math.max(lo,center-span);hi=math.min(hi,center+span)
 else lo=math.max(0,math.min(1,center));hi=lo end
 if lo>hi then lo=math.max(0,math.min(1,center));hi=lo end
 local preferred=math.abs(v.Z)>1e-6 and (height-a.Z)/v.Z or center
 return P.add(a,P.scale(v,math.max(lo,math.min(hi,preferred))))
end
-- Solve the contact first, then the knees. The ankle is above the sole in the
-- native rig; rotating around the ankle alone lifts the ski off the surface.
function P.ski_contact(foot,x,y,yaw,surface,sole_z)
 local c,s=math.cos(yaw),math.sin(yaw)
 local wx,wy=x+c*foot.X-s*foot.Y,y+s*foot.X+c*foot.Y
 local z=assert(surface(wx,wy))
 local a,ag=surface(wx+c*75,wy+s*75)
 local b,bg=surface(wx-c*75,wy-s*75)
 local pitch=-math.atan((ag or a)-(bg or b),150)
 local q={X=0,Y=math.sin(pitch/2),Z=0,W=math.cos(pitch/2)}
 local ankle=P.rotate(q,{X=0,Y=0,Z=foot.Z-(sole_z or 0)})
 return {X=foot.X+ankle.X,Y=foot.Y,Z=z+ankle.Z},q,{X=wx,Y=wy,Z=z}
end
function P.board_frame(x,y,yaw,surface,sole_z)
 local c,s=math.cos(yaw),math.sin(yaw)
 local pitch=-math.atan(surface(x+c*120,y+s*120)-surface(x-c*120,y-s*120),240)
 local q={X=0,Y=math.sin(pitch/2),Z=0,W=math.cos(pitch/2)}
 -- Offset the rotated sole plane, rather than the unrotated mesh origin.
 return surface(x,y)-sole_z/math.cos(pitch),q
end
function P.grounded_root(legs)
 local root=math.huge
 for _,leg in ipairs(legs)do
  local h,k,f,t=leg.hip,leg.knee,leg.foot,leg.target
  local reach=P.length(P.sub(k,h))+P.length(P.sub(f,k))-2
  local horizontal=(t.X-h.X)^2+(t.Y-h.Y)^2
  assert(horizontal<reach*reach,'Ski target beyond leg reach')
  -- A slight bend avoids snapping through a fully straight knee on crests.
  root=math.min(root,t.Z+math.sqrt(reach*reach-horizontal)-h.Z)
 end
 return root
end
function P.depth_height(bytes,side,width,eye,x,y)
 local col=(y-eye.Y)/width*side+side*.5-.5
 local row=-(x-eye.X)/width*side+side*.5-.5
 local ix,iy=math.floor(col),math.floor(row)
 if ix<0 or iy<0 or ix>=side-1 or iy>=side-1 then return nil end
 local u,v=col-ix,row-iy
 local function at(i,j)return string.unpack('<f',bytes,1+4*(j*side+i))end
 local a,b,c,d=at(ix,iy),at(ix+1,iy),at(ix,iy+1),at(ix+1,iy+1)
 for _,n in ipairs({a,b,c,d})do if not(n>0 and n<100000)then return nil end end
 return eye.Z-((a*(1-u)+b*u)*(1-v)+(c*(1-u)+d*u)*v)
end
return P
