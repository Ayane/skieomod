package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Animated,Aim,Json=require('animated_mesh'),require('animated_aim'),require('json')
local function read(path)local f=assert(io.open(path,'rb'));local b=f:read('*a');f:close();return b end
local model=Animated.decode(read('mod/SkiEO-Foxes/Assets/fox.skan'))
local source=read('mod/SkiEO-Foxes/Assets/fox-eyes.json')
local rig=Aim.decode(source,model)
assert(#rig.groups==2,'both eyes must have independent orbits')
local function distance(a,b)return math.sqrt((a.X-b.X)^2+(a.Y-b.Y)^2+(a.Z-b.Z)^2)end
local function center(v,g)
    local a,b=v[g.x_pair[1]],v[g.x_pair[2]]
    return {X=(a.X+b.X)/2,Y=(a.Y+b.Y)/2,Z=(a.Z+b.Z)/2}
end
for _,clip in ipairs({'idle','walk','sniff','pounce','feed'}) do
    local base=Animated.sample(model,2,clip,.4)
    local v,n=Animated.sample(model,2,clip,.4);local state={}
    Aim.apply(rig,2,v,n,nil,state,.1)
    assert(Json.encode(v)==Json.encode(base),'distant gaze changed the animation')
    Aim.apply(rig,2,v,n,{X=100,Y=100,Z=70,weight=1},state,.1)
    local changed=false
    for i,g in ipairs(rig.groups) do
        local pivot=center(base,g)
        assert(distance(pivot,center(v,g))<1e-7,'eyeball detached from its animated orbit')
        for _,j in ipairs(g.vertices) do
            changed=changed or distance(v[j],base[j])>.01
            assert(math.abs(distance(v[j],pivot)-distance(base[j],pivot))<1e-7,'gaze deformed the globe')
            assert(math.abs(distance(n[j],{X=0,Y=0,Z=0})-1)<1e-5,'gaze broke normals')
        end
        assert(math.abs(state[i].yaw)<=g.yaw_limit*math.pi/180 and math.abs(state[i].pitch)<=g.pitch_limit*math.pi/180)
    end
    assert(changed,'gaze left the pupils static')
    for _=1,20 do v,n=Animated.sample(model,2,clip,.4);Aim.apply(rig,2,v,n,nil,state,.1) end
    for i in ipairs(v) do assert(distance(v[i],base[i])<.001,'distant gaze did not settle back to neutral') end
    local body,bn=Animated.sample(model,1,clip,.4);local before=Json.encode(body)
    Aim.apply(rig,1,body,bn,{X=100,Y=100,Z=70,weight=1},state,.1)
    assert(Json.encode(body)==before,'eye control deformed the body')
end
local bad=Json.decode(source);bad.groups[2].vertices[1]=bad.groups[1].vertices[1]
assert(not pcall(Aim.decode,Json.encode(bad),model),'overlapping groups accepted')
bad=Json.decode(source);bad.groups[1].yaw_limit=90
assert(not pcall(Aim.decode,Json.encode(bad),model),'unbounded rotation accepted')
bad=Json.decode(source);bad.groups[1].x_pair={1,1}
assert(not pcall(Aim.decode,Json.encode(bad),model),'degenerate anchors accepted')
print('Animated gaze: both orbits follow clips, sphere shape and normals preserved, body untouched, bounded smooth rotation and distance fade OK')
