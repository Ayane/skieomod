-- Optional, bounded aim groups over a baked animation. The orbit centres and
-- axes follow the sampled pose, so aiming does not detach eyes from the head.
local Aim={}
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<1e8 end
local function dot(a,b) return a.X*b.X+a.Y*b.Y+a.Z*b.Z end
local function sub(a,b) return {X=a.X-b.X,Y=a.Y-b.Y,Z=a.Z-b.Z} end
local function unit(v)
    local length=math.sqrt(dot(v,v));assert(length>1e-5,'Degenerate aim axes')
    return {X=v.X/length,Y=v.Y/length,Z=v.Z/length}
end
local function cross(a,b) return {X=a.Y*b.Z-a.Z*b.Y,Y=a.Z*b.X-a.X*b.Z,Z=a.X*b.Y-a.Y*b.X} end
local function clamp(n,limit) return math.max(-limit,math.min(limit,n)) end
function Aim.decode(bytes,model)
    assert(type(bytes)=='string' and #bytes<=65536,'Aim rig exceeds 64 KiB')
    local rig=require('json').decode(bytes)
    assert(type(rig)=='table' and rig.format=='skieo-aim-rig' and rig.version==1
        and type(rig.groups)=='table' and #rig.groups>=1 and #rig.groups<=8,'Invalid aim rig')
    local used,total={},0
    for _,group in ipairs(rig.groups) do
        assert(finite(group.section) and group.section%1==0 and model.sections[group.section],'Invalid aim section')
        local mesh=model.sections[group.section]
        assert(type(group.vertices)=='table' and #group.vertices>=4,'Invalid aim vertices')
        local members={};used[group.section]=used[group.section] or {}
        for _,index in ipairs(group.vertices) do
            assert(finite(index) and index%1==0 and index>=1 and index<=mesh.count
                and not used[group.section][index],'Invalid or overlapping aim vertex')
            members[index]=true;used[group.section][index]=true;total=total+1
        end
        assert(total<=4096,'Aim rig exceeds 4096 vertices')
        for _,pair in ipairs({group.x_pair,group.z_pair}) do
            assert(type(pair)=='table' and #pair==2 and pair[1]~=pair[2]
                and members[pair[1]] and members[pair[2]],'Invalid aim anchor pair')
        end
        assert(group.x_pair and group.z_pair,'Missing aim axes')
        local x=sub(mesh.vertices[group.x_pair[2]],mesh.vertices[group.x_pair[1]])
        local z=sub(mesh.vertices[group.z_pair[2]],mesh.vertices[group.z_pair[1]])
        unit(cross(unit(x),unit(z)))
        for _,limit in ipairs({group.yaw_limit,group.pitch_limit}) do
            assert(finite(limit) and limit>0 and limit<=45,'Aim limit must be 0..45 degrees')
        end
        assert(group.yaw_limit and group.pitch_limit,'Missing aim limits')
    end
    return rig
end
function Aim.apply(rig,section,vertices,normals,target,state,dt)
    for index,group in ipairs(rig.groups) do if group.section==section then
        local angles=state[index] or {yaw=0,pitch=0};state[index]=angles
        local weight=target and target.weight or 0
        if weight>0 or math.abs(angles.yaw)+math.abs(angles.pitch)>1e-5 then
            local a,b=vertices[group.x_pair[1]],vertices[group.x_pair[2]]
            local center={X=(a.X+b.X)/2,Y=(a.Y+b.Y)/2,Z=(a.Z+b.Z)/2}
            local x=unit(sub(b,a));local up=sub(vertices[group.z_pair[2]],vertices[group.z_pair[1]])
            local y=unit(cross(up,x));local z=unit(cross(x,y))
            local yaw,pitch=0,0
            if weight>0 then
                local direction=sub(target,center)
                local dx,dy,dz=dot(direction,x),dot(direction,y),dot(direction,z)
                yaw=clamp(math.atan(dy,dx),group.yaw_limit*math.pi/180)*weight
                pitch=clamp(math.atan(dz,math.sqrt(dx*dx+dy*dy)),group.pitch_limit*math.pi/180)*weight
            end
            local alpha=1-math.exp(-12*dt)
            angles.yaw=angles.yaw+(yaw-angles.yaw)*alpha
            angles.pitch=angles.pitch+(pitch-angles.pitch)*alpha
            local cy,sy,cp,sp=math.cos(angles.yaw),math.sin(angles.yaw),math.cos(angles.pitch),math.sin(angles.pitch)
            local function rotate(v)
                local vx,vy,vz=dot(v,x),dot(v,y),dot(v,z)
                local px,pz=cp*vx-sp*vz,sp*vx+cp*vz
                local xx,yy=cy*px-sy*vy,sy*px+cy*vy
                return {X=x.X*xx+y.X*yy+z.X*pz,Y=x.Y*xx+y.Y*yy+z.Y*pz,Z=x.Z*xx+y.Z*yy+z.Z*pz}
            end
            for _,i in ipairs(group.vertices) do
                local v=rotate(sub(vertices[i],center))
                vertices[i]={X=center.X+v.X,Y=center.Y+v.Y,Z=center.Z+v.Z}
                normals[i]=rotate(normals[i])
            end
        end
    end end
end
return Aim
