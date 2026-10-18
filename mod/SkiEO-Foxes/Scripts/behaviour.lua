-- Deterministic example AI, independent of UE4SS. Distances are centimetres;
-- animation/movement use simulation seconds, and access to pistes uses game time.
local Foxes={}
local GAITS={walk={stride=36,duration=1},trot={stride=50,duration=.65},bound={stride=60,duration=.7}}
local GRAVITY=980 -- cm/s², independently of movement speed or snow resistance
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<1e7 end
local function distance(a,b) return math.sqrt((a.x-b.x)^2+(a.y-b.y)^2) end
function Foxes.night(hour) return hour>=20 or hour<6 end
function Foxes.ballistic(height,seconds)
    local velocity=math.sqrt(2*GRAVITY*height)
    return math.max(0,velocity*seconds-GRAVITY*seconds*seconds/2),2*velocity/GRAVITY
end
local function launch(fox,height)
    local _,duration=Foxes.ballistic(height,0)
    fox.leap_id=(fox.leap_id or 0)+1
    fox.flight={id=fox.leap_id,height=height,duration=duration,elapsed=0}
    fox.jump=0
end
function Foxes.render_jump(fox,previous,alpha)
    local a,b=previous.flight,fox.flight
    local step=fox.motion_dt or .1
    if a and b and a.id==b.id then
        if a.elapsed>=a.duration then return 0 end
        return Foxes.ballistic(b.height,a.elapsed+step*alpha)
    elseif b and b.elapsed>0 then
        return Foxes.ballistic(b.height,math.max(0,b.elapsed-step*(1-alpha)))
    end
    return previous.jump+((fox.jump or 0)-previous.jump)*alpha
end
local function random(state)
    state.seed=(state.seed*48271)%2147483647
    return state.seed/2147483647
end
local function point(state,area)
    local a=random(state)*2*math.pi;local r=math.sqrt(random(state))*area.radius
    return {x=area.x+math.cos(a)*r,y=area.y+math.sin(a)*r}
end
local function risk(surface)
    local d=surface.disturbance
    return d and math.max(0,1-d.distance/(d.radius*1.5)) or 0
end
local function quiet(surface)return surface.inside and not surface.trail and risk(surface)<.15 end
local function clear_point(state,area,env,fox)
    local best,score
    for _=1,16 do
        local p=point(state,area);local s=env(p.x,p.y)
        if quiet(s) then
            local value=fox and distance(p,fox) or 0
            if not score or value<score then best,score=p,value end
        end
    end
    return best
end
function Foxes.config(options)
    options=options or {}
    local config={count=options.count or 4,seed=options.seed or 7521,gaits=GAITS,leg_height_cm=31.68,habitats=options.habitats or {
        {forest={x=-6000,y=0,radius=1800},meadow={x=6000,y=0,radius=1800},
         crossing={{x=-2500,y=0},{x=2500,y=0}}}}}
    assert(finite(config.count) and config.count%1==0 and config.count>=1 and config.count<=8,'Fox count must be 1..8')
    assert(finite(config.seed) and config.seed%1==0 and config.seed>0,'Invalid fox seed')
    assert(type(config.habitats)=='table' and #config.habitats>0 and #config.habitats<=8,'Foxes need 1..8 habitats')
    for _,h in ipairs(config.habitats) do
        for _,area in ipairs({h.forest,h.meadow}) do
            assert(type(area)=='table' and finite(area.x) and finite(area.y) and finite(area.radius)
                and area.radius>=100 and area.radius<=10000,'Invalid fox habitat')
        end
        assert(h.forest and h.meadow and type(h.crossing)=='table' and #h.crossing==2,'A habitat needs a forest, meadow and two crossing banks')
        for _,p in ipairs(h.crossing) do assert(finite(p.x) and finite(p.y),'Invalid crossing bank') end
    end
    return config
end
function Foxes.new(config,saved)
    if saved.version==2 and type(saved.foxes)=='table' and #saved.foxes==config.count then
        for _,f in ipairs(saved.foxes) do
            f.anim_time=f.anim_time or f.time;f.gait_clip=f.gait_clip or f.clip
            f.hunger=f.hunger or .45;f.fatigue=f.fatigue or .15;f.trip_cooldown=f.trip_cooldown or 0
            if not f.coat_weather then f.coat=0;f.coat_weather=true end
        end
        return saved
    end
    saved.version=2;saved.seed=config.seed;saved.foxes={};saved.rodents={};saved.catches=0
    for i=1,config.count do
        local habitat=(i-1)%#config.habitats+1
        local p
        for attempt=1,40 do
            p=point(saved,config.habitats[habitat].forest)
            local clear=true
            for _,other in ipairs(saved.foxes) do if distance(p,other)<800 then clear=false end end
            if clear then break end
        end
        saved.foxes[i]={x=p.x,y=p.y,yaw=0,habitat=habitat,area='forest',mode='idle',time=0,
            wait=2+random(saved)*5,clip='idle',anim_time=0,gait_clip='idle',coat=0,coat_weather=true,shake_age=20+i*7,social_cooldown=0,
            hunger=.4+random(saved)*.2,fatigue=.15,trip_cooldown=0,purpose='forage'}
        p=point(saved,config.habitats[habitat].forest)
        saved.rodents[i]={x=p.x,y=p.y,yaw=0,hidden=0,clip='idle',time=0}
    end
    return saved
end
local function mode(fox,name,clip,wait)
    fox.mode=name;fox.clip=clip;fox.time=0;fox.wait=wait or 0;fox.speed=0
    if not fox.flight or fox.flight.elapsed>=fox.flight.duration then fox.jump=0 end
end
local function escape(state,fox,h,threat,env)
    local angle=math.atan(fox.y-threat.y,fox.x-threat.x)
    local best,score
    for n=1,11 do
        local a=angle+(n==1 and 0 or (n%2==0 and 1 or -1)*math.ceil((n-1)/2)*.22)
        local p={x=fox.x+math.cos(a)*2400,y=fox.y+math.sin(a)*2400}
        local s=env(p.x,p.y)
        if s.inside and not s.trail then
            local value=risk(s)*5000+distance(p,h.forest)*.08+math.abs(a-angle)*300
            if not score or value<score then best,score=p,value end
        end
    end
    fox.target=best or {x=fox.x+math.cos(angle)*300,y=fox.y+math.sin(angle)*300}
    fox.threat={x=threat.x,y=threat.y,kind=threat.kind};fox.purpose='shelter'
    fox.partner=nil;fox.route=nil;fox.social_cooldown=90;fox.safe_time=0
    mode(fox,'flee','trot')
end
local function move(state,fox,target,speed,dt,env,allow_trail,prints)
    local d=distance(fox,target)
    if d<10 then return true end
    local desired=math.atan(target.y-fox.y,target.x-fox.x)*180/math.pi
    local delta=(desired-fox.yaw+180)%360-180
    -- Steer along the body's direction and slow down through tight turns.
    -- Updating yaw alone would make the fox slide sideways toward its target.
    local turning=fox.mode=='flee' and 200 or 95
    local desired_turn=math.max(-turning,math.min(turning,delta*3))
    fox.turn_rate=(fox.turn_rate or 0)+(desired_turn-(fox.turn_rate or 0))*(1-math.exp(-dt/.25))
    local turn=fox.turn_rate*dt
    if turn*delta>0 and math.abs(turn)>math.abs(delta) then turn=delta end
    fox.yaw=fox.yaw+turn
    local angle=fox.yaw*math.pi/180;local dx,dy=math.cos(angle),math.sin(angle)
    local previous=env(fox.x,fox.y)
    local fresh=previous.fresh_cm or 0
    speed=speed/(1+math.min(fresh,45)/65)
    fox.speed=(fox.speed or 0)+(speed-(fox.speed or 0))*(1-math.exp(-dt/.45))
    local amount=math.min(d,fox.speed*dt)*math.max(0,math.cos(delta*math.pi/180))
    if amount<.001 then return false end
    local x,y=fox.x+dx*amount,fox.y+dy*amount
    local ground=env(x,y)
    -- A short lookahead catches narrow trail segments at fast simulation rates.
    local ahead=env(fox.x+dx*math.min(d,amount+150),fox.y+dy*math.min(d,amount+150))
    if not ground.inside or not ahead.inside or (not allow_trail and (ground.trail or ahead.trail))
        or math.abs(ground.ground-previous.ground)>amount*.8+5 then
        return nil
    end
    if risk(ground)>.15 and risk(ground)>risk(previous)+.003
        or risk(ahead)>.15 and risk(ahead)>risk(previous)+.03 then return nil end
    fox.x,fox.y=x,y
    fox.moved=(fox.moved or 0)+math.sqrt(amount*amount+(ground.ground-previous.ground)^2)
    return distance(fox,target)<10
end
function Foxes.step(state,config,dt,clock,env)
    assert(finite(dt) and dt>=0 and dt<=.25,'Fox timestep must be 0..0.25 seconds')
    local prints={}
    if clock.paused then return prints end
    local night=Foxes.night(clock.hour)
    -- Fear has priority over hunting, play and feeding. Camera position is
    -- deliberately absent here: the movable debug view is not a person.
    for _,fox in ipairs(state.foxes) do
        local here=env(fox.x,fox.y);local threat=here.disturbance
        if threat and fox.mode~='flee' then
            if threat.distance<threat.radius then
                escape(state,fox,config.habitats[fox.habitat],threat,env)
            elseif fox.mode~='alert' then
                fox.threat={x=threat.x,y=threat.y,kind=threat.kind};fox.partner=nil;fox.route=nil
                fox.purpose='watch';mode(fox,'alert','idle',2)
            end
        end
    end
    -- Encounters are brief and have a long cooldown: never maintain a pack.
    for i,a in ipairs(state.foxes) do
        for j=i+1,#state.foxes do
            local b=state.foxes[j]
            local function available(f)
                return (f.mode=='idle' or f.mode=='roam' or f.mode=='stalk') and (f.social_cooldown or 0)<=0
            end
            if distance(a,b)<180 and available(a) and available(b) then
                local angle=math.atan(b.y-a.y,b.x-a.x)
                for role,f in ipairs({a,b}) do
                    f.partner=role==1 and j or i;f.social_role=role
                    f.social_center={x=(a.x+b.x)/2,y=(a.y+b.y)/2}
                    f.social_angle=angle+(role==1 and math.pi or 0)
                    f.social_cooldown=90;mode(f,'play','play_bow',7)
                end
            end
        end
    end
    for i,fox in ipairs(state.foxes) do
        -- Prey positions represent activity in galleries below the snow.
        -- They remain saved simulation data; no rodent actor is rendered.
        local h=config.habitats[fox.habitat];local prey=state.rodents[i]
        fox.moved=0
        fox.motion_dt=dt
        fox.time=fox.time+dt;prey.time=prey.time+dt
        fox.bound_rest=math.max(0,(fox.bound_rest or 0)-dt)
        if fox.flight and fox.flight.elapsed<fox.flight.duration then
            fox.flight.elapsed=math.min(fox.flight.duration,fox.flight.elapsed+dt)
            fox.jump=Foxes.ballistic(fox.flight.height,fox.flight.elapsed)
            if fox.flight.elapsed==fox.flight.duration then fox.bound_rest=.18 end
        end
        fox.shake_age=(fox.shake_age or 0)+dt
        fox.social_cooldown=math.max(0,(fox.social_cooldown or 0)-dt)
        fox.trip_cooldown=math.max(0,(fox.trip_cooldown or 0)-dt)
        fox.refuge_time=math.max(0,(fox.refuge_time or 0)-dt)
        if fox.refuge and fox.refuge_time==0 then
            if quiet(env(h.forest.x,h.forest.y)) then fox.refuge=nil else fox.refuge_time=60 end
        end
        local feeding_area=fox.refuge or h[fox.area]
        fox.hunger=math.min(1,(fox.hunger or .45)+dt/240)
        fox.fatigue=math.max(0,(fox.fatigue or .15)-(fox.mode=='rest' and dt/35 or dt/1800))
        local weather=env(fox.x,fox.y)
        -- Lying snow is not falling snow. Only a local heavy snowfall adds
        -- a coat; running, shaking and warmer air gradually clear the fur.
        local coating=weather.heavy_snow and dt/180 or -dt/(weather.temperature_c and weather.temperature_c>0 and 35 or 300)
        fox.coat=math.min(1,(fox.coat or 0)+coating)
        fox.coat=math.max(0,fox.coat)
        prey.hidden=math.max(0,prey.hidden-dt)
        prey.clip='idle'
        if prey.hidden==0 and distance(fox,prey)<250 and fox.mode~='pounce' and fox.mode~='listen' then
            local dx,dy=prey.x-fox.x,prey.y-fox.y;local d=math.max(1,math.sqrt(dx*dx+dy*dy))
            local p={x=prey.x+dx/d*38*dt,y=prey.y+dy/d*38*dt}
            local surface=env(p.x,p.y)
            if distance(p,feeding_area)<feeding_area.radius and quiet(surface) then
                prey.x,prey.y=p.x,p.y;prey.yaw=math.atan(dy,dx)*180/math.pi;prey.clip='scurry'
            end
        end
        if fox.mode=='alert' then
            fox.yaw=fox.yaw+math.max(-45*dt,math.min(45*dt,
                (math.atan(fox.threat.y-fox.y,fox.threat.x-fox.x)*180/math.pi-fox.yaw+180)%360-180))
            if fox.time>=fox.wait then
                local threat=env(fox.x,fox.y).disturbance
                if threat then escape(state,fox,h,threat,env)
                else mode(fox,'idle','idle',6+random(state)*6) end
            end
        elseif fox.mode=='flee' then
            local here=env(fox.x,fox.y)
            if risk(here)<.1 then fox.safe_time=fox.safe_time+dt else fox.safe_time=0 end
            local arrived=move(state,fox,fox.target,175,dt,env,here.trail,prints)
            if arrived==nil and fox.time>1 then
                local threat=here.disturbance or fox.threat
                escape(state,fox,h,threat,env)
            elseif arrived or fox.safe_time>4 then
                fox.refuge={x=fox.x,y=fox.y,radius=650};fox.refuge_time=120
                fox.area='forest';fox.purpose='watch';mode(fox,'rest','idle',12+random(state)*10)
            end
        elseif fox.mode=='rest' then
            if fox.time>=fox.wait then mode(fox,'idle','idle',2) end
        elseif fox.mode=='sniff' then
            if fox.time>=fox.wait then mode(fox,'idle','idle',1) end
        elseif fox.mode=='search' or fox.mode=='run' then
            -- Search a feeding patch with a persistent, gently curving heading
            -- and listening stops, rather than selecting random waypoints.
            local area=feeding_area
            local goal=prey.hidden==0 and quiet(env(prey.x,prey.y)) and prey or area
            local desired=math.atan(goal.y-fox.y,goal.x-fox.x)*180/math.pi
            local heading=desired+18*math.sin(fox.time*.45+i*1.7)
            local a=heading*math.pi/180
            fox.target={x=fox.x+math.cos(a)*300,y=fox.y+math.sin(a)*300}
            local arrived=move(state,fox,fox.target,fox.mode=='run' and 190 or 55,dt,env,false,prints)
            if prey.hidden==0 and distance(fox,prey)<500 and quiet(env(prey.x,prey.y)) then
                mode(fox,'stalk','walk')
            elseif arrived==nil or fox.time>=fox.wait then mode(fox,'sniff','sniff',3+random(state)*4) end
        elseif fox.mode=='shelter' then
            if move(state,fox,fox.target,65,dt,env,false,prints)~=false then
                fox.purpose='rest';mode(fox,'rest','idle',25+random(state)*30)
            end
        elseif fox.mode=='shake' then
            if fox.time>.65 and not fox.shed then fox.coat=0;fox.shed=true end
            if fox.time>=1.6 then fox.shake_age=0;fox.shed=nil;mode(fox,'idle','idle',2) end
        elseif fox.mode=='play' then
            local partner=state.foxes[fox.partner]
            if not partner or partner.mode~='play' and fox.time<fox.wait then
                fox.partner=nil;mode(fox,'idle','idle',5)
            elseif fox.time<2 then
                fox.yaw=math.atan(partner.y-fox.y,partner.x-fox.x)*180/math.pi
            elseif fox.time<fox.wait then
                fox.clip='trot'
                local angle=fox.social_angle+(fox.time-2)*1.25
                local target={x=fox.social_center.x+math.cos(angle)*140,y=fox.social_center.y+math.sin(angle)*140}
                move(state,fox,target,180,dt,env,false,prints)
            else
                fox.target={x=fox.x+math.cos(fox.social_angle)*1000,y=fox.y+math.sin(fox.social_angle)*1000}
                fox.partner=nil;mode(fox,'disperse','trot')
            end
        elseif fox.mode=='disperse' then
            if move(state,fox,fox.target,210,dt,env,false,prints)~=false then mode(fox,'idle','idle',3) end
        elseif fox.mode=='cross' then
            -- If dawn arrives while already on a piste, finish exiting it.
            -- Before entering, wait for the next night.
            local here=env(fox.x,fox.y)
            if here.trail then fox.crossed_trail=true end
            if not night and not here.trail and (not fox.crossed_trail or fox.waypoint>=3) then
                if fox.waypoint>=3 then fox.area=fox.destination end
                mode(fox,'idle','idle',8);fox.route=nil
            else
                local target=fox.route[fox.waypoint]
                local arrived=move(state,fox,target,260,dt,env,night or fox.waypoint==2,prints)
                if arrived then
                    fox.waypoint=fox.waypoint+1
                    if fox.waypoint>#fox.route then fox.area=fox.destination;fox.route=nil;mode(fox,'idle','idle',2) end
                elseif arrived==nil then mode(fox,'idle','idle',4);fox.route=nil end
            end
        elseif fox.mode=='roam' or fox.mode=='stalk' then
            local target=fox.mode=='stalk' and prey or fox.target
            local arrived=move(state,fox,target,fox.mode=='stalk' and 45 or 55,dt,env,false,prints)
            if fox.mode=='stalk' and distance(fox,prey)<90 then
                mode(fox,'listen','sniff',1.5)
            elseif arrived~=false then mode(fox,'idle','idle',2+random(state)*3) end
        elseif fox.mode=='listen' then
            if fox.time>=fox.wait then
                fox.launch={x=fox.x,y=fox.y};fox.target={x=prey.x,y=prey.y}
                local _,flight=Foxes.ballistic(65,0)
                fox.pounce_id=nil;mode(fox,'pounce','pounce',.14+flight+.14)
            end
        elseif fox.mode=='pounce' then
            local _,flight=Foxes.ballistic(65,0)
            local airborne=math.max(0,math.min(flight,fox.time-.14))
            local t=airborne/flight
            if airborne>0 and fox.pounce_id==nil then launch(fox,65);fox.pounce_id=fox.flight.id end
            if fox.pounce_id and fox.flight.id==fox.pounce_id then fox.flight.elapsed=airborne end
            local x=fox.launch.x+(fox.target.x-fox.launch.x)*t
            local y=fox.launch.y+(fox.target.y-fox.launch.y)*t
            local surface=env(x,y)
            if surface.inside and not surface.trail then fox.x,fox.y=x,y end
            fox.jump=Foxes.ballistic(65,airborne)
            if fox.time>=fox.wait then
                fox.jump=0
                if surface.inside and not surface.trail and distance(fox,prey)<90 then
                    prey.hidden=35+random(state)*35;state.catches=state.catches+1
                    local p=clear_point(state,feeding_area,env,fox)
                    if p then prey.x,prey.y=p.x,p.y end
                    fox.hunger=math.max(0,fox.hunger-.55);fox.purpose='feed'
                    mode(fox,'feed','feed',3)
                else mode(fox,'idle','idle',3) end
            end
        elseif fox.mode=='feed' then
            if fox.time>=fox.wait then mode(fox,'idle','idle',2) end
        elseif fox.time>=fox.wait then
            if fox.shake_age>45 and fox.coat>.35 and random(state)<.3 then
                mode(fox,'shake','shake',1.6)
            elseif night and fox.trip_cooldown<=0
                and not fox.refuge and (fox.area=='forest' and fox.hunger>.55
                    or fox.area=='meadow' and (fox.hunger<.25 or fox.fatigue>.5 or clock.hour>=4 and clock.hour<6))
                and quiet(env(h.crossing[1].x,h.crossing[1].y)) and quiet(env(h.crossing[2].x,h.crossing[2].y)) then
                fox.destination=fox.area=='forest' and 'meadow' or 'forest';fox.purpose=fox.destination=='meadow' and 'forage' or 'shelter'
                local a,b=h.crossing[1],h.crossing[2]
                if fox.area=='meadow' then a,b=b,a end
                local target=clear_point(state,h[fox.destination],env) or b
                fox.route={{x=a.x,y=a.y},{x=b.x,y=b.y},target};fox.waypoint=1;fox.crossed_trail=false;fox.trip_cooldown=180
                mode(fox,'cross','trot')
            elseif fox.fatigue>.55 or fox.hunger<.2 then
                fox.target=clear_point(state,fox.refuge or h.forest,env,fox)
                fox.purpose='shelter'
                if fox.target and distance(fox,fox.target)>150 then mode(fox,'shelter','walk')
                else mode(fox,'rest','idle',25+random(state)*30) end
            elseif prey.hidden==0 and distance(fox,prey)<500 and quiet(env(prey.x,prey.y)) then fox.purpose='hunt';mode(fox,'stalk','walk')
            else
                -- A rodent represents this feeding patch. Move it to the new
                -- habitat after a crossing instead of chasing it back across
                -- the piste during daylight.
                if distance(prey,feeding_area)>feeding_area.radius or not quiet(env(prey.x,prey.y)) then
                    local p=clear_point(state,feeding_area,env,fox)
                    if p then prey.x,prey.y=p.x,p.y end
                end
                fox.purpose='forage'
                if fox.fatigue<.4 and distance(fox,prey)>650 and random(state)<.3 then
                    mode(fox,'run','trot',3+random(state)*3)
                else mode(fox,'search','walk',7+random(state)*8) end
            end
        end
        local locomotion=fox.mode=='roam' or fox.mode=='stalk' or fox.mode=='cross'
            or fox.mode=='search' or fox.mode=='run' or fox.mode=='shelter' or fox.mode=='flee'
            or fox.mode=='disperse' or (fox.mode=='play' and fox.time>=2)
        if locomotion then
            local surface=env(fox.x,fox.y)
            local buried=(surface.fresh_cm or 0)*.85>=config.leg_height_cm
            local airborne=fox.flight and fox.flight.elapsed<fox.flight.duration
            local clip=(buried or airborne) and 'bound' or ((fox.mode=='roam' or fox.mode=='stalk' or fox.mode=='search' or fox.mode=='shelter') and 'walk' or 'trot')
            fox.clip=clip
            if fox.gait_clip~=clip then fox.anim_time=0;fox.gait_clip=clip end
            local gait=config.gaits[clip]
            -- Distance along the terrain drives the feet, including slower
            -- turns/powder and blocked motion. No independent clock sliding.
            local penetration=math.min((surface.fresh_cm or 0)*.85,config.leg_height_cm+8)
            if clip=='bound' then
                if buried and fox.moved>0 and not airborne and fox.bound_rest<=0 then
                    launch(fox,penetration+10);fox.bound_cycles=(fox.bound_cycles or 0)+1
                end
                local flight=fox.flight
                local phase=flight and flight.elapsed<flight.duration and flight.elapsed/flight.duration*.65
                    or .65+(1-fox.bound_rest/.18)*.35
                fox.anim_time=((fox.bound_cycles or 0)+phase)*gait.duration
            else
                fox.anim_time=(fox.anim_time or 0)+fox.moved/gait.stride*gait.duration
                fox.jump=0
            end
            fox.fatigue=math.min(1,fox.fatigue+fox.moved/22000)
            fox.coat=math.max(0,fox.coat-fox.moved/70000)
        else
            if fox.gait_clip~=fox.clip then fox.anim_time=0;fox.gait_clip=fox.clip end
            if fox.mode=='pounce' then fox.anim_time=fox.time/fox.wait*(config.gaits.pounce and config.gaits.pounce.duration or 1.2)
            else fox.anim_time=(fox.anim_time or 0)+dt end
        end
    end
    return prints
end
return Foxes
