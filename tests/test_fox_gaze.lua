package.path='mod/SkiEO-Foxes/Scripts/?.lua;'..package.path
local Gaze=require('gaze')
local fox={x=0,y=0,yaw=0,time=0,mode='stalk'}
local prey={x=150,y=20};local ground={z=100}
local function surface()return {inside=true,z=100}end
local camera={x=200,y=-100,z=160}
local target,weight=Gaze.target(fox,prey,camera,ground,1,surface)
assert(target.x==prey.x and target.y==prey.y and target.z==104 and weight==1,'hunt did not track prey')
fox.mode='feed';fox.target={x=80,y=0};prey.x=900
target=Gaze.target(fox,prey,camera,ground,1,surface)
assert(target.x==80,'feeding gaze followed a respawned rodent')
fox.mode='cross';fox.route={{x=400,y=0},{x=800,y=0}};fox.waypoint=2
assert(Gaze.target(fox,prey,camera,ground,1,surface).x==800,'crossing gaze missed the next bank')
fox.mode='idle';fox.time=6.5
assert(Gaze.target(fox,prey,camera,ground,1,surface)==camera,'nearby observer never received attention')
fox.time=1;target=Gaze.target(fox,prey,camera,ground,1,surface)
assert(target~=camera,'idle stare never looked away')
target,weight=Gaze.target(fox,prey,{x=800,y=0,z=149},ground,1,surface)
assert(target and math.abs(weight-.5)<1e-6,'distance fade is not gradual')
target,weight=Gaze.target(fox,prey,{x=1300,y=0,z=149},ground,1,function()error('distant gaze sampled terrain')end)
assert(not target and weight==0,'distant camera still animated gaze')
assert(Gaze.target(fox,prey,nil,ground,1,surface)==nil)
print('Fox gaze: prey, feeding location, travel bank, observer attention, idle fixations and camera distance OK')
