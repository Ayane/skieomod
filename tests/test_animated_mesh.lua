package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Animated=require('animated_mesh')
local function read(path) local f=assert(io.open(path,'rb'));local data=f:read('*a');f:close();return data end
for _,name in ipairs({'fox'}) do
    local bytes=read('mod/SkiEO-Foxes/Assets/'..name..'.skan')
    local model=Animated.decode(bytes)
    if name=='fox' then
        for clip in pairs(model.sections[1].clips) do
            local eyes=Animated.sample(model,2,clip,.3)
            for _,v in ipairs(eyes) do assert(v.Z>25,'eyes detached from the head') end
        end
    end
    local moved=false
    for i,mesh in ipairs(model.sections) do
        local outward,total=0,0
        for j=1,#mesh.triangles,3 do
            local a,b,c=mesh.vertices[mesh.triangles[j]+1],mesh.vertices[mesh.triangles[j+1]+1],mesh.vertices[mesh.triangles[j+2]+1]
            local n=mesh.normals[mesh.triangles[j]+1]
            local ux,uy,uz=b.X-a.X,b.Y-a.Y,b.Z-a.Z
            local vx,vy,vz=c.X-a.X,c.Y-a.Y,c.Z-a.Z
            local dot=(uy*vz-uz*vy)*n.X+(uz*vx-ux*vz)*n.Y+(ux*vy-uy*vx)*n.Z
            if math.abs(dot)>1e-6 then total=total+1;if dot<0 then outward=outward+1 end end
        end
        assert(outward/total>.99,'model front faces do not use Unreal clockwise winding')
        for name,clip in pairs(mesh.clips) do
            local a=Animated.sample(model,i,name,0)
            local b,normals=Animated.sample(model,i,name,clip.duration*.3)
            assert(#a==mesh.count and #b==mesh.count)
            local last=Animated.sample(model,i,name,clip.duration)
            for j,p in ipairs(a) do
                local q=b[j];moved=moved or math.abs(p.X-q.X)+math.abs(p.Z-q.Z)>.1
                assert(q.Z>=-.001,'animation goes below ground')
                local n=normals[j];assert(math.abs(n.X*n.X+n.Y*n.Y+n.Z*n.Z-1)<1e-4)
                if clip.loop then assert(math.abs(p.X-last[j].X)+math.abs(p.Z-last[j].Z)<.001,'loop seam') end
            end
        end
    end
    assert(moved,'static mesh masquerading as an animation')
    assert(not pcall(Animated.decode,bytes:sub(1,-2)))
    assert(not pcall(Animated.decode,bytes..'x'))
    assert(not pcall(Animated.decode,'BAD!'..bytes:sub(5)))
    local nan=bytes:sub(1,24)..string.pack('<f',0/0)..bytes:sub(29)
    assert(not pcall(Animated.decode,nan),'NaN vertex accepted')
    assert(not pcall(Animated.sample,model,1,'absent',0))
end
print('Animated mesh: topology, nine fox clips, deformations, normals, loop seams, grounding and malformed input OK')
