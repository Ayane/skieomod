package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;mod/SkiEO-Foxes/Scripts/?.lua;'..package.path
local Foxes,Json=require('behaviour'),require('json')
local config=Foxes.config({count=2,seed=17})
local function terrain(x,y)
    return {inside=math.abs(x)<20000 and math.abs(y)<20000,ground=0,z=30,snow_cm=12,trail=math.abs(x)<1600}
end
local state=Foxes.new(config,{})
assert(Foxes.new(config,state)==state,'restore reset the population')
assert(Foxes.night(20) and Foxes.night(5.99) and not Foxes.night(6) and not Foxes.night(19.99))
local before=Json.encode(state)
assert(#Foxes.step(state,config,.1,{hour=22,paused=true},terrain)==0 and Json.encode(state)==before,'pause moved wildlife')
local restored=Json.decode(before)
local crossings,leaps=0,0
for i=1,14000 do
    local result=Foxes.step(state,config,.1,{hour=22},terrain)
    Foxes.step(restored,config,.1,{hour=22},terrain)
    assert(#result==0,'AI emitted a distance-based track without paw collision')
    for _,f in ipairs(state.foxes) do
        if f.mode=='cross' then crossings=crossings+1 end
        if (f.jump or 0)>5 then leaps=leaps+1 end
        assert(terrain(f.x,f.y).inside,'escaped terrain')
    end
end
local function equal(a,b)
    if type(a)=='number' then return math.abs(a-b)<1e-6 end
    if type(a)~='table' then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
assert(equal(state,restored),'save/restore changed random sequence')
assert(crossings>0 and leaps>0 and state.catches>0,'night hunt did not complete')
state=Foxes.new(config,{})
for _=1,6000 do
    Foxes.step(state,config,.1,{hour=12},terrain)
    for _,f in ipairs(state.foxes) do assert(f.x< -1600 and f.mode~='cross','daytime piste entry') end
end
local function dry(x,y) local t=terrain(x,y);t.snow_cm=0;return t end
for _=1,3000 do assert(#Foxes.step(state,config,.1,{hour=22},dry)==0,'footprints without snow') end
local function crossing(x)
    local saved=Foxes.new(Foxes.config({count=1}),{})
    local f=saved.foxes[1]
    f.x=x;f.y=0;f.mode='cross';f.destination='meadow';f.waypoint=2
    f.route={{x=-2500,y=0},{x=2500,y=0},{x=6000,y=0}}
    return saved,f
end
local dawn,f=crossing(0)
for _=1,120 do Foxes.step(dawn,config,.1,{hour=6},terrain) end
assert(f.area=='meadow' and f.x>=2490 and f.mode=='idle','dawn did not finish at the destination bank')
dawn,f=crossing(-2300)
Foxes.step(dawn,config,.1,{hour=6},terrain)
assert(f.x==-2300 and f.mode=='idle' and f.area=='forest','crossing entered a piste after dawn')
dawn,f=crossing(-1700)
f.mode='pounce';f.time=1.1;f.wait=1.2;f.launch={x=-1700,y=0};f.target={x=-1500,y=0}
dawn.rodents[1].x=-1500;dawn.rodents[1].y=0
Foxes.step(dawn,config,.1,{hour=12},terrain)
assert(dawn.catches==0 and dawn.rodents[1].hidden==0 and f.x==-1700,'caught a rodent across a blocked piste')
assert(not pcall(Foxes.config,{count=9}))
assert(not pcall(Foxes.config,{habitats={ {forest={x=0,y=0,radius=0}} }}))
assert(not pcall(Foxes.step,state,config,1,{hour=22},terrain))
-- Animation is a function of distance, including slow turns and blocked paths.
local walking=Foxes.new(Foxes.config({count=1}),{});local f=walking.foxes[1]
f.x,f.y,f.yaw,f.mode,f.clip,f.gait_clip,f.anim_time= -6000,0,0,'roam','walk','walk',0
f.target={x=-5000,y=0}
local function snow(fresh)return function(x,y)return {inside=true,trail=false,ground=x*.2,z=x*.2+100,snow_cm=100+fresh,fresh_cm=fresh}end end
local x=f.x;Foxes.step(walking,Foxes.config({count=1}),.1,{hour=12},snow(0))
assert(math.abs(f.anim_time-math.sqrt((f.x-x)^2+(f.x-x)^2*.04)/36)<1e-7,'movement and animation speeds diverge on slopes')
assert(f.clip=='walk' and f.jump==0,'compact snow caused locomotion bounds')
Foxes.step(walking,Foxes.config({count=1}),.1,{hour=12},snow(20));assert(f.clip=='walk','partially buried legs already bound')
Foxes.step(walking,Foxes.config({count=1}),.1,{hour=12},snow(60));assert(f.clip=='bound','fully buried legs did not use bounds')
local t=f.anim_time
local function blocked()return {inside=false,trail=false,ground=0,z=0,snow_cm=160,fresh_cm=60}end
-- A blocked attempt ends roaming; it must never advance a locomotion cycle.
Foxes.step(walking,Foxes.config({count=1}),.1,{hour=12},blocked)
assert(f.moved==0,'blocked gait still travelled')
print('Foxes: deterministic saves, pause, night crossings, hunts, distance-driven gait and bounds only with fully buried legs OK')
