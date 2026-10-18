package.path='mod/SkiEO-Foxes/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Foxes=require('behaviour');local json=require('json')
local config=Foxes.config({count=2})
local function surface()return {inside=true,trail=false,ground=0,z=150,snow_cm=120}end
local state=Foxes.new(config,{})
assert(math.sqrt((state.foxes[1].x-state.foxes[2].x)^2+(state.foxes[1].y-state.foxes[2].y)^2)>=800,'new foxes cluster')
local a,b=state.foxes[1],state.foxes[2]
a.x,a.y,b.x,b.y=-6050,0,-5950,0
a.wait,b.wait=100,100
Foxes.step(state,config,.1,{hour=12},surface)
assert(a.mode=='play' and b.mode=='play' and a.partner==2 and b.partner==1,'meeting did not start mutual play')
local before=json.encode(state)
for _=1,20 do assert(#Foxes.step(state,config,.1,{hour=12,paused=true},surface)==0) end
assert(json.encode(state)==before,'pause advanced social animation or state')
local saw_trot=false
for _=1,75 do
 Foxes.step(state,config,.1,{hour=12},surface)
 saw_trot=saw_trot or a.clip=='trot'
 assert(a.clip~='bound' and b.clip~='bound','ordinary play used powder bounds on compact snow')
end
assert(saw_trot and a.mode=='disperse' and b.mode=='disperse','play never ended in separation')
local dax,day=a.target.x-a.x,a.target.y-a.y
local dbx,dby=b.target.x-b.x,b.target.y-b.y
assert(dax*dbx+day*dby<0,'departures are not in opposite directions')
for _=1,55 do Foxes.step(state,config,.1,{hour=12},surface) end
assert(math.sqrt((a.x-b.x)^2+(a.y-b.y)^2)>1200,'foxes stayed grouped after playing')
assert(a.social_cooldown>0 and b.social_cooldown>0,'social cooldown missing')
-- Snow shedding is a finite animation, removes the coat, and is frozen in pause.
a.mode,a.clip,a.time,a.wait,a.coat='shake','shake',0,1.6,1
for _=1,8 do Foxes.step(state,config,.1,{hour=12},surface) end
assert(a.coat<.02 and a.shed,'shake did not shed snow')
before=json.encode(state);Foxes.step(state,config,.1,{hour=12,paused=true},surface)
assert(json.encode(state)==before,'paused shake kept moving')
for _=1,10 do Foxes.step(state,config,.1,{hour=12},surface) end
assert(a.mode=='idle' and a.shake_age<1 and not a.shed,'shake never completed')
print('Fox social behaviour: initial separation, mutual play, ordinary trot, opposite departures, cooldown, snow shedding and pause OK')
