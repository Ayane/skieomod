package.path='mod/SkiEO-Foxes/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local F,J=require('behaviour'),require('json')
local config=F.config({count=1})
local function surface(fresh,heavy)
    return function()return {inside=true,ground=0,z=150,snow_cm=120,fresh_cm=fresh or 0,trail=false,heavy_snow=heavy}end
end
local state=F.new(config,{});local fox=state.foxes[1]
fox.wait=1000
assert(fox.coat==0,'fox spawned with a white coat in ordinary weather')
for _=1,1000 do F.step(state,config,.1,{hour=12},surface(20,false)) end
assert(fox.coat==0,'lying snow or light snowfall accumulated on fur')
for _=1,900 do F.step(state,config,.1,{hour=12},surface(20,true)) end
assert(fox.coat>.45 and fox.coat<.55,'heavy snowfall coating is not gradual')
local before=J.encode(state);F.step(state,config,.1,{hour=12,paused=true},surface(20,true))
assert(J.encode(state)==before,'paused weather/physics advanced')
for _=1,100 do F.step(state,config,.1,{hour=12},surface(20,false)) end
assert(fox.coat<.5,'fur did not gradually lose snow after the storm')
local old=J.decode(J.encode(state));old.foxes[1].coat_weather=nil;old.foxes[1].coat=1
assert(F.new(config,old).foxes[1].coat==0,'legacy automatic snow coating survived migration')
for _,height in ipairs({20,49,65}) do
    local _,duration=F.ballistic(height,0)
    assert(duration<.75,'fox hover lasts longer than a physical flight')
    local peak=F.ballistic(height,duration/2)
    assert(math.abs(peak-height)<1e-7 and F.ballistic(height,duration)<1e-7,'incorrect ballistic peak/landing')
    local t=duration*.35;local eps=.001
    local a,b,c=F.ballistic(height,t-eps),F.ballistic(height,t),F.ballistic(height,t+eps)
    assert(math.abs((a-2*b+c)/eps^2+980)<1e-5,'jump does not have terrestrial gravity')
end
-- Powder resistance changes forward speed, never flight duration/gravity.
local function traveller(mode)
    local s=F.new(config,{});local f=s.foxes[1]
    f.x,f.y,f.yaw,f.mode,f.clip,f.gait_clip,f.wait=0,0,0,mode,'walk','walk',1000
    f.target={x=15000,y=0};s.rodents[1].x=15000;s.rodents[1].y=0
    return s,f
end
local slow,a=traveller('roam');local fast,b=traveller('run')
for _=1,15 do F.step(slow,config,.05,{hour=12},surface(60));F.step(fast,config,.05,{hour=12},surface(60)) end
assert(b.x>a.x*2,'quiet fox never runs faster than a walk')
assert(a.flight and b.flight and math.abs(a.flight.duration-b.flight.duration)<1e-8,'forward speed stretched a bound into slow motion')
local snapshot={jump=a.jump,flight={id=a.flight.id,height=a.flight.height,elapsed=a.flight.elapsed,duration=a.flight.duration}}
F.step(slow,config,.05,{hour=12},surface(60))
if a.flight.id==snapshot.flight.id then
 local rendered=F.render_jump(a,snapshot,.5)
 local expected=F.ballistic(a.flight.height,(snapshot.flight.elapsed+a.flight.elapsed)/2)
 assert(math.abs(rendered-expected)<1e-8,'rendering reverted to a linear/sinusoidal flight')
end
print('Fox weather/physics: heavy local snowfall only, gradual fur coating, legacy migration, pause, real gravity, speed-independent flight and running OK')
