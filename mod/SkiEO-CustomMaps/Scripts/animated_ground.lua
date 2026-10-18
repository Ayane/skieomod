-- Paw support over baked animation: independent two-bone legs, an upright
-- torso across a slope, planted stance feet and model-derived contact meshes.
local Ground={}
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<1e7 end
local function v(x,y,z)return {X=x,Y=y,Z=z}end
local function arr(a,i)return v(a[i or 1],a[(i or 1)+1],a[(i or 1)+2])end
local function add(a,b)return v(a.X+b.X,a.Y+b.Y,a.Z+b.Z)end
local function sub(a,b)return v(a.X-b.X,a.Y-b.Y,a.Z-b.Z)end
local function mul(a,s)return v(a.X*s,a.Y*s,a.Z*s)end
local function dot(a,b)return a.X*b.X+a.Y*b.Y+a.Z*b.Z end
local function cross(a,b)return v(a.Y*b.Z-a.Z*b.Y,a.Z*b.X-a.X*b.Z,a.X*b.Y-a.Y*b.X)end
local function length(a)return math.sqrt(dot(a,a))end
local function unit(a)return mul(a,1/math.max(1e-8,length(a)))end
local function mix(a,b,t)return add(a,mul(sub(b,a),t))end
local function smooth(t)t=math.max(0,math.min(1,t));return t*t*(3-2*t)end
local function index(i,n)return finite(i) and i%1==0 and i>=1 and i<=n end
function Ground.decode(bytes,model)
    assert(type(bytes)=='string' and #bytes<=512*1024,'Ground rig exceeds 512 KiB')
    local rig=require('json').decode(bytes)
    assert(rig.format=='skieo-ground-rig' and rig.version==1 and index(rig.section,#model.sections),'Invalid ground rig')
    local mesh=model.sections[rig.section]
    assert(finite(rig.leg_height_cm) and rig.leg_height_cm>5 and rig.leg_height_cm<100,'Invalid leg height')
    assert(rig.paw_spacing==nil or finite(rig.paw_spacing) and rig.paw_spacing>=.6 and rig.paw_spacing<=1,'Invalid paw spacing')
    assert(type(rig.paws)=='table' and #rig.paws==4 and type(rig.clips)=='table','Invalid ground rig paws/clips')
    local used={}
    for _,p in ipairs(rig.paws) do
        assert(type(p.rest)=='table' and #p.rest==3 and type(p.sole)=='table' and #p.sole>=3 and #p.sole<=256,'Invalid paw sole')
        for _,n in ipairs(p.rest) do assert(finite(n),'Invalid paw rest position') end
        local members={}
        assert(type(p.vertices)=='table' and #p.vertices<=4096,'Invalid leg vertices')
        for _,m in ipairs(p.vertices) do
            assert(#m==10 and index(m[1],mesh.count) and not used[m[1]],'Invalid or overlapping leg vertex')
            for i=2,10 do assert(finite(m[i]),'Invalid leg binding') end
            assert(m[2]>=0 and m[3]>=0 and m[2]+m[3]<=1.00001 and m[4]>=0 and m[4]<=1,'Invalid leg influence')
            members[m[1]]=true;used[m[1]]=true
        end
        for _,i in ipairs(p.sole) do assert(members[i],'Sole outside its leg') end
        assert(type(p.triangles)=='table' and #p.triangles>=1 and #p.triangles<=512,'Invalid sole topology')
        for _,t in ipairs(p.triangles) do
            assert(#t==3,'Invalid sole triangle')
            for _,i in ipairs(t) do assert(members[i],'Sole triangle outside its leg') end
        end
        for name,clip in pairs(mesh.clips) do
            local c=rig.clips[name];local frames=p.frames and p.frames[name]
            assert(c and c.duration==clip.duration or c and math.abs(c.duration-clip.duration)<1e-5,'Ground clip duration mismatch')
            assert(c.loop==clip.loop and type(frames)=='table' and #frames==clip.frames,'Ground clip frames mismatch')
            for _,f in ipairs(frames) do assert(#f==6,'Invalid leg anchors');for _,n in ipairs(f) do assert(finite(n),'Invalid leg anchor') end end
            if c.stride then
                assert(finite(c.stride) and c.stride>10 and c.stride<=150 and finite(c.stance) and c.stance>=.2 and c.stance<=.9
                    and finite(c.lift) and c.lift>=0 and c.lift<=30 and type(c.offsets)=='table' and #c.offsets==4,'Invalid gait')
                for _,n in ipairs(c.offsets) do assert(finite(n) and n>=0 and n<1,'Invalid gait phase') end
            end
        end
    end
    return rig
end
-- Unreal positive Pitch points the local X axis uphill. Roll stays zero.
function Ground.axes(yaw,pitch)
    local a,b=yaw*math.pi/180,pitch*math.pi/180
    local c,s,cp,sp=math.cos(a),math.sin(a),math.cos(b),math.sin(b)
    return {v(cp*c,cp*s,sp),v(-s,c,0),v(-sp*c,-sp*s,cp)}
end
function Ground.rotate(axes,p)return add(add(mul(axes[1],p.X),mul(axes[2],p.Y)),mul(axes[3],p.Z))end
function Ground.inverse(axes,p)return v(dot(p,axes[1]),dot(p,axes[2]),dot(p,axes[3]))end
local function between(from,to)
    local a,b=unit(from),unit(to);local axis=cross(a,b);local d=math.max(-1,math.min(1,dot(a,b)))
    if d<-.9999 then
        local k=unit(cross(a,math.abs(a.Z)<.9 and v(0,0,1) or v(0,1,0)))
        return {2*k.X*k.X-1,2*k.X*k.Y,2*k.X*k.Z,2*k.Y*k.X,2*k.Y*k.Y-1,2*k.Y*k.Z,2*k.Z*k.X,2*k.Z*k.Y,2*k.Z*k.Z-1}
    end
    local x,y,z=axis.X,axis.Y,axis.Z;local s=1/math.max(1e-8,1+d)
    return {1-(y*y+z*z)*s,x*y*s-z,x*z*s+y,x*y*s+z,1-(x*x+z*z)*s,y*z*s-x,x*z*s-y,y*z*s+x,1-(x*x+y*y)*s}
end
local function rotate3(r,x,y,z)return r[1]*x+r[2]*y+r[3]*z,r[4]*x+r[5]*y+r[6]*z,r[7]*x+r[8]*y+r[9]*z end
local function knee(h,k,a,t,hint)
    local upper,lower=length(sub(k,h)),length(sub(a,k));local dir=unit(sub(t,h));local d=math.max(.01,length(sub(t,h)))
    -- Small extension on steep cross slopes retains contact instead of lifting
    -- the entire torso to fit a rigid, maximum-height bounding box.
    local stretch=math.max(1,d/(upper+lower)*1.00001);upper=upper*stretch;lower=lower*stretch
    local along=math.max(-upper,math.min(upper,(d*d+upper*upper-lower*lower)/(2*d)))
    -- Keep the bending plane consistent when an almost straight baked leg
    -- crosses its hip axis; a tiny sign change must not flip its knee.
    local bend=sub(hint,mul(dir,dot(hint,dir)))
    local animated=sub(sub(k,h),mul(dir,dot(sub(k,h),dir)))
    if length(animated)>.001 then
        if dot(animated,bend)<0 then animated=mul(animated,-1) end
        bend=mix(unit(bend),unit(animated),.35)
    end
    return add(add(h,mul(dir,along)),mul(unit(bend),math.sqrt(math.max(0,upper*upper-along*along))))
end
local function anchors(p,c,name,seconds)
    local frames=p.frames[name];local count=#frames
    local f=c.loop and seconds%c.duration/c.duration*count or math.min(1,seconds/c.duration)*(count-1)
    local a=math.floor(f);local b=c.loop and (a+1)%count or math.min(a+1,count-1)
    return mix(arr(frames[a+1]),arr(frames[b+1]),f-a),mix(arr(frames[a+1],4),arr(frames[b+1],4),f-a)
end
function Ground.penetration(surface,leg_height)
    return math.min(math.max(0,surface.fresh_cm or 0)*.85,leg_height+8)
end
function Ground.visibility(distance,surface)
    return smooth((1000-distance)/400)*(1-smooth(math.max(0,surface.fresh_cm or 0)*.85/3))
end
function Ground.solve(rig,vertices,normals,name,seconds,x,y,jump,yaw,environment,state,emit,adaptation,dt,blend_weight)
    local c=assert(rig.clips[name],'Unknown grounded clip')
    blend_weight=blend_weight or 1
    assert(finite(blend_weight) and blend_weight>=0 and blend_weight<=1,'Invalid grounded blend weight')
    local changed=state.clip and state.clip~=name;state.clip=name
    adaptation=adaptation==nil and 1 or adaptation
    assert(finite(adaptation) and adaptation>=0 and adaptation<=1,'Invalid leg adaptation')
    local old_adapt=state.adaptation
    local step=math.max(0,math.min(.25,dt or 1/30))
    state.adaptation=old_adapt and old_adapt+(adaptation-old_adapt)*(1-math.exp(-step/.12)) or adaptation
    if state.adaptation<.001 then state.adaptation=0 end
    local strength=state.adaptation
    local spacing=rig.paw_spacing or 1
    local yaw_axes=Ground.axes(yaw,0);local samples={};local fronts,backs={},{}
    local root_z=0
    for i,p in ipairs(rig.paws) do
        local r=Ground.rotate(yaw_axes,v(p.rest[1],p.rest[2]*spacing,p.rest[3]));local s=environment(x+r.X,y+r.Y)
        assert(s.inside,'Paw outside map')
        samples[i]=s
        local group=p.rest[1]>0 and fronts or backs
        group[#group+1]={z=s.z-Ground.penetration(s,rig.leg_height_cm),x=p.rest[1]}
    end
    local function average(group,key)local n=0;for _,s in ipairs(group) do n=n+s[key] end;return n/#group end
    local pitch=math.atan((average(fronts,'z')-average(backs,'z'))/(average(fronts,'x')-average(backs,'x')))*180/math.pi
    pitch=math.max(-45,math.min(45,pitch));local axes=Ground.axes(yaw,pitch)
    for i,p in ipairs(rig.paws) do root_z=root_z+samples[i].z-Ground.penetration(samples[i],rig.leg_height_cm)-Ground.rotate(axes,arr(p.rest)).Z end
    root_z=root_z/4+(jump or 0);local origin=v(x,y,root_z)
    local contacts={}
    for i,p in ipairs(rig.paws) do
        local old=state[i] or {};state[i]=old
        if changed then old.source=blend_weight<1 and old.h and {h=old.h,k=old.k,target=old.target} or nil end
        if blend_weight==1 then old.source=nil end
        local offset,lift,stance,phase,cycle,swing=0,0,true,0,0,0
        if c.stride then
            local elapsed=seconds/c.duration+c.offsets[i];phase=elapsed%1;cycle=math.floor(elapsed)
            stance=phase<c.stance
            if stance then offset=c.stride*(c.stance/2-phase)
            else
                swing=(phase-c.stance)/(1-c.stance)
                -- Hermite endpoints match the backward stance velocity.
                -- Lift has zero velocity at takeoff and landing too.
                local t=swing;local tangent=-c.stride*(1-c.stance)
                offset=c.stride*c.stance*(smooth(t)-.5)+tangent*(2*t^3-3*t*t+t)
                lift=c.lift*16*t*t*(1-t)*(1-t)
            end
        end
        stance=stance and (jump or 0)<.1
        local free=add(origin,Ground.rotate(axes,v(p.rest[1]+offset,p.rest[2]*spacing,p.rest[3]+lift)))
        local entered=stance and not old.stance
        local leg_strength=strength
        if strength>0 and stance then
            if entered or not old.plant then old.plant=free end
            -- Fade the correction through tight turns, without teleporting a
            -- planted paw or forcing a stretched, widely spread leg.
            local drift=math.sqrt((free.X-old.plant.X)^2+(free.Y-old.plant.Y)^2)
            leg_strength=leg_strength*(1-smooth((drift-10)/14))
            free=v(old.plant.X,old.plant.Y,free.Z)
        elseif strength>0 then
            if old.stance and old.foot then old.release={X=old.foot.X-free.X,Y=old.foot.Y-free.Y} end
            if old.release then
                local remaining=1-smooth(swing)
                free.X=free.X+old.release.X*remaining;free.Y=free.Y+old.release.Y*remaining
            end
        else
            old.plant=nil;old.release=nil
        end
        if strength==0 then leg_strength=0
        elseif old.leg_strength then
            if old.source then leg_strength=old.leg_strength+(leg_strength-old.leg_strength)*blend_weight end
            leg_strength=old.leg_strength+(leg_strength-old.leg_strength)*(1-math.exp(-step/.12))
        end
        old.leg_strength=leg_strength
        local s=environment(free.X,free.Y);assert(s.inside,'Paw outside map')
        local sink=Ground.penetration(s,rig.leg_height_cm)
        local t=v(free.X,free.Y,s.z-sink+lift+(jump or 0))
        if leg_strength>0 then
        local h,k=anchors(p,c,name,seconds)
        if old.source then
            h=mix(old.source.h,h,blend_weight);k=mix(old.source.k,k,blend_weight)
            t=mix(old.source.target,t,blend_weight)
        end
        old.h=h;old.k=k;old.target=t
        h=add(origin,Ground.rotate(axes,h));k=add(origin,Ground.rotate(axes,k))
        local center=v(0,0,math.huge)
        for _,j in ipairs(p.sole) do local q=vertices[j];center.X=center.X+q.X;center.Y=center.Y+q.Y;center.Z=math.min(center.Z,q.Z) end
        center.X=center.X/#p.sole;center.Y=center.Y/#p.sole
        local a=add(origin,Ground.rotate(axes,center))
        local kk=knee(h,k,a,t,mul(yaw_axes[1],p.rest[1]>0 and 1 or -1))
        local sx1,sx2=environment(t.X+2,t.Y),environment(t.X-2,t.Y)
        local sy1,sy2=environment(t.X,t.Y+2),environment(t.X,t.Y-2)
        local normal=unit(v(-((sx1.ground or sx1.z)-(sx2.ground or sx2.z))/4,
            -((sy1.ground or sy1.z)-(sy2.ground or sy2.z))/4,1))
        local fx=unit(sub(yaw_axes[1],mul(normal,dot(yaw_axes[1],normal))))
        local foot_axes={fx,unit(cross(normal,fx)),normal}
        local upper_rotation=between(sub(k,h),sub(kk,h));local lower_rotation=between(sub(a,k),sub(t,kk))
        local ax,ay,az=axes[1],axes[2],axes[3]
        local fx,fy,fz=foot_axes[1],foot_axes[2],foot_axes[3]
        for _,m in ipairs(p.vertices) do
            local q,n=vertices[m[1]],normals[m[1]]
            local ox=origin.X+ax.X*q.X+ay.X*q.Y+az.X*q.Z
            local oy=origin.Y+ax.Y*q.X+ay.Y*q.Y+az.Y*q.Z
            local oz=origin.Z+ax.Z*q.X+ay.Z*q.Y+az.Z*q.Z
            local nx=ax.X*n.X+ay.X*n.Y+az.X*n.Z
            local ny=ax.Y*n.X+ay.Y*n.Y+az.Y*n.Z
            local nz=ax.Z*n.X+ay.Z*n.Y+az.Z*n.Z
            local ux,uy,uz=rotate3(upper_rotation,ox-h.X,oy-h.Y,oz-h.Z)
            local lx,ly,lz=rotate3(lower_rotation,ox-k.X,oy-k.Y,oz-k.Z)
            local unx,uny,unz=rotate3(upper_rotation,nx,ny,nz)
            local lnx,lny,lnz=rotate3(lower_rotation,nx,ny,nz)
            local weight=m[4]*(m[2]+m[3]);local blend=1-weight;local torso=1-m[2]-m[3]
            local px=(ox*torso+(h.X+ux)*m[2]+(kk.X+lx)*m[3])*blend+(t.X+fx.X*m[5]+fy.X*m[6]+fz.X*m[7])*weight-origin.X
            local py=(oy*torso+(h.Y+uy)*m[2]+(kk.Y+ly)*m[3])*blend+(t.Y+fx.Y*m[5]+fy.Y*m[6]+fz.Y*m[7])*weight-origin.Y
            local pz=(oz*torso+(h.Z+uz)*m[2]+(kk.Z+lz)*m[3])*blend+(t.Z+fx.Z*m[5]+fy.Z*m[6]+fz.Z*m[7])*weight-origin.Z
            nx=(nx*torso+unx*m[2]+lnx*m[3])*blend+(fx.X*m[8]+fy.X*m[9]+fz.X*m[10])*weight
            ny=(ny*torso+uny*m[2]+lny*m[3])*blend+(fx.Y*m[8]+fy.Y*m[9]+fz.Y*m[10])*weight
            nz=(nz*torso+unz*m[2]+lnz*m[3])*blend+(fx.Z*m[8]+fy.Z*m[9]+fz.Z*m[10])*weight
            local inv=1/math.max(1e-8,math.sqrt(nx*nx+ny*ny+nz*nz))
            q.X=q.X+(px*ax.X+py*ax.Y+pz*ax.Z-q.X)*leg_strength
            q.Y=q.Y+(px*ay.X+py*ay.Y+pz*ay.Z-q.Y)*leg_strength
            q.Z=q.Z+(px*az.X+py*az.Y+pz*az.Z-q.Z)*leg_strength
            n.X=n.X+((nx*ax.X+ny*ax.Y+nz*ax.Z)*inv-n.X)*leg_strength
            n.Y=n.Y+((nx*ay.X+ny*ay.Y+nz*ay.Z)*inv-n.Y)*leg_strength
            n.Z=n.Z+((nx*az.X+ny*az.Y+nz*az.Z)*inv-n.Z)*leg_strength
            inv=1/math.max(1e-8,length(n));n.X=n.X*inv;n.Y=n.Y*inv;n.Z=n.Z*inv
        end
        else old.h=nil;old.k=nil;old.target=nil;old.source=nil end
        local bottom=math.huge;local center_x,center_y=0,0
        for _,j in ipairs(p.sole) do
            local q=Ground.rotate(axes,vertices[j]);bottom=math.min(bottom,origin.Z+q.Z)
            center_x=center_x+origin.X+q.X;center_y=center_y+origin.Y+q.Y
        end
        local crossed=old.z and old.z>s.z+.05 and bottom<=s.z+.05 and bottom<old.z
        local landing=name..':'..(cycle+(phase>(c.stance or 1) and 1 or 0))
        if emit and s.snow_cm>.2 and (jump or 0)<.1 and bottom<=s.z+.1
            and (entered or crossed) and old.landing~=landing then
            local profile={vertices={},triangles={}};local lookup={}
            for _,tri in ipairs(p.triangles) do
                for _,j in ipairs(tri) do
                    if not lookup[j] then
                        lookup[j]=#profile.vertices+1
                        local q=add(origin,Ground.rotate(axes,vertices[j]));profile.vertices[#profile.vertices+1]={X=q.X,Y=q.Y}
                    end
                    profile.triangles[#profile.triangles+1]=lookup[j]-1
                end
            end
            contacts[#contacts+1]={x=t.X,y=t.Y,z=s.z,yaw=yaw,profile=profile,paw=i}
            old.landing=landing
        end
        if not emit and stance then old.landing=landing end
        old.stance=stance;old.clip=name;old.z=bottom;old.foot={X=center_x/#p.sole,Y=center_y/#p.sole}
    end
    return root_z,pitch,contacts
end
return Ground
