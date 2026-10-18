package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;mod/SkiEO-Foxes/Scripts/?.lua;'..package.path
local F,J=require('behaviour'),require('json')
local config=F.config({count=1})
local function terrain(x,y)return {inside=math.abs(x)<20000 and math.abs(y)<20000,trail=false,ground=0,z=100,snow_cm=100,fresh_cm=0}end
local function threat(kind,tx,ty,radius,enabled)
 return function(x,y)
  local s=terrain(x,y);local d=math.sqrt((x-tx)^2+(y-ty)^2)
  if enabled() and d<radius*1.5 then s.disturbance={kind=kind,x=tx,y=ty,distance=d,radius=radius} end
  return s
 end
end
local active=true
local env=threat('person',-6000,0,1800,function()return active end)
local state=F.new(config,{});local fox=state.foxes[1]
fox.x,fox.y,fox.yaw,fox.mode,fox.clip,fox.time,fox.wait=-5600,0,180,'feed','feed',0,100
F.step(state,config,.1,{hour=12},env)
assert(fox.mode=='flee' and fox.purpose=='shelter','human proximity did not interrupt feeding')
local distance=math.abs(fox.x+6000)
for _=1,120 do F.step(state,config,.1,{hour=12},env) end
assert(math.abs(fox.x+6000)>distance+1000,'fox did not retreat from the person')
local before=J.encode(state)
F.step(state,config,.1,{hour=12,paused=true},env)
assert(before==J.encode(state),'fear moved a paused fox')
local restored=F.new(config,J.decode(before))
active=false
for _=1,100 do
 F.step(state,config,.1,{hour=12},env);F.step(restored,config,.1,{hour=12},env)
end
assert(J.encode(state)==J.encode(restored),'fear/save restore lost deterministic precision')
assert(fox.mode=='rest','fox resumed wandering immediately after escape')
assert(fox.refuge and fox.refuge_time>90,'fox forgot the quiet refuge immediately')
-- A camera is an observation tool, independent of human proximity.
state=F.new(config,{});fox=state.foxes[1];fox.wait=100
F.step(state,config,.1,{hour=12,camera={x=fox.x,y=fox.y,z=100}},terrain)
assert(fox.mode=='idle','debug camera was treated as a person')
-- Operating lift corridors suppress a hunt and a night crossing.
state=F.new(config,{});fox=state.foxes[1]
fox.x,fox.y,fox.mode,fox.wait=-6000,0,'listen',1
env=threat('lift',-5800,0,1400,function()return true end)
F.step(state,config,.1,{hour=22},env)
assert(fox.mode=='flee' and fox.threat.kind=='lift','active lift did not interrupt hunting')
state=F.new(config,{});fox=state.foxes[1];fox.x,fox.y,fox.wait,fox.hunger=-6000,0,0,1
env=threat('lift',-2500,0,1400,function()return true end)
F.step(state,config,.1,{hour=22},env)
assert(fox.mode~='cross','fox entered a noisy crossing route')
-- Longer observation shows feeding, listening and rest rather than arbitrary
-- patrol points, with smooth steering and persistent physiological drives.
state=F.new(config,{});local modes={}
for _=1,5000 do
 local f=state.foxes[1];local yaw=f.yaw
 F.step(state,config,.1,{hour=12},terrain);modes[f.mode]=true
 assert(math.abs((f.yaw-yaw+180)%360-180)<30,'heading snapped during normal foraging')
 assert(f.mode~='roam' and f.mode~='cross','daytime search fell back to random patrol')
end
assert(modes.search and modes.listen and modes.feed and modes.rest and state.catches>1,'foraging never completed meaningful feeding/rest cycles')
print('Fox fear: people and active lifts override hunting, quiet crossings, escape/rest, pause, save precision, camera independence and purposeful foraging OK')
