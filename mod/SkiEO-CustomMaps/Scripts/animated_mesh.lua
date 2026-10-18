-- Portable, baked vertex animation. No cooked Unreal assets or native pointers
-- cross the map API. SKAN meshes share immutable frames/materials per session.
local Animated = {}
local function finite(v) return type(v)=='number' and v==v and math.abs(v)<1e8 end
function Animated.decode(bytes)
    assert(type(bytes)=='string' and #bytes<=32*1024^2,'Animated mesh exceeds 32 MiB')
    local magic,version,count,clips,offset=string.unpack('<c4I4I4I4',bytes)
    assert(magic=='SKAN' and version==1 and count>=1 and count<=8 and clips>=1 and clips<=16,'Invalid SKAN header')
    local result={sections={},bytes=bytes}
    local total=0
    for section=1,count do
        local nv,ni;nv,ni,offset=string.unpack('<I4I4',bytes,offset)
        total=total+nv
        assert(nv>=3 and total<=12000 and ni>=3 and ni%3==0 and ni<=72000,'Invalid SKAN topology')
        local mesh={vertices={},normals={},uv={},triangles={},clips={},count=nv}
        for i=1,nv do
            local x,y,z,nx,ny,nz,u,v
            x,y,z,nx,ny,nz,u,v,offset=string.unpack('<ffffffff',bytes,offset)
            for _,n in ipairs({x,y,z,nx,ny,nz,u,v}) do assert(finite(n),'Invalid SKAN vertex') end
            mesh.vertices[i]={X=x,Y=y,Z=z};mesh.normals[i]={X=nx,Y=ny,Z=nz};mesh.uv[i]={X=u,Y=v}
        end
        for i=1,ni do
            local index;index,offset=string.unpack('<I4',bytes,offset)
            assert(index<nv,'SKAN index out of range');mesh.triangles[i]=index
        end
        for _=1,clips do
            local name,duration,frames,loop
            name,duration,frames,loop,offset=string.unpack('<c16fI4I4',bytes,offset)
            name=name:gsub('%z.*','')
            assert(name:match('^[a-z][a-z0-9_]*$') and not mesh.clips[name] and finite(duration)
                and duration>0 and duration<=60 and frames>=2 and frames<=120 and loop<=1,'Invalid SKAN clip')
            local length=frames*nv*24
            assert(offset+length-1<=#bytes,'Truncated SKAN animation')
            -- Validate all samples once, before passing any float to Unreal.
            for p=offset,offset+length-1,4 do assert(finite(string.unpack('<f',bytes,p)),'Invalid SKAN animation sample') end
            mesh.clips[name]={duration=duration,frames=frames,loop=loop==1,offset=offset}
            offset=offset+length
        end
        result.sections[section]=mesh
    end
    assert(offset==#bytes+1,'Trailing SKAN data')
    return result
end
local function frame_data(model,mesh,clip,index)
    clip.cache=clip.cache or {}
    local values=clip.cache[index]
    if values then return values end
    values={}
    for i=1,mesh.count do
        local x,y,z,nx,ny,nz=string.unpack('<ffffff',model.bytes,clip.offset+(index*mesh.count+i-1)*24)
        local p=(i-1)*6
        values[p+1]=x;values[p+2]=y;values[p+3]=z
        values[p+4]=nx;values[p+5]=ny;values[p+6]=nz
    end
    -- Only the two neighbours are needed, even for a very long clip.
    clip.cache[index]=values
    local keys={};for key in pairs(clip.cache) do keys[#keys+1]=key end
    if #keys>2 then
        table.sort(keys,function(a,b)return math.abs(a-index)>math.abs(b-index)end)
        clip.cache[keys[1]]=nil
    end
    return values
end
function Animated.sample(model,section,name,seconds,buffer)
    assert(finite(seconds) and seconds>=0,'Invalid animation time')
    local mesh=model.sections[section];local clip=assert(mesh.clips[name],'Unknown animation: '..tostring(name))
    local frame=clip.loop and (seconds%clip.duration)/clip.duration*clip.frames
        or math.min(seconds/clip.duration,1)*(clip.frames-1)
    local a=math.floor(frame);local b=clip.loop and (a+1)%clip.frames or math.min(a+1,clip.frames-1)
    local t=frame-a
    local aa,bb=frame_data(model,mesh,clip,a),frame_data(model,mesh,clip,b)
    buffer=buffer or {vertices={},normals={}}
    local vertices,normals=buffer.vertices,buffer.normals
    for i=1,mesh.count do
        local p=(i-1)*6
        local v=vertices[i] or {};vertices[i]=v
        v.X=aa[p+1]+(bb[p+1]-aa[p+1])*t
        v.Y=aa[p+2]+(bb[p+2]-aa[p+2])*t
        v.Z=aa[p+3]+(bb[p+3]-aa[p+3])*t
        local nx,ny,nz=aa[p+4]+(bb[p+4]-aa[p+4])*t,aa[p+5]+(bb[p+5]-aa[p+5])*t,aa[p+6]+(bb[p+6]-aa[p+6])*t
        local length=math.max(math.sqrt(nx*nx+ny*ny+nz*nz),1e-8)
        local n=normals[i] or {};normals[i]=n
        n.X=nx/length;n.Y=ny/length;n.Z=nz/length
    end
    return vertices,normals
end
-- Authored poses stay separate from the renderer's ground/eye corrections.
-- A change, including one interrupting another fade, starts from the last
-- displayed authored pose rather than restarting an obsolete source clip.
function Animated.copy(source,buffer)
    buffer=buffer or {vertices={},normals={}}
    for _,key in ipairs({'vertices','normals'}) do
        for i,p in ipairs(source[key]) do
            local q=buffer[key][i] or {};buffer[key][i]=q
            q.X=p.X;q.Y=p.Y;q.Z=p.Z
        end
    end
    return buffer
end
function Animated.pose(model,name,seconds,dt,state,duration)
    duration=duration or .24
    assert(finite(dt) and dt>=0 and dt<=1,'Invalid animation timestep')
    assert(finite(duration) and duration>=0 and duration<=1,'Invalid animation blend duration')
    local changed=state.clip and state.clip~=name
    if changed and duration>0 then
        state.source=state.source or {}
        -- Keep the reusable copied section buffers on this entity only.
        for i,pose in ipairs(state.poses) do state.source[i]=Animated.copy(pose,state.source[i]) end
        state.elapsed=0
    elseif state.source then state.elapsed=state.elapsed+dt end
    state.clip=name;state.poses=state.poses or {}
    local t=state.source and duration>0 and math.min(1,state.elapsed/duration) or 1
    local weight=t*t*t*(t*(t*6-15)+10)
    state.weight=weight
    for i in ipairs(model.sections) do
        local pose=state.poses[i] or {vertices={},normals={}};state.poses[i]=pose
        Animated.sample(model,i,name,seconds,pose)
        if weight<1 then
            local source=state.source[i]
            for j,p in ipairs(pose.vertices) do
                local q=source.vertices[j]
                p.X=q.X+(p.X-q.X)*weight;p.Y=q.Y+(p.Y-q.Y)*weight;p.Z=q.Z+(p.Z-q.Z)*weight
                local n,a=pose.normals[j],source.normals[j]
                local nx,ny,nz=a.X+(n.X-a.X)*weight,a.Y+(n.Y-a.Y)*weight,a.Z+(n.Z-a.Z)*weight
                local length=math.sqrt(nx*nx+ny*ny+nz*nz)
                if length>1e-8 then n.X=nx/length;n.Y=ny/length;n.Z=nz/length
                else n.X=a.X;n.Y=a.Y;n.Z=a.Z end
            end
        end
    end
    if t==1 then state.source=nil end
    return state.poses,weight
end
return Animated
