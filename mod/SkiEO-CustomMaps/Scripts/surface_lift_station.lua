-- Circular guide sheaves tangent to both the inclined bullwheel's horizontal
-- entry/exit and the suspended line. All geometry is shared with the cable.
local P=require('surface_lift_pose_math')
local S={}
local function vec(p)return{X=p.x,Y=p.y,Z=p.z}end
local function quaternion(x,y)
    local a=P.between({X=1,Y=0,Z=0},x)
    return P.mul(P.between(P.rotate(a,{X=0,Y=1,Z=0}),y),a)
end
function S.solve(origin,direction,lead,radius,target,sag)
    local b=P.add(origin,P.scale(direction,lead))
    local virtual={X=target.X,Y=target.Y,Z=target.Z-4*sag}
    local delta=P.sub(virtual,b);local along=P.dot(delta,direction)
    assert(along>radius,'Station guide overlaps the first line support')
    local perpendicular=P.sub(delta,P.scale(direction,along))
    local height=P.length(perpendicular)
    local up=height>1e-6 and P.scale(perpendicular,1/height)or{X=0,Y=0,Z=1}
    local center=P.add(b,P.scale(up,radius))
    local theta=math.atan(height-radius,along)+math.asin(radius/math.sqrt(along^2+(height-radius)^2))
    theta=math.max(0,theta)
    local tangent=P.add(b,P.add(P.scale(direction,radius*math.sin(theta)),P.scale(up,radius*(1-math.cos(theta)))))
    local q=quaternion(direction,up)
    return {origin=origin,direction=direction,up=up,b=b,center=center,tangent=tangent,theta=theta,
        radius=radius,lead=lead,sag=sag,target=target,
        transform={Translation=center,Rotation=q,Scale3D={X=radius/80,Y=radius/80,Z=1}}}
end
function S.arc(g,angle)
    return P.add(g.b,P.add(P.scale(g.direction,g.radius*math.sin(angle)),P.scale(g.up,g.radius*(1-math.cos(angle)))))
end
function S.build(route,supports,definition,G,sag_function)
    local guides={{},{}}
    for _=1,8 do for terminal=1,2 do for _,lane in ipairs({-160,160})do
        local path=lane>0 and supports.return_path or supports
        local at=terminal==1 and 1 or #path
        local s=path[at];local next_support=path[at+(terminal==1 and 1 or -1)]
        local target={X=next_support.x+next_support.nx*lane,Y=next_support.y+next_support.ny*lane,
            Z=next_support.z+(lane>0 and next_support.return_height or next_support.height)}
        local target_distance=next_support.distance
        if #path==2 and guides[3-terminal][lane]then
            target=guides[3-terminal][lane].tangent;target_distance=guides[3-terminal][lane].distance
        end
        local old=guides[terminal][lane]
        local span=math.abs(target_distance-(old and old.distance or s.distance))
        local sag=lane>0 and sag_function(span)or 40
        local origin={X=s.x+s.nx*lane,Y=s.y+s.ny*lane,Z=s.z+(lane>0 and s.return_height or s.height)}
        local sign=terminal==1 and 1 or -1
        local direction={X=sign*math.cos(s.yaw),Y=sign*math.sin(s.yaw),Z=0}
        local lead=terminal==2 and 250 or definition and definition.drive=='covered' and 850 or 450
        -- Small reusable maps may have a support close to the station.
        lead=math.min(lead,math.max(100,P.dot(P.sub(target,origin),direction)*.4))
        local g=S.solve(origin,direction,lead,terminal==1 and 80 or 60,target,sag)
        g.distance=G.nearest(route,g.tangent.X,g.tangent.Y)
        g.flat_distance=G.nearest(route,g.b.X,g.b.Y)
        g.distances={g.flat_distance,g.distance}
        for n=1,15 do local p=S.arc(g,g.theta*n/16);g.distances[#g.distances+1]=G.nearest(route,p.X,p.Y)end
        guides[terminal][lane]=g
    end end end
    return guides
end
function S.sample(g,p)
    local along=P.dot(P.sub(vec(p),g.origin),g.direction)
    local v
    if along<=g.lead then v=P.add(g.origin,P.scale(g.direction,math.max(0,along)))
    else
        local angle=math.asin(math.max(0,math.min(math.sin(g.theta),(along-g.lead)/g.radius)))
        v=S.arc(g,angle)
    end
    p.x,p.y,p.z=v.X,v.Y,v.Z;return p
end
function S.mounts(route,supports,G)
    local mesh={vertices={},normals={},uv={},triangles={}}
    local function rod(a,b,r,color)
        local axis=P.unit(P.sub(b,a));local x=P.unit(P.cross(axis,math.abs(axis.Z)<.9 and{X=0,Y=0,Z=1}or{X=1,Y=0,Z=0}))
        local y=P.cross(axis,x);local base=#mesh.vertices
        for _,p in ipairs({a,b})do for i=0,7 do
            local n=P.add(P.scale(x,math.cos(i*math.pi/4)),P.scale(y,math.sin(i*math.pi/4)))
            mesh.vertices[#mesh.vertices+1]=P.add(p,P.scale(n,r));mesh.normals[#mesh.normals+1]=n
            mesh.uv[#mesh.uv+1]={X=(color+.5)/8,Y=.5}
        end end
        for i=0,7 do local j=(i+1)%8
            for _,k in ipairs({i,j,8+i,j,8+j,8+i})do mesh.triangles[#mesh.triangles+1]=base+k end
        end
    end
    for terminal,group in ipairs(supports.guides or{})do
        local s=supports[terminal==1 and 1 or #supports]
        if terminal==1 then
            local main=G.wheel_transform(s)
            local anchor=P.point(main,{X=0,Y=0,Z=60})
            local direction=group[-160].direction
            local top=P.add(anchor,P.scale(direction,math.sqrt(160^2+((s.return_height-s.height)*.5)^2)+100))
            local base={X=top.X,Y=top.Y,Z=assert(route.ground(top.X,top.Y))}
            rod(base,top,14,0);rod(top,anchor,12,0)
        else
            local main=G.wheel_transform(s);local center=main.Translation
            local anchor=P.point(main,{X=0,Y=0,Z=60})
            rod(center,anchor,12,0)
            for _,side in ipairs({-160,160})do
                rod(anchor,{X=s.x+s.nx*side,Y=s.y+s.ny*side,Z=s.z+s.height*1.13},7,0)
            end
        end
        for _,g in pairs(group)do
            local normal=P.rotate(g.transform.Rotation,{X=0,Y=0,Z=1})
            local head=P.add(g.center,P.scale(normal,35))
            local foot={X=head.X,Y=head.Y,Z=assert(route.ground(head.X,head.Y))}
            rod(foot,head,10,0);rod(head,g.center,9,0)
            rod(foot,P.add(foot,{X=0,Y=0,Z=20}),25,2)
        end
    end
    for _,w in ipairs(supports.wheels or{})do
        local s=supports[w.support];local c=w.base.Translation
        local axis=P.rotate(w.base.Rotation,{X=0,Y=0,Z=1})
        if P.dot(axis,{X=s.x-c.X,Y=s.y-c.Y,Z=0})<0 then axis=P.scale(axis,-1)end
        local bearing=P.add(c,P.scale(axis,38))
        local shoulder={X=s.x,Y=s.y,Z=s.z+(w.lane>0 and s.return_height or s.height)+80}
        rod(c,bearing,9,0);rod(bearing,shoulder,6,0)
    end
    return mesh
end
return S
