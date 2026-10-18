-- Small behavioural details are visible near the camera. Looking does not
-- change the hunt's random generator or persistent movement state.
local Gaze={}
function Gaze.target(fox,prey,camera,ground,index,surface)
    if not camera then return nil,0 end
    local distance=math.sqrt((camera.x-fox.x)^2+(camera.y-fox.y)^2+(camera.z-ground.z-49)^2)
    local weight=math.max(0,math.min(1,(1200-distance)/800))
    if weight==0 then return nil,0 end
    local target
    if fox.mode=='alert' then target=fox.threat
    elseif fox.mode=='flee' or fox.mode=='shelter' or fox.mode=='search' then target=fox.target
    elseif fox.mode=='stalk' or fox.mode=='listen' then target=prey
    elseif fox.mode=='pounce' or fox.mode=='feed' then target=fox.target
    elseif fox.mode=='cross' then target=fox.route and fox.route[fox.waypoint]
    elseif fox.mode=='roam' then target=fox.target end
    if target then
        local s=surface(target.x,target.y)
        local hunting=fox.mode=='stalk' or fox.mode=='listen' or fox.mode=='pounce' or fox.mode=='feed'
        return {x=target.x,y=target.y,z=(s.inside and s.z or ground.z)+(hunting and 4 or 45)},weight
    end
    -- Brief attention to a nearby observer, then two quiet scanning fixations.
    -- Each animal has a different phase; eyes settle instead of oscillating.
    local phase=(fox.time+index*1.7)%8
    if distance<600 and phase<1.4 then return camera,weight end
    local offset=phase<4.5 and -12 or 10
    local angle=(fox.yaw+offset)*math.pi/180
    local x,y=fox.x+math.cos(angle)*300,fox.y+math.sin(angle)*300
    local s=surface(x,y)
    return {x=x,y=y,z=(s.inside and s.z or ground.z)+(phase<4.5 and 35 or 65)},weight
end
return Gaze
