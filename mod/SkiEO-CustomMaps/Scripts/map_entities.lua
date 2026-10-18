-- Small decorative populations for mapmods; bounds and lifetime belong to the
-- loader. Behaviour, habitats and models remain entirely in each mapmod.
local UE=require('UEHelpers')
local Terrain=require('terrain')
local Animated=require('animated_mesh')
local Aim=require('animated_aim')
local Snow=require('entity_snow')
local Ground=require('animated_ground')
local Disturbance=require('map_disturbance')
local Entities={}
local DIRECTORY=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local function valid(o) return o and o:IsValid() end
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<1e8 end
local function load(path)
    local o=StaticFindObject(path);if not valid(o) then o=LoadAsset(path) end
    assert(valid(o),'Entity resource unavailable: '..path);return o
end
local function subsystem(name)
    local world=UE.GetWorld()
    for _,o in ipairs(FindAllOf(name) or {}) do
        if valid(o) and not o:GetFullName():find('Default__',1,true) then
            local w=o:GetWorld()
            if valid(w) and w:GetAddress()==world:GetAddress() then return o end
        end
    end
end
local function context(api)
    local session=api._session or api
    if not session._entities then
        local state={models={},ground_rigs={},materials={},actors={},count=0,tracks={},next_track=1,snow_cache={}}
        session._entities=state
        session._cleanups=session._cleanups or {}
        session._cleanups[#session._cleanups+1]=function()
            state.stopped=true
            for _,actor in ipairs(state.actors) do if valid(actor) then pcall(function() actor:K2_DestroyActor() end) end end
            state.models={};state.ground_rigs={};state.materials={};state.tracks={};state.actors={}
        end
    end
    assert(not session._entities.stopped,'Entity session has ended')
    return session._entities
end
function Entities.environment(api,x,y,support_only)
    local state=context(api)
    if not valid(state.time) then state.time=subsystem('TimeSubsystem') end
    assert(valid(state.time),'Time subsystem unavailable')
    local result=state.clock
    if x==nil or not result then
        local game=UE.GetGameplayStatics();local world=UE.GetWorld()
        result={hour=state.time:GetTimeOfDayHours(),paused=state.time:IsTimePaused(),
            rate=state.time:GetTimeRate(),hours=state.time:GetTotalGameHoursElapsed(),
            seconds=game:GetRealTimeSeconds(world),ready=(api._session or api)._loading_success==true}
        result.paused=result.paused or result.rate==0
            or (state.time.IsUIPaused and state.time:IsUIPaused())
            or (game.IsGamePaused and game:IsGamePaused(world)) or false
        state.clock=result
    end
    if x==nil then
        local controller=UE.GetPlayerController()
        local camera=valid(controller) and controller.PlayerCameraManager
        if valid(camera) then
            local p=camera:GetCameraLocation()
            result.camera={x=p.X,y=p.Y,z=p.Z}
        end
        local second=math.floor(result.seconds/2)
        if state.snow_second~=second then state.snow_cache={};state.snow_second=second end
        if not valid(state.weather) then state.weather=subsystem('WeatherSubsystem') end
        result.heavy_snow=false
        if valid(state.weather) then
            result.weather=tonumber(state.weather:GetWeatherType())
            -- Blizzard is the game's heavy precipitation; location checks
            -- distinguish snow from rain at warmer, lower elevations.
            result.heavy_snow=result.weather==3
        end
        return result
    end
    assert(finite(x) and finite(y),'Invalid surface position')
    local terrain=Terrain.active
    local ground=Terrain.surface_height_at(x,y)
    if not terrain or not ground then return {inside=false} end
    local u=(x-terrain.origin_x)/((terrain.width-1)*terrain.spacing_cm)
    local v=(y-terrain.origin_y)/((terrain.height-1)*terrain.spacing_cm)
    if u<0 or u>1 or v<0 or v>1 then return {inside=false} end
    result=setmetatable({inside=true,ground=ground,snow_cm=0},{__index=result})
    if not valid(state.snow) then state.snow=subsystem('SnowStateCache') end
    if valid(state.snow) then
        -- CPU cells are about 2.6 m in Veymont. Cache only spatial samples;
        -- renderer/AI calls never perform synchronous GPU readbacks.
        local cell=state.snow_spacing or 100
        local key=math.floor(x/cell)..':'..math.floor(y/cell)
        local depth=state.snow_cache[key]
        if depth==nil then
            local spacing,packed,fresh,total
            total,spacing,packed,fresh=Snow.sample(state.snow,x,y)
            depth=total and {total=total,packed=packed or total,fresh=fresh or 0} or nil
            if spacing then state.snow_spacing=spacing end
            state.snow_cache[key]=depth or false
        end
        result=setmetatable({snow_cm=depth and depth.total or 0,packed_cm=depth and depth.packed or 0,
            fresh_cm=depth and depth.fresh or 0},{__index=result})
    else result=setmetatable({snow_cm=0,packed_cm=0,fresh_cm=0},{__index=result}) end
    -- Snow depth is physical data; a material can render a slightly different
    -- surface. The map supplies its measured visual contact calibration.
    result.z=ground+(result.snow_cm>.2 and
        math.max(0,(terrain.runtime.snow_offset_centimeters or 30)+result.snow_cm
            +(terrain.runtime.snow_surface_bias_centimeters or 0)) or 0)
    if support_only then return result end
    if not valid(state.trails) then state.trails=subsystem('TrailMapSubsystem') end
    -- The native trail map reserves ID zero for positions outside all pistes.
    result.trail=valid(state.trails) and state.trails:GetTrailAtPosition({X=x,Y=y,Z=ground},true)>0 or false
    result.disturbance=Disturbance.sample(state,x,y,result.z,result.seconds)
    if valid(state.weather) then
        local position={X=x,Y=y,Z=ground}
        result.heavy_snow=result.heavy_snow and state.weather:IsSnowingAtLocation(position) or false
        result.temperature_c=state.weather:GetTemperatureAtLocation(position)
    end
    return result
end
function Entities.focus_camera(api,x,y,z,distance)
    context(api)
    assert(finite(x) and finite(y) and finite(z),'Invalid camera target')
    distance=distance or 500
    assert(finite(distance) and distance>=100 and distance<=5000,'Camera distance must be 100..5000 cm')
    local surface=Entities.environment(api,x,y)
    assert(surface.inside,'Camera target is outside the map')
    local controller=UE.GetPlayerController()
    assert(valid(controller),'Player controller is unavailable')
    local pawn=controller:K2_GetPawn()
    assert(valid(pawn),'Camera pawn is unavailable')
    local camera=controller.PlayerCameraManager
    assert(valid(camera),'Player camera is unavailable')
    -- The native pawn keeps its own view rotation; actor/control rotation
    -- changes are overwritten by its tick. Move along the existing view ray.
    local view=camera:GetCameraRotation()
    local angle,pitch=view.Yaw*math.pi/180,view.Pitch*math.pi/180
    local horizontal=distance*math.cos(pitch)
    local position={X=x-math.cos(angle)*horizontal,Y=y-math.sin(angle)*horizontal,
        Z=z-distance*math.sin(pitch)}
    local ground=Entities.environment(api,position.X,position.Y)
    if not ground.inside then position.X=x;position.Y=y;position.Z=z+distance end
    position.Z=math.max(position.Z,(ground.inside and ground.z or surface.z)
        +math.max(25,tonumber(pawn.CollisionSphereRadius) or 50))
    pawn:K2_SetActorLocation(position,false,{},true)
    controller:SetViewTargetWithBlend(pawn,0,0,0,false)
    return true
end
local function spawn(state)
    local world=UE.GetWorld();assert(valid(world),'Map world unavailable')
    local cls=load('/Script/Engine.Actor');local mesh_class=load('/Script/ProceduralMeshComponent.ProceduralMeshComponent')
    local t={Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}}
    local game=UE.GetGameplayStatics()
    local actor=game:BeginDeferredActorSpawnFromClass(world,cls,t,1,nil,0)
    assert(valid(actor),'Could not spawn map entity');state.actors[#state.actors+1]=actor
    actor=game:FinishSpawningActor(actor,t,0);state.actors[#state.actors]=actor
    actor:SetActorEnableCollision(false)
    local mesh=actor:AddComponentByClass(mesh_class,false,t,false)
    assert(valid(mesh),'Could not create map entity mesh');mesh:SetCollisionEnabled(0)
    return actor,mesh
end
local function material(api,state,path,dry)
    local key=api._map.id..'/'..path..(dry and '/dry' or '')
    if state.materials[key] then return state.materials[key] end
    local bytes=api:read_asset(path);require('textures').png_size(bytes)
    local rendering=load('/Script/Engine.Default__KismetRenderingLibrary')
    local base=load(dry and '/Game/Materials/M_Prop_albtex_Snowless.M_Prop_albtex_Snowless' or '/Game/Materials/M_Prop_albtex.M_Prop_albtex')
    local retain=require('native_terrain').retain_texture
    if retain then retain(base) end
    local library=load('/Script/Engine.Default__KismetMaterialLibrary')
    local file=assert(io.open(DIRECTORY..'entity-texture.png','wb'));file:write(bytes);file:close()
    local ok,texture=pcall(function() return rendering:ImportFileAsTexture2D(UE.GetWorld(),DIRECTORY..'entity-texture.png') end)
    os.remove(DIRECTORY..'entity-texture.png')
    assert(ok and valid(texture),'Could not import entity texture')
    if retain then retain(texture) end
    local m=library:CreateDynamicMaterialInstance(UE.GetWorld(),base,UE.FindOrAddFName('MapEntity'),0)
    assert(valid(m),'Could not create entity material')
    if retain then retain(m) end
    m:SetTextureParameterValue(UE.FindOrAddFName('Albedo'),texture)
    state.materials[key]=m
    return m
end
function Entities.spawn(api,path,textures,options)
    local state=context(api);assert(state.count<16,'At most 16 animated entities per map')
    assert(type(textures)=='table','Animated mesh textures must be an array')
    local key=api._map.id..'/'..path
    local model=state.models[key]
    if not model then model=Animated.decode(api:read_asset(path));state.models[key]=model end
    options=options or {};assert(type(options)=='table','Invalid animated entity options')
    local blend_duration=options.blend_duration or .24
    assert(finite(blend_duration) and blend_duration>=0 and blend_duration<=1,'Invalid animation blend duration')
    local rig=options.aim_rig and Aim.decode(api:read_asset(options.aim_rig),model)
    local ground_rig
    if options.ground_rig then
        local key=api._map.id..'/'..path..'/'..options.ground_rig
        ground_rig=state.ground_rigs[key]
        if not ground_rig then ground_rig=Ground.decode(api:read_asset(options.ground_rig),model);state.ground_rigs[key]=ground_rig end
    end
    local ground_state={}
    local aim_state,target,aim_dt={},nil,0
    assert(#textures==#model.sections,'One texture is required per mesh section')
    local materials={};for i,p in ipairs(textures) do materials[i]=material(api,state,p,options.snow_coat) end
    local snow_materials
    if options.snow_textures then
        assert(options.snow_coat and type(options.snow_textures)=='table' and #options.snow_textures>=2
            and #options.snow_textures<=16,'Snow coat needs 2..16 declared textures')
        snow_materials={materials[1]}
        for i,path in ipairs(options.snow_textures) do snow_materials[i+1]=material(api,state,path,true) end
    end
    if options.snow_coat then assert(#model.sections>=3,'Snow coating needs a separate final section') end
    local actor,mesh=spawn(state);state.count=state.count+1
    for i,section in ipairs(model.sections) do
        mesh:CreateMeshSection(i-1,section.vertices,section.triangles,section.normals,section.uv,{},{},false)
        mesh:SetMaterial(i-1,materials[i])
    end
    if snow_materials then mesh:SetMeshSectionVisible(#model.sections-1,false) end
    local buffers={};for i=1,#model.sections do buffers[i]={vertices={},normals={}} end
    local animation_state,last_pose_seconds={},nil
    local handle={}
    local transform,inspection
    function handle:inspect(provider)
        assert(not state.stopped and valid(actor),'Entity session has ended')
        assert(type(provider)=='function' and not inspection,'Inspection needs one information provider per entity')
        inspection=true
        require('entity_selection').attach(api,{provider=provider,
            pose=function()return buffers[1].vertices,model.sections[1].triangles,transform end,
            surface=function(px,py)return Entities.environment(api,px,py,true)end,
            highlight=function(selected)
                if valid(mesh) then mesh:SetCustomDepthStencilValue(1);mesh:SetRenderCustomDepth(selected) end
            end})
    end
    local sound,last_sound
    function handle:pause()
        if valid(sound) then sound:Stop() end
    end
    local function snow_sound(contact)
        if not options.snow_sound then return end
        local clock=Entities.environment(api)
        local camera=clock.camera
        if clock.paused or not camera or (last_sound and clock.seconds-last_sound<.08) then return end
        local distance=math.sqrt((camera.x-contact.x)^2+(camera.y-contact.y)^2+(camera.z-contact.z)^2)
        if distance>=900 then return end
        if not valid(state.audio_settings) then
            state.audio_settings=subsystem('AmbientCrowdAudioSubsystem')
            state.audio_settings=valid(state.audio_settings) and state.audio_settings.Settings or nil
        end
        local settings=state.audio_settings
        if not valid(settings) or not valid(settings.WalkingSound) then return end
        local volume=.28*(1-distance/900)^2
        if not valid(sound) then
            local cls=load('/Script/Engine.AudioComponent')
            local identity={Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}}
            sound=actor:AddComponentByClass(cls,false,identity,false)
            if not valid(sound) then return end
            sound:SetAutoActivate(false);sound.bAutoDestroy=false;sound.bAllowSpatialization=true
            sound.AttenuationSettings=settings.MovementAttenuation
            sound:SetSound(settings.WalkingSound);sound:SetPitchMultiplier(1.35)
        end
        sound:Stop();sound:K2_SetWorldLocation({X=contact.x,Y=contact.y,Z=contact.z},false,{},true)
        sound:SetVolumeMultiplier(volume);sound:Play(0)
        -- Reuse the game's snow crunch as a short, spatial contact burst,
        -- rather than leaving a human walking loop running under a fox.
        sound:FadeOut(.18,0,0);last_sound=clock.seconds
    end
    if options.snow_coat then
        local dry=false
        local snow_level=1
        local flakes,flakes_visible
        function handle:snow(amount,shake_time)
            assert(finite(amount) and amount>=0 and amount<=1,'Invalid snow coat')
            if snow_materials then
                local level=1+math.floor(amount*(#snow_materials-1)+.5)
                if level~=snow_level then mesh:SetMaterial(0,snow_materials[level]);snow_level=level end
            else
                local next_dry=amount<.5
                if next_dry~=dry then
                    dry=next_dry
                    mesh:SetMeshSectionVisible(#model.sections-1,not dry)
                end
            end
            if shake_time and shake_time>=.65 and shake_time<1.4 then
                if not flakes then
                    local t={Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}}
                    flakes=actor:AddComponentByClass(load('/Script/ProceduralMeshComponent.ProceduralMeshComponent'),false,t,false)
                    flakes:SetCollisionEnabled(0)
                    flakes:SetMaterial(0,materials[#materials])
                end
                local vertices,normals,triangles,uv={},{},{},{}
                local elapsed=shake_time-.65
                for j=1,16 do
                    local phi=j*2.3999632297
                    local t=math.max(0,elapsed-(j%4)*.025)
                    local x=(j%5-2)*9+math.cos(phi)*90*t
                    local y=math.sin(phi)*(10+100*t)
                    local z=32+60*t-190*t*t
                    local first=#vertices
                    for _,v in ipairs({{1,0,0},{-1,0,0},{0,1,0},{0,-1,0},{0,0,1},{0,0,-1}}) do
                        vertices[#vertices+1]={X=x+v[1]*.8,Y=y+v[2]*.8,Z=z+v[3]*.8}
                        normals[#normals+1]={X=v[1],Y=v[2],Z=v[3]};uv[#uv+1]={X=0,Y=0}
                    end
                    for _,v in ipairs({{0,4,2},{2,4,1},{1,4,3},{3,4,0},{2,5,0},{1,5,2},{3,5,1},{0,5,3}}) do
                        for _,index in ipairs(v) do triangles[#triangles+1]=first+index end
                    end
                end
                flakes:CreateMeshSection(0,vertices,triangles,normals,uv,{},{},false);flakes_visible=true
            elseif flakes_visible and valid(flakes) then flakes:ClearMeshSection(0);flakes_visible=false end
        end
    end
    function handle:look_at(x,y,z,weight,dt)
        assert(not state.stopped and valid(actor),'Entity session has ended')
        assert(rig,'Entity has no aim rig')
        assert(finite(weight) and weight>=0 and weight<=1 and finite(dt) and dt>=0 and dt<=.25,'Invalid gaze weight/timestep')
        aim_dt=dt
        if weight==0 then target=nil;return end
        for _,n in ipairs({x,y,z}) do assert(finite(n),'Invalid gaze target') end
        assert(x and y and z,'Missing gaze target')
        target={X=x,Y=y,Z=z,weight=weight}
    end
    function handle:place(x,y,z,yaw,pitch,roll)
        assert(not state.stopped and valid(actor),'Entity session has ended')
        for _,n in ipairs({x,y,z,yaw,pitch or 0,roll or 0}) do assert(finite(n),'Invalid entity pose') end
        actor:K2_SetActorLocationAndRotation({X=x,Y=y,Z=z},{Pitch=pitch or 0,Yaw=yaw,Roll=roll or 0},false,{},false)
        transform={x=x,y=y,z=z,yaw=yaw,pitch=pitch or 0}
    end
    function handle:pose(clip,seconds,x,y,z,yaw,pitch,roll,support)
        assert(not state.stopped and valid(actor),'Entity session has ended')
        for _,n in ipairs({x,y,z,yaw}) do assert(finite(n),'Invalid entity pose') end
        support=support or {}
        local clock=Entities.environment(api)
        local elapsed=support.dt or (last_pose_seconds and math.max(0,math.min(1,clock.seconds-last_pose_seconds)) or 0)
        last_pose_seconds=clock.seconds
        local poses,weight=Animated.pose(model,clip,seconds,elapsed,animation_state,blend_duration)
        for i,pose in ipairs(poses) do Animated.copy(pose,buffers[i]) end
        local contacts={}
        if ground_rig then
            assert(finite(support.jump or 0) and (support.jump or 0)>=0 and (support.jump or 0)<=150,'Invalid grounded jump')
            local surface=Entities.environment(api,x,y,true)
            local camera=clock.camera
            local distance=camera and math.sqrt((camera.x-x)^2+(camera.y-y)^2+(camera.z-surface.z)^2) or math.huge
            local adapt=support.adapt==nil and Ground.visibility(distance,surface) or support.adapt
            local section=ground_rig.section
            local vertices,normals=buffers[section].vertices,buffers[section].normals
            z,pitch,contacts=Ground.solve(ground_rig,vertices,normals,clip,seconds,x,y,support.jump or 0,yaw,
                function(px,py)return Entities.environment(api,px,py,true)end,ground_state,support.emit==true,adapt,support.dt,weight)
            roll=0
        end
        local local_target
        if target then
            local_target=Ground.inverse(Ground.axes(yaw,pitch or 0),{X=target.X-x,Y=target.Y-y,Z=target.Z-z})
            local_target.weight=target.weight
        end
        for i,section in ipairs(model.sections) do
            local vertices,normals=buffers[i].vertices,buffers[i].normals
            if rig then Aim.apply(rig,i,vertices,normals,local_target,aim_state,aim_dt) end
            mesh:UpdateMeshSection(i-1,vertices,normals,{},{},{})
        end
        self:place(x,y,z,yaw,pitch,roll)
        for _,contact in ipairs(contacts) do
            if options.paw_texture then Entities.footprint(api,contact.x,contact.y,contact.yaw,options.paw_texture,contact.profile) end
            snow_sound(contact)
        end
        return {z=z,pitch=pitch or 0,roll=roll or 0,contacts=contacts}
    end
    return handle
end
-- A bounded mesh ring uses one section per footprint; expired prints are
-- removed, and all prints disappear when their map session ends.
function Entities.footprint(api,x,y,yaw,texture,profile)
    for _,n in ipairs({x,y,yaw}) do assert(finite(n),'Invalid footprint position') end
    local state=context(api)
    local surface=Entities.environment(api,x,y)
    if not surface.inside or surface.snow_cm<=.2 then return false end
    if not state.track_mesh then
        local actor,mesh=spawn(state);state.track_mesh=mesh
        local base=load('/Game/Materials/M_Prop_albtex_Snowless.M_Prop_albtex_Snowless')
        local library=load('/Script/Engine.Default__KismetMaterialLibrary')
        state.track_material=library:CreateDynamicMaterialInstance(UE.GetWorld(),base,UE.FindOrAddFName('FoxTracks'),0)
        if texture then state.track_material=material(api,state,texture,true) end
    end
    local vertices,triangles,normals,uv={},{},{},{}
    local angle=yaw*math.pi/180;local c,s=math.cos(angle),math.sin(angle)
    if profile then
        assert(type(profile.vertices)=='table' and #profile.vertices>=3 and #profile.vertices<=256
            and type(profile.triangles)=='table' and #profile.triangles<=1536 and #profile.triangles%3==0,'Invalid paw contact profile')
        for _,p in ipairs(profile.vertices) do
            assert(finite(p.X) and finite(p.Y) and math.abs(p.X-x)<100 and math.abs(p.Y-y)<100,'Invalid paw contact vertex')
            local ground=Terrain.surface_height_at(p.X,p.Y) or surface.ground
            vertices[#vertices+1]={X=p.X,Y=p.Y,Z=ground+(surface.z-surface.ground)+.05}
            normals[#normals+1]={X=0,Y=0,Z=1};uv[#uv+1]={X=0,Y=0}
        end
        for j=1,#profile.triangles,3 do
            local a,b,c=profile.triangles[j],profile.triangles[j+1],profile.triangles[j+2]
            for _,i in ipairs({a,b,c}) do assert(finite(i) and i%1==0 and i>=0 and i<#vertices,'Invalid paw contact triangle') end
            local aa,bb,cc=vertices[a+1],vertices[b+1],vertices[c+1]
            if (bb.X-aa.X)*(cc.Y-aa.Y)-(bb.Y-aa.Y)*(cc.X-aa.X)>0 then b,c=c,b end
            triangles[#triangles+1]=a;triangles[#triangles+1]=b;triangles[#triangles+1]=c
        end
    else
    -- Generic API fallback; grounded animals supply their actual sole mesh.
    for _,pad in ipairs({{0,0,1.4,1.2},{1.4,-1.4,.7,.55},{2.2,-.45,.7,.55},{2.2,.45,.7,.55},{1.4,1.4,.7,.55}}) do
        local start=#vertices
        for i=0,7 do
            local a=i*math.pi/4;local px,py=pad[1]+pad[3]*math.cos(a),pad[2]+pad[4]*math.sin(a)
            local wx,wy=x+c*px-s*py,y+s*px+c*py
            local ground=Terrain.surface_height_at(wx,wy) or surface.ground
            vertices[#vertices+1]={X=wx,Y=wy,Z=ground+(surface.z-surface.ground)+.05}
            normals[#normals+1]={X=0,Y=0,Z=1};uv[#uv+1]={X=0,Y=0}
        end
        for i=1,6 do triangles[#triangles+1]=start;triangles[#triangles+1]=start+i+1;triangles[#triangles+1]=start+i end
    end
    end
    local index=state.next_track;state.next_track=index%256+1
    state.track_mesh:CreateMeshSection(index-1,vertices,triangles,normals,uv,{},{},false)
    state.track_mesh:SetMaterial(index-1,state.track_material)
    state.tracks[index]={expires=surface.hours+6,x=x,y=y}
    return true
end
function Entities.expire(api)
    local state=context(api);local now=Entities.environment(api).hours
    if not valid(state.track_mesh) then return end
    for index,track in pairs(state.tracks) do
        local surface=Entities.environment(api,track.x,track.y)
        if now>=track.expires or not surface.inside or surface.snow_cm<=.2 then
            state.track_mesh:ClearMeshSection(index-1);state.tracks[index]=nil
        end
    end
end
return Entities
