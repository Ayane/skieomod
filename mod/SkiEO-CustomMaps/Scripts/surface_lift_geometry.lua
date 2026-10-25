-- Metres are configuration units; runtime geometry uses world centimetres.
-- Kept independent of Unreal for deterministic route and clearance tests.
local G={}
local Station=require('surface_lift_station')
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<1e7 end
local function dist(a,b) return math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+(a.z-b.z)^2) end
local function return_sag(span)return math.max(40,math.min(200,20*(span/10000)^2))end
function G.validate(d)
    assert(type(d)=='table' and type(d.name)=='string' and #d.name>0 and #d.name<=100,'Lift needs a name')
    assert(type(d.route)=='table' and #d.route>=2 and #d.route<=128,'Lift route needs 2..128 points')
    for _,p in ipairs(d.route) do
        assert(type(p)=='table' and finite(p[1]) and finite(p[2]) and finite(p[3]),'Invalid lift route point')
    end
    assert(finite(d.speed_mps) and d.speed_mps>=.5 and d.speed_mps<=5,'Lift speed must be .5..5 m/s')
    assert(finite(d.capacity_per_hour) and d.capacity_per_hour>=100 and d.capacity_per_hour<=1200,'Invalid lift capacity')
    assert(d.kind=='detachable_platter' or d.kind=='fixed_platter' or d.kind=='fixed_chair','Unknown surface lift type')
    assert(d.ascent_side==nil or d.ascent_side=='left' or d.ascent_side=='right','Unknown ascent side')
    assert(d.max_snow_cm==nil or(finite(d.max_snow_cm)and d.max_snow_cm>=110 and d.max_snow_cm<=300),'Maximum snow depth must be 110..300 cm')
    assert(d.drive==nil or d.drive=='open' or d.drive=='covered' or d.drive=='modern','Unknown drive station')
    assert(d.return_station==nil or d.return_station=='floating' or d.return_station=='release' or d.return_station=='lattice','Unknown return station')
    assert(type(d.pylons)=='number' and d.pylons%1==0 and d.pylons>=1 and d.pylons<=32,'Invalid pylon count')
    require('surface_lift_models').validate(d)
end
function G.route(definition,ground)
    G.validate(definition)
    local nodes={}
    for _,p in ipairs(definition.route) do
        local z=assert(ground(p[1],p[2]),'Lift route is outside terrain')
        nodes[#nodes+1]={x=p[1],y=p[2],z=z}
    end
    -- UE's local +Y is right when looking uphill. The ascent uses lane -160,
    -- so reflecting the normals puts that lane on the requested right side.
    local result={points={},nodes=nodes,xy_segments={},length=0,ground=ground,mirror=definition.ascent_side=='right'and -1 or 1}
    local raw_length=0
    for i=1,#nodes-1 do
        local a,b=nodes[i],nodes[i+1];local length=dist(a,b)
        assert(length>1,'Repeated lift route point')
        raw_length=raw_length+length
        assert(raw_length<=300000,'Lift route exceeds 3000 m')
        local segments=math.ceil(length/200)
        result.xy_segments[#result.xy_segments+1]={first=#result.points+1,count=segments}
        for j=0,segments-1 do
            local t=j/segments;local x,y=a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t
            result.points[#result.points+1]={x=x,y=y,z=assert(ground(x,y)),node=i}
        end
    end
    result.points[#result.points+1]=nodes[#nodes]
    for i,p in ipairs(result.points) do
        if i>1 then result.length=result.length+dist(result.points[i-1],p) end
        p.distance=result.length
        local a,b=result.points[math.max(1,i-1)],result.points[math.min(#result.points,i+1)]
        p.yaw=math.atan(b.y-a.y,b.x-a.x);p.nx=-math.sin(p.yaw)*result.mirror;p.ny=math.cos(p.yaw)*result.mirror
    end
    assert(result.length>=3000 and result.length<=300000,'Lift route must be 30..3000 m')
    return result
end
function G.sample(route,distance)
    local points=route.points;distance=math.max(0,math.min(route.length,distance))
    local lo,hi=1,#points
    while hi-lo>1 do local mid=(lo+hi)//2;if points[mid].distance>distance then hi=mid else lo=mid end end
    local a,b=points[lo],points[hi];local t=(distance-a.distance)/math.max(.001,b.distance-a.distance)
    local nx,ny=a.nx+(b.nx-a.nx)*t,a.ny+(b.ny-a.ny)*t
    local n=math.sqrt(nx*nx+ny*ny);nx,ny=nx/n,ny/n
    return {x=a.x+(b.x-a.x)*t,y=a.y+(b.y-a.y)*t,z=a.z+(b.z-a.z)*t,
        nx=nx,ny=ny,yaw=math.atan(-nx*(route.mirror or 1),ny*(route.mirror or 1)),distance=distance,mirror=route.mirror or 1}
end
function G.supports(route,count,kind,definition)
    local supports={};local nodes=route.nodes
    local height=kind=='fixed_platter' and 500 or 600
    if #nodes==count+2 then
        local at=1
        for i,n in ipairs(nodes) do
            while at<#route.points and ((route.points[at].x-n.x)^2+(route.points[at].y-n.y)^2)>1 do at=at+1 end
            local p=G.sample(route,route.points[at].distance);p.height=height
            if i>1 and i<#nodes then
                local a,b=nodes[i-1],nodes[i+1]
                local incoming=math.atan(n.y-a.y,n.x-a.x);local outgoing=math.atan(b.y-n.y,b.x-n.x)
                local turn=(outgoing-incoming+math.pi)%(2*math.pi)-math.pi
                p.angle=math.abs(turn)>math.rad(5)
            end
            supports[#supports+1]=p
        end
    else
        -- Where OSM supplies only the axis, fit the support positions to the
        -- terrain profile. Equal spacing can straddle a crest and force an
        -- implausibly tall station and telescopic pole. Surveyed supports in
        -- the branch above are never moved.
        local distances={0,route.length}
        for i=2,#nodes-1 do
            local nearest
            for _,p in ipairs(route.points)do
                local error=(p.x-nodes[i].x)^2+(p.y-nodes[i].y)^2
                if not nearest or error<nearest.error then nearest={distance=p.distance,error=error}end
            end
            distances[#distances+1]=nearest.distance
        end
        assert(#distances<=count+2,'More route bends than available lift supports')
        local separation=math.min(1800,route.length/(count+1)*.35)
        while #distances<count+2 do
            table.sort(distances)
            local best,score
            for i=1,#distances-1 do
                local a,b=G.sample(route,distances[i]),G.sample(route,distances[i+1])
                local span=b.distance-a.distance
                for _,p in ipairs(route.points)do
                    if p.distance>a.distance+separation and p.distance<b.distance-separation then
                        local t=(p.distance-a.distance)/span
                        local error=math.abs(p.z-(a.z*(1-t)+b.z*t-160*t*(1-t)))
                        local value=error+.0001*span*4*t*(1-t)
                        if not score or value>score then best=p.distance;score=value end
                    end
                end
            end
            assert(best,'Lift supports cannot fit this short route')
            distances[#distances+1]=best
        end
        table.sort(distances)
        for _,s in ipairs(distances) do local p=G.sample(route,s);p.height=height;supports[#supports+1]=p end
        for i=2,#supports-1 do
            local a,b=G.sample(route,math.max(0,supports[i].distance-500)),G.sample(route,math.min(route.length,supports[i].distance+500))
            supports[i].angle=math.abs((b.yaw-a.yaw+math.pi)%(2*math.pi)-math.pi)>math.rad(5)
        end
    end
    -- A convex rise between surveyed supports must not intersect the cable.
    -- Raise both adjoining heads together, keeping a minimum empty-pole gap.
    for i=1,#supports-1 do
        local a,b=supports[i],supports[i+1];local raise=0
        for _,p in ipairs(route.points) do
            if p.distance>=a.distance and p.distance<=b.distance then
                local t=(p.distance-a.distance)/math.max(1,b.distance-a.distance)
                local cable=(a.z+a.height)*(1-t)+(b.z+b.height)*t-40*4*t*(1-t)
                local floor=p.z
                for _,lane in ipairs({-160,160}) do
                    floor=math.max(floor,assert(route.ground(p.x+p.nx*lane,p.y+p.ny*lane)))
                end
                raise=math.max(raise,floor+(kind=='fixed_platter' and 430 or 480)-cable)
            end
        end
        a.height=a.height+raise;b.height=b.height+raise
    end
    G.return_supports(supports,kind)
    if kind~='fixed_chair'then supports.guides=Station.build(route,supports,definition,G,return_sag)end
    return supports
end
function G.return_supports(supports,kind)
    local selected={}
    for i,p in ipairs(supports)do
        -- The lower drive changes branch height. At the upper return both
        -- branches meet a horizontal bullwheel, through their guide sheaves.
        p.return_height=p.height*(kind=='detachable_platter' and i<#supports and 1.5 or 1)
        p.return_used=true;selected[#selected+1]=p
        -- A high, unloaded return can bridge a hollow without being pulled
        -- down to the uphill compression support. Direction changes still
        -- require a return sheave. Include cable sag in the bypass decision.
        while kind=='detachable_platter' and #selected>=3 do
            local a,b,c=selected[#selected-2],selected[#selected-1],selected[#selected]
            local t=(b.distance-a.distance)/(c.distance-a.distance)
            local span=c.distance-a.distance
            local z=(a.z+a.return_height)*(1-t)+(c.z+c.return_height)*t-4*return_sag(span)*t*(1-t)
            -- Missing surveyed return hardware does not justify an entire
            -- kilometre of unsupported cable. Keep intermediate heads.
            if b.angle or span>25000 or z<b.z+b.return_height+20 then break end
            b.return_used=false;table.remove(selected,#selected-1)
        end
    end
    supports.return_path=selected
end
function G.raw_cable(route,supports,distance,lane)
    local path=lane>0 and supports.return_path or supports
    path=path or supports
    local p=G.sample(route,distance);local a,b=path[1],path[2];local index=1
    for i=1,#path-1 do a,b=path[i],path[i+1];index=i;if distance<=b.distance then break end end
    local ah=lane>0 and (a.return_height or a.height) or a.height
    local bh=lane>0 and (b.return_height or b.height) or b.height
    local av={X=a.x+a.nx*lane,Y=a.y+a.ny*lane,Z=a.z+ah}
    local bv={X=b.x+b.nx*lane,Y=b.y+b.ny*lane,Z=b.z+bh}
    local ad,bd=a.distance,b.distance
    if supports.guides and lane~=0 then
        if index==1 then
            local g=supports.guides[1][lane]
            if distance<=g.distance then return Station.sample(g,p)end
            av,ad=g.tangent,g.distance
        end
        if index==#path-1 then
            local g=supports.guides[2][lane]
            if distance>=g.distance then return Station.sample(g,p)end
            bv,bd=g.tangent,g.distance
        end
    end
    local t=math.max(0,math.min(1,(distance-ad)/math.max(1,bd-ad)))
    p.x=av.X*(1-t)+bv.X*t;p.y=av.Y*(1-t)+bv.Y*t
    local sag=lane>0 and return_sag(bd-ad) or 40
    p.z=av.Z*(1-t)+bv.Z*t-4*sag*t*(1-t)
    return p
end
-- Keep a continuous tangent through a support. The pulley frames follow this
-- curve; the rope is never kinked to fit a horizontal, pre-baked roller train.
function G.cable(route,supports,distance,lane)
    local path=lane>0 and supports.return_path or supports
    for i=2,#path-1 do
        local s=path[i];local width=math.min(140,(s.distance-path[i-1].distance)*.1,(path[i+1].distance-s.distance)*.1)
        if math.abs(distance-s.distance)<width then
            local lo,hi=s.distance-width,s.distance+width;local span=hi-lo
            local a,b=G.raw_cable(route,supports,lo,lane),G.raw_cable(route,supports,hi,lane)
            local aa,bb=G.raw_cable(route,supports,lo-.1,lane),G.raw_cable(route,supports,hi+.1,lane)
            local t=(distance-lo)/span;local t2,t3=t*t,t*t*t
            local p=G.sample(route,distance)
            for _,key in ipairs({'x','y','z'})do
                p[key]=(2*t3-3*t2+1)*a[key]+(t3-2*t2+t)*(a[key]-aa[key])*span/.1
                    +(-2*t3+3*t2)*b[key]+(t3-t2)*(bb[key]-b[key])*span/.1
            end
            return p
        end
    end
    return G.raw_cable(route,supports,distance,lane)
end
function G.wheel(support,angle)
    local rise=(support.return_height or support.height)-support.height
    local radius=math.sqrt(160^2+(rise*.5)^2)
    local x,y=radius*math.cos(angle),160*math.sin(angle)*(support.mirror or 1)
    local c,s=math.cos(support.yaw),math.sin(support.yaw)
    return {x=support.x+c*x-s*y,y=support.y+s*x+c*y,
        z=support.z+support.height+rise*(.5+.5*math.sin(angle))}
end
function G.wheel_transform(support)
    local rise=(support.return_height or support.height)-support.height
    local angle=math.atan(rise,320)*(support.mirror or 1);local radius=math.sqrt(160^2+(rise*.5)^2)
    local s,c=math.sin(angle*.5),math.cos(angle*.5)
    local sy,cy=math.sin(support.yaw*.5),math.cos(support.yaw*.5)
    return {Translation={X=support.x,Y=support.y,Z=support.z+support.height+rise*.5},
        Rotation={X=cy*s,Y=sy*s,Z=sy*c,W=cy*c},Scale3D={X=radius/200,Y=radius/200,Z=1}}
end
function G.station_guide(support,angle,tail)
    local p=G.wheel(support,math.pi/2+angle)
    local shift=(tail or 0)*(angle/math.pi)^6
    p.x=p.x+shift*math.cos(support.yaw);p.y=p.y+shift*math.sin(support.yaw)
    local theta=math.pi/2+angle
    p.z=p.z-10;p.yaw=support.yaw+math.atan(160*(support.mirror or 1)*math.cos(theta),-math.sqrt(160^2+((support.return_height-support.height)*.5)^2)*math.sin(theta))
    return p
end
-- Platter model's grip is (0,0,0), its seat (-36,0,-409) cm. Solve the
-- telescopic length and rotation so the seat touches the rider's pelvis while
-- the clamp leads it uphill. Stretching a vertical pole cannot exert traction.
function G.towing_transform(clamp,rider,yaw,seat_height,back)
    back=back or 36
    local dx,dy=clamp.x-rider.X,clamp.y-rider.Y
    local height=clamp.z-rider.Z-(seat_height or 108)
    local lead=math.sqrt(dx*dx+dy*dy)
    local length=math.sqrt(math.max(1,lead*lead+height*height-back*back))
    local pitch=math.atan(lead,height)-math.atan(back,length)
    local s,c=math.sin(pitch*.5),math.cos(pitch*.5)
    local sy,cy=math.sin(yaw*.5),math.cos(yaw*.5)
    return {Translation={X=clamp.x,Y=clamp.y,Z=clamp.z},
        Rotation={X=-sy*s,Y=cy*s,Z=sy*c,W=cy*c},Scale3D={X=1,Y=1,Z=length/409}}
end
-- Rigid transforms for the sleeve and bent end. The inner tube's visible
-- portion slides out of the casing; the plate always retains its real size.
function G.towing_parts(clamp,seat,yaw,back)
    local t=G.towing_transform(clamp,seat,yaw,0,back)
    local length=t.Scale3D.Z*409;t.Scale3D.Z=1
    return t,length,G.perch_parts(t,length)
end
function G.detachable_clamp(route,supports,d,lane,seat)
    -- Deep snow can shorten the vertical separation. Let the clamp lead
    -- farther uphill instead of pushing the handle through its own casing.
    local p=G.cable(route,supports,math.min(route.length,d+180),lane)
    for lead=200,1200,20 do
        local horizontal=math.sqrt((p.x-seat.X)^2+(p.y-seat.Y)^2)
        local vertical=p.z-seat.Z
        local length=math.sqrt(math.max(1,horizontal^2+vertical^2-60^2))
        if length>=295 and math.atan(horizontal,vertical)-math.atan(60,length)>=math.rad(25) then return p end
        p=G.cable(route,supports,math.min(route.length,d+lead),lane)
    end
    return p
end
function G.perch_parts(t,length)
    local P=require('surface_lift_pose_math')
    local function part(z,scale)
        return {Translation=P.point(t,{X=0,Y=0,Z=z}),Rotation=t.Rotation,Scale3D={X=1,Y=1,Z=scale or 1}}
    end
    assert(length>=245,'Telescopic pole compressed beyond its sleeve')
    return {upper=t,shaft=part(-60,length-233),lower=part(-length)}
end
function G.fixed_clamp(route,supports,d,lane,seat)
    local length=300;local radius2=length*length+60*60
    local function sample(at)
        local p=G.cable(route,supports,at,lane)
        return p,(p.x-seat.X)^2+(p.y-seat.Y)^2+(p.z-seat.Z)^2-radius2
    end
    local lo,hi=d,math.min(route.length,d+1200)
    local _,a=sample(lo);local _,b=sample(hi)
    if b<0 then return nil end
    if a>0 then
        -- The short rigid TKF pole hangs above the piste when empty. With a
        -- rider, the flexible cable deflects between supports, never the tube.
        local at=math.min(route.length-100,d+120)
        for _,s in ipairs(supports)do if math.abs(at-s.distance)<50 then at=s.distance+50 end end
        local p=G.cable(route,supports,at,lane)
        local horizontal=(p.x-seat.X)^2+(p.y-seat.Y)^2
        if horizontal>=radius2 then return nil end
        local z=seat.Z+math.sqrt(radius2-horizontal)
        p.sag=math.max(0,p.z-z);p.z=z;p.distance=at
        for i=1,#supports-1 do if at>=supports[i].distance and at<=supports[i+1].distance then
            p.lo=math.max(supports[i].distance,at-400)
            p.hi=math.min(supports[i+1].distance,at+400)
            if supports.guides then
                if i==1 then p.lo=math.max(p.lo,supports.guides[1][-160].distance)end
                if i==#supports-1 then p.hi=math.min(p.hi,supports.guides[2][-160].distance)end
            end
            break
        end end
        return p
    end
    for _=1,24 do local mid=(lo+hi)*.5;local _,e=sample(mid);if e<0 then lo=mid else hi=mid end end
    return (sample((lo+hi)*.5))
end
function G.flex_cable(route,supports,d,lane,loads)
    local p=G.cable(route,supports,d,lane);local sag=0
    if lane<0 then for _,load in ipairs(loads or{})do
        if load.sag and load.lo and d>load.lo and d<load.hi then
            local fraction=d<load.distance and (d-load.lo)/(load.distance-load.lo)
                or (load.hi-d)/(load.hi-load.distance)
            sag=math.max(sag,load.sag*fraction)
        end
    end end
    p.z=p.z-sag;return p
end
function G.empty_perch(clamp,yaw,length,surface)
    local sy,cy=math.sin(yaw*.5),math.cos(yaw*.5)
    return {Translation={X=clamp.x or clamp.X,Y=clamp.y or clamp.Y,Z=clamp.z or clamp.Z},
        Rotation={X=0,Y=0,Z=sy,W=cy},Scale3D={X=1,Y=1,Z=1}}
end
function G.release_length(previous,dt)
    -- Overdamped internal return spring after the rider lets go. Occupied
    -- poles follow the contact constraint directly, so rebound never lifts skis.
    return 295+math.max(0,(previous or 295)-295)*math.exp(-8*math.max(0,dt))
end
function G.nearest(route,x,y)
    local best,error
    -- Resampling the terrain adds hundreds of collinear XY points. Project
    -- onto the original segments, then interpolate the exact 3D route distance
    -- in the corresponding resampled interval (not the whole coarse chord).
    local segments=route.xy_segments
    for i=1,segments and #segments or #route.points-1 do
        local segment=segments and segments[i]
        local first=segment and segment.first or i
        local count=segment and segment.count or 1
        local a,b=route.points[first],route.points[first+count];local dx,dy=b.x-a.x,b.y-a.y
        local t=math.max(0,math.min(1,((x-a.x)*dx+(y-a.y)*dy)/math.max(1,dx*dx+dy*dy)))
        local e=(x-a.x-dx*t)^2+(y-a.y-dy*t)^2
        if not error or e<error then
            local at=math.min(count-1,math.floor(t*count));local fraction=t*count-at
            local lo,hi=route.points[first+at],route.points[first+at+1]
            error=e;best=lo.distance+(hi.distance-lo.distance)*fraction
        end
    end
    return best,error
end
function G.transport(route,surface)
    local points={};local lane=160
    for _,p in ipairs(route.points) do
        local x,y=p.x-p.nx*lane,p.y-p.ny*lane
        points[#points+1]={X=x,Y=y,Z=assert(surface(x,y))+3}
    end
    local function turn(p,top)
        for i=1,11 do
            local a=-math.pi/2+i*math.pi/12
            local dx,dy=math.cos(p.yaw),math.sin(p.yaw)
            local x=p.x+(top and 1 or -1)*dx*lane*math.cos(a)+p.nx*lane*math.sin(a)*(top and 1 or -1)
            local y=p.y+(top and 1 or -1)*dy*lane*math.cos(a)+p.ny*lane*math.sin(a)*(top and 1 or -1)
            points[#points+1]={X=x,Y=y,Z=assert(surface(x,y))+3}
        end
    end
    turn(route.points[#route.points],true)
    for i=#route.points,1,-1 do local p=route.points[i];local x,y=p.x+p.nx*lane,p.y+p.ny*lane
        points[#points+1]={X=x,Y=y,Z=assert(surface(x,y))+3}
    end
    turn(route.points[1],false)
    return points
end
-- Shared rings keep cable positions and normals continuous at every joint.
function G.path_mesh(points,radius)
    local P=require('surface_lift_pose_math')
    local m={vertices={},normals={},uv={},triangles={}}
    local count=#points;assert(count>=3)
    for i,p in ipairs(points)do
        local a,b=points[(i-2)%count+1],points[i%count+1]
        local tangent=P.unit(P.sub(b,a))
        local x=P.unit(P.cross(tangent,math.abs(tangent.Z)<.9 and {X=0,Y=0,Z=1}or{X=0,Y=1,Z=0}))
        local y=P.cross(tangent,x)
        for j=0,7 do
            local n=P.add(P.scale(x,math.cos(j*math.pi/4)),P.scale(y,math.sin(j*math.pi/4)))
            m.vertices[#m.vertices+1]=P.add(p,P.scale(n,radius));m.normals[#m.normals+1]=n;m.uv[#m.uv+1]={X=7.5/8,Y=.5}
        end
    end
    for i=0,count-1 do for j=0,7 do
        local a=i*8+j;local b=i*8+(j+1)%8;local c=((i+1)%count)*8+j;local d=((i+1)%count)*8+(j+1)%8
        for _,n in ipairs({a,b,c,b,d,c})do m.triangles[#m.triangles+1]=n end
    end end
    return m
end
-- Static cable geometry: four-sided dark rope, batched into one component.
function G.cable_mesh(route,supports,loads,definition)
    local m={vertices={},normals={},uv={},triangles={}}
    local function segment(a,b,radius,color)
        radius=radius or 1.4;color=color or 7.5/8
        local dx,dy=b.x-a.x,b.y-a.y;local h=math.max(1,math.sqrt(dx*dx+dy*dy));local nx,ny=-dy/h,dx/h
        local base=#m.vertices
        for _,p in ipairs({a,b}) do
            for i=0,3 do local u,v=math.cos(i*math.pi/2),math.sin(i*math.pi/2)
                m.vertices[#m.vertices+1]={X=p.x+nx*u*radius,Y=p.y+ny*u*radius,Z=p.z+v*radius}
                m.normals[#m.normals+1]={X=nx*u,Y=ny*u,Z=v};m.uv[#m.uv+1]={X=color,Y=.5}
            end
        end
        for i=0,3 do local j=(i+1)%4
            for _,n in ipairs({i,j,4+i,j,4+j,4+i}) do m.triangles[#m.triangles+1]=base+n end
        end
    end
    for _,lane in ipairs({-160,160}) do
        local distances={}
        for i=1,math.ceil(route.length/400)do distances[#distances+1]=math.min(route.length,i*400)end
        for _,s in ipairs(supports)do
            distances[#distances+1]=s.distance
            for offset=-140,140,20 do distances[#distances+1]=math.max(0,math.min(route.length,s.distance+offset))end
        end
        for _,group in ipairs(supports.guides or{})do
            for _,d in ipairs(group[lane].distances)do distances[#distances+1]=d end
        end
        if lane<0 then for _,load in ipairs(loads or{})do if load.lo then
            for _,d in ipairs({load.lo,load.distance,load.hi})do distances[#distances+1]=d end
        end end end
        table.sort(distances)
        local previous=G.flex_cable(route,supports,0,lane,loads);local last=0
        for _,d in ipairs(distances)do if d>last+.01 then
            local p=G.flex_cable(route,supports,d,lane,loads);segment(previous,p);previous=p;last=d
        end
        end
    end
    for j,center in ipairs({supports[1],supports[#supports]}) do
        local previous
        -- Only the used half of the inclined bullwheel carries cable.
        for i=0,24 do local a=(j==1 and math.pi/2 or -math.pi/2)+i*math.pi/24
            local p=G.wheel(center,a)
            if previous then segment(previous,p) end;previous=p
        end
    end
    if supports.stock_rail then
        for _,drop in ipairs({0,200})do
            local previous
            for _,p in ipairs(supports.stock_rail.points)do
                local q={x=p.x,y=p.y,z=p.z-drop}
                if previous then segment(previous,q,3.5,.5/8)end;previous=q
            end
        end
    end
    return m
end
return G
