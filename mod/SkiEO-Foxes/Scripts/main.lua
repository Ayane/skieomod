-- Behaviour stays deterministic and inexpensive. Nearby animals interpolate
-- between simulation snapshots and render independently of the AI cadence.
local Foxes=require('behaviour')
local Gaze=require('gaze')
local json=require('json')
return function(api)
    local config=Foxes.config(api:mapmod_options())
    local support_rig=json.decode(api:read_asset('Assets/fox-ground.json'))
    config.gaits=support_rig.clips;config.leg_height_cm=support_rig.leg_height_cm
    api:on('map.ready',function()
        local saved=api:mod_state({})
        local state=Foxes.new(config,json.decode(json.encode(saved)))
        local function checkpoint()
            local copy=json.decode(json.encode(state))
            for key in pairs(saved) do saved[key]=nil end
            for key,value in pairs(copy) do saved[key]=value end
        end
        checkpoint()
        local actors,previous,last_render={},{},{}
        local snow_textures={}
        for i=1,16 do snow_textures[i]=string.format('Assets/snow-coat-%02d.png',i) end
        for i=1,config.count do
            actors[i]=api:spawn_animated('Assets/fox.skan',{'Assets/skin.png','Assets/eyeballs.png','Assets/snow.png'},
                {aim_rig='Assets/fox-eyes.json',ground_rig='Assets/fox-ground.json',snow_coat=true,
                    paw_texture='Assets/pawprint.png',snow_sound=true,snow_textures=snow_textures,blend_duration=.16})
            local fox=state.foxes[i]
            actors[i]:inspect(function()
                local activity={idle='Observe les alentours',rest='Se repose',search='Cherche sa nourriture',
                    run='Court dans la neige',stalk='Approche une proie',listen='Écoute sous la neige',
                    pounce='Chasse sous la neige',feed='Mange',shake="S’ébroue",play='Joue',
                    flee='Prend la fuite',alert='Surveille',shelter='Rejoint un abri',cross='Traverse la piste',
                    disperse='Retourne dans son territoire',sniff='Renifle'}
                return {title='Renard roux',subtitle='Vulpes vulpes',
                    properties={{label='Activité',value=activity[fox.mode] or 'Explore'},
                        {label='Habitat',value=fox.area=='meadow' and 'Prairie' or 'Forêt'}},
                    note='Vous avez repéré un habitant discret de la montagne.'}
            end)
        end
        local surface_cache={}
        local function surface(x,y)
            local key=x..':'..y
            local value=surface_cache[key]
            if not value then value=api:environment(x,y);surface_cache[key]=value end
            return value
        end
        local clock=api:environment()
        local last_seconds=clock.seconds or 0
        local accumulator=0
        local paused_audio=false
        local focused=0
        local heights={}
        local function copy_poses()
            for i,f in ipairs(state.foxes) do
                previous[i]={x=f.x,y=f.y,yaw=f.yaw,clip=f.clip,time=f.anim_time,jump=f.jump or 0,coat=f.coat or 0}
                if f.flight then
                    local b=f.flight
                    previous[i].flight={id=b.id,height=b.height,elapsed=b.elapsed,duration=b.duration}
                end
            end
        end
        copy_poses()
        local function blend(a,b,t) return a+(b-a)*t end
        local function pose_at(f,p,t)
            local yaw=p.yaw+((f.yaw-p.yaw+180)%360-180)*t
            return blend(p.x,f.x,t),blend(p.y,f.y,t),yaw,
                p.clip==f.clip and blend(p.time,f.anim_time or f.time,t) or (f.anim_time or f.time)
        end
        local function render(dt,initial)
            local alpha=initial and 1 or accumulator/.1
            for i,fox in ipairs(state.foxes) do
                local x,y,yaw,seconds=pose_at(fox,previous[i],alpha)
                local distance=clock.camera and math.sqrt((clock.camera.x-x)^2+(clock.camera.y-y)^2+(clock.camera.z-(heights[i] or clock.camera.z))^2) or 0
                local interval=distance<1800 and 1/30 or (distance<8000 and .1 or 1)
                last_render[i]=(last_render[i] or 1)+dt
                if initial or last_render[i]>=interval-1e-5 then
                    local ground=surface(x,y);assert(ground.inside,'Fox habitat is outside the map');heights[i]=ground.z
                    local elapsed=math.min(.25,last_render[i])
                    local periods=math.floor((last_render[i]+1e-5)/interval)
                    last_render[i]=math.max(0,last_render[i]-periods*interval)
                    local prey=state.rodents[i]
                    local target,weight=Gaze.target(fox,prey,clock.camera,ground,i,surface)
                    actors[i]:look_at(target and target.x or 0,target and target.y or 0,target and target.z or 0,weight,elapsed)
                    local pose=actors[i]:pose(fox.clip,seconds,x,y,ground.z,yaw,0,0,
                        {jump=Foxes.render_jump(fox,previous[i],alpha),emit=not initial,dt=elapsed})
                    if pose then heights[i]=pose.z end
                    if actors[i].snow then actors[i]:snow(fox.coat or 0,fox.mode=='shake' and seconds or nil) end
                end
            end
        end
        local initialized=clock.ready~=false
        if initialized then render(0,true) end
        api:bind_key('F7',function()
            focused=focused%#state.foxes+1
            local fox=state.foxes[focused]
            local ground=surface(fox.x,fox.y)
            api:focus_camera(fox.x,fox.y,(heights[focused] or ground.z)+35,500)
            last_render[focused]=1
            api:log('F7: fox '..focused..'/'..#state.foxes..' ('..fox.mode..')')
        end)
        api:on_frame(function()
            clock=api:environment()
            local now=clock.seconds or (last_seconds+.016)
            local dt=math.max(0,math.min(.25,now-last_seconds));last_seconds=now
            if clock.ready==false then accumulator=0;return end
            surface_cache={}
            if not initialized then
                initialized=true;render(0,true);copy_poses();accumulator=0;return
            end
            if clock.paused then
                if not paused_audio then for _,actor in ipairs(actors) do if actor.pause then actor:pause() end end end
                paused_audio=true;accumulator=0;copy_poses();return
            end
            paused_audio=false
            accumulator=accumulator+dt
            while accumulator>=.1 do
                copy_poses()
                Foxes.step(state,config,.1,clock,surface)
                accumulator=accumulator-.1
            end
            render(dt,false)
        end)
        api:every(5000,function() if not api:environment().paused then api:expire_footprints() end end)
        api:every(30000,checkpoint)
        api:log(config.count..' solitary foxes active; F7 focuses the next fox')
    end)
end
