package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local A,G=require('animated_mesh'),require('animated_ground')
local function read(path)local f=assert(io.open(path,'rb'));local b=f:read('*a');f:close();return b end
local model=A.decode(read('mod/SkiEO-Foxes/Assets/fox.skan'))
local rig=G.decode(read('mod/SkiEO-Foxes/Assets/fox-ground.json'),model)
local function copy(poses)local result={};for i,p in ipairs(poses) do result[i]=A.copy(p) end;return result end
local function difference(a,b)
    local largest=0
    for i,p in ipairs(a) do for j,v in ipairs(p.vertices) do
        local q=b[i].vertices[j]
        largest=math.max(largest,math.sqrt((v.X-q.X)^2+(v.Y-q.Y)^2+(v.Z-q.Z)^2))
    end end
    return largest
end
local function raw(clip,time)
    local poses={}
    for i in ipairs(model.sections) do
        local v,n=A.sample(model,i,clip,time);poses[i]={vertices=v,normals=n}
    end
    return poses
end
local function unit_normals(poses)
    for _,pose in ipairs(poses) do for _,n in ipairs(pose.normals) do
        assert(math.abs(n.X*n.X+n.Y*n.Y+n.Z*n.Z-1)<1e-5,'blended shading normals lost normalization')
    end end
end
local state={}
local poses,weight=A.pose(model,'walk',.3,0,state)
assert(weight==1 and difference(poses,raw('walk',.3))<1e-6,'initial placement faded from a rest/bounding-box pose')
local before=copy(poses)
poses,weight=A.pose(model,'sniff',.2,1/30,state)
assert(weight==0 and difference(poses,before)<1e-6,'clip switch snapped the body, eyes or snow coat')
poses,weight=A.pose(model,'sniff',.2,.12,state)
unit_normals(poses)
assert(weight>0 and weight<1 and difference(poses,before)>1,'transition did not advance')
assert(difference(poses,raw('sniff',.2))>1,'transition jumped straight to the new clip')
before=copy(poses)
poses,weight=A.pose(model,'pounce',.4,1/30,state)
assert(weight==0 and difference(poses,before)<1e-6,'interrupted fade restarted an obsolete clip')
poses,weight=A.pose(model,'pounce',.4,.1,state)
assert(weight>0 and weight<1,'interrupted transition did not advance')
before=copy(poses);unit_normals(poses)
poses=A.pose(model,'pounce',.4,0,state)
assert(difference(poses,before)<1e-6,'zero elapsed time advanced a transition')
poses,weight=A.pose(model,'pounce',.4,.24,state)
assert(weight==1 and difference(poses,raw('pounce',.4))<1e-6,'transition never reached its destination')
unit_normals(poses)
local rendered=copy(poses);rendered[1].vertices[1].Z=-900
poses=A.pose(model,'idle',.2,1/30,state)
assert(poses[1].vertices[1].Z>=0,'a render correction contaminated the next source pose')
local other={};A.pose(model,'feed',.1,0,other);A.pose(model,'shake',.5,.1,other)
assert(difference(poses,raw('pounce',.4))<1e-6 and state.clip=='idle','two animals shared transition state')
local disabled={};A.pose(model,'walk',.2,0,disabled,0)
assert(difference(A.pose(model,'idle',.7,.1,disabled,0),raw('idle',.7))<1e-6,'zero duration did not disable blending')
assert(not pcall(A.pose,model,'idle',0,-1,{}))
assert(not pcall(A.pose,model,'idle',0,.1,{},2))

-- Check the final grounded mesh as well as authored poses: a continuous body
-- is insufficient if terrain adaptation snaps its paws on a clip switch.
local function surface(x,y)return {inside=true,z=200+x*.1+y*.2,ground=x*.1+y*.2,snow_cm=40,fresh_cm=0}end
for _,source in ipairs({'idle','walk','trot','sniff','play_bow'}) do
    for _,target in ipairs({'idle','walk','trot','sniff','pounce','shake'}) do
        for _,phase in ipairs({0,.3,.7}) do
            local animation,ground={},{}
            local function grounded(clip,time,dt)
                local pp,w=A.pose(model,clip,time,dt,animation)
                local bb=copy(pp)
                G.solve(rig,bb[1].vertices,bb[1].normals,clip,time,0,0,0,0,surface,ground,false,1,dt,w)
                return bb
            end
            local a=grounded(source,phase,0)
            if source~=target then
                local b=grounded(target,.2,1/30)
                assert(difference(a,b)<.01,'ground adaptation snapped at '..source..' -> '..target..': '..difference(a,b))
                for _=1,9 do
                    b=grounded(target,.2,1/30)
                    for _,pose in ipairs(b) do for _,v in ipairs(pose.vertices) do assert(v.Z==v.Z,'transition produced non-finite feet') end end
                end
            end
        end
    end
end
print('Animation transitions: source continuity, interruptions, pause, all sections, independent entities, normals and grounded paws OK')
