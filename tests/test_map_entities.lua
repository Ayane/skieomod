package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local updates,created,destroyed,reads=0,0,0,0
local hour,hours,second,depth=22,0,0,12
local fresh=0
local sounds,crunches,stops,retained=0,0,0,0
local material_sets,shell_visible=0,nil
local ui_paused,world_paused=false,false
local function valid(self)return not self.dead end
local world={IsValid=valid,GetAddress=function()return 1 end}
local function base(o)
    o=o or {};o.IsValid=valid;o.GetWorld=function()return world end
    o.GetFullName=function()return 'Object Current' end;return o
end
local terrain={active={origin_x=-10000,origin_y=-10000,width=201,height=201,spacing_cm=100,runtime={snow_offset_centimeters=30}},surface_height_at=function()return 100 end}
local sections={}
local function actor()
    created=created+1
    local o=base({SetActorEnableCollision=function()end,K2_SetActorLocationAndRotation=function()end,
        K2_DestroyActor=function(self)self.dead=true;destroyed=destroyed+1 end})
    o.AddComponentByClass=function(_,cls)
        if cls.path=='/Script/Engine.AudioComponent' then
            sounds=sounds+1
            return base({SetAutoActivate=function()end,SetSound=function()end,SetPitchMultiplier=function()end,
                Stop=function()stops=stops+1 end,K2_SetWorldLocation=function()end,SetVolumeMultiplier=function(_,n)assert(n>0 and n<=.28)end,
                Play=function()crunches=crunches+1 end,FadeOut=function(_,n)assert(n==.18)end})
        end
        return base({SetCollisionEnabled=function()end,CreateMeshSection=function(_,i)sections[i]=true end,
            SetMaterial=function()material_sets=material_sets+1 end,SetMeshSectionVisible=function(_,_,show)shell_visible=show end,
            UpdateMeshSection=function()updates=updates+1 end,
            ClearMeshSection=function(_,i)sections[i]=nil end})
    end
    return o
end
local game=base({BeginDeferredActorSpawnFromClass=function()return actor()end,FinishSpawningActor=function(_,o)return o end,IsGamePaused=function()return world_paused end,GetRealTimeSeconds=function()return second end})
local camera_position,control_rotation,view_target
local pawn=base({CollisionSphereRadius=50,K2_SetActorLocation=function(_,position)
    camera_position=position
end})
local camera_rotation={Pitch=-60,Yaw=30,Roll=0}
local controller=base({PlayerCameraManager=base({GetCameraLocation=function()return {X=100,Y=200,Z=300}end,
    GetCameraRotation=function()return camera_rotation end}),K2_GetPawn=function()return pawn end,
    SetControlRotation=function(_,rotation)control_rotation=rotation end,
    SetViewTargetWithBlend=function(_,target)view_target=target end})
package.preload.UEHelpers=function()return {GetWorld=function()return world end,GetPlayerController=function()return controller end,GetGameplayStatics=function()return game end,FindOrAddFName=function(s)return s end}end
package.preload.terrain=function()return terrain end
package.preload.native_terrain=function()return {retain_texture=function()retained=retained+1 end} end
package.preload.entity_snow=function()return {sample=function()reads=reads+1;return depth,100,depth-fresh,fresh end}end
local time=base({GetTimeOfDayHours=function()return hour end,GetTotalGameHoursElapsed=function()return hours end,
    IsUIPaused=function()return ui_paused end,IsTimePaused=function()return false end,GetTimeRate=function()return 1 end})
local snow=base({IsCacheValid=function()return true end})
local trails=base({GetTrailAtPosition=function(_,p)return math.abs(p.X)<10 and 1 or 0 end})
local audio=base({Settings=base({WalkingSound=base(),MovementAttenuation=base()})})
local weather_type,freezing=0,true
local weather=base({GetWeatherType=function()return weather_type end,IsSnowingAtLocation=function()return freezing end,
    GetTemperatureAtLocation=function()return freezing and -5 or 3 end})
FindAllOf=function(name)return ({TimeSubsystem={time},SnowStateCache={snow},TrailMapSubsystem={trails},AmbientCrowdAudioSubsystem={audio},WeatherSubsystem={weather}})[name] or {} end
local material=base({SetTextureParameterValue=function()end,SetVectorParameterValue=function()end})
StaticFindObject=function(path)
    if path:find('KismetRenderingLibrary',1,true) then return base({ImportFileAsTexture2D=function()return base()end,
        ReadRenderTargetRawPixel=function()reads=reads+1;return{R=depth}end}) end
    if path:find('KismetMaterialLibrary',1,true) then return base({CreateDynamicMaterialInstance=function()return material end}) end
    return base({path=path})
end
local Api,Entities=require('api'),require('map_entities')
local files={'Assets/fox.skan','Assets/skin.png','Assets/eyeballs.png','Assets/fox-eyes.json','Assets/snow.png','Assets/fox-ground.json','Assets/pawprint.png'}
local coats={}
for i=1,16 do coats[i]=string.format('Assets/snow-coat-%02d.png',i);files[#files+1]=coats[i] end
local map={id='test.foxes',script={permissions={'gameplay'}},content={assets=files},__read=function(path)
    local f=assert(io.open('mod/SkiEO-Foxes/'..path,'rb'));local b=f:read('*a');f:close();return b
end}
local host={log=function()end,entity_action=function(api,name,...)return Entities[name](api,...)end}
local session=Api.new(host,{id='test.map',extensions={['test.foxes']={count=2}},script={permissions={'gameplay'}}})
local api=Api.new(host,map);api._session=session
assert(api:mapmod_options().count==2)
local options=api:mapmod_options();options.count=9;assert(api:mapmod_options().count==2)
api:mod_state({count=3}).count=4
local map_state=session:state({season=1})
assert(map_state.__mapmods['test.foxes'].count==4 and map_state.season==1,'dependency suppressed map defaults')
map_state.season=2
assert(session:state({season=1}).season==2,'defaults reset initialized state')
local restored=Api.new(host,{id='test.restored',script={permissions={'gameplay'}}})
restored._persistent={__mapmods={}}
assert(restored:state({season=1}).season==nil,'defaults changed restored state semantics')
local entity=api:spawn_animated(files[1],{files[2],files[3],files[5]},{aim_rig=files[4]})
entity:look_at(200,400,150,1,.1)
entity:pose('walk',.2,100,100,130,20);assert(updates==3 and created==1)
assert(api:environment().camera.z==300,'camera position was not exposed to the mapmod')
ui_paused=true;assert(api:environment().paused,'UI pause ignored');ui_paused=false
world_paused=true;assert(api:environment().paused,'world pause ignored');world_paused=false
assert(not api:environment().paused)
weather_type=2;api:environment();assert(not api:environment(100,100).heavy_snow,'light snowfall classified as a storm')
weather_type=3;api:environment();assert(api:environment(100,100).heavy_snow,'local blizzard was not exposed')
freezing=false;api:environment();assert(not api:environment(100,100).heavy_snow and api:environment(100,100).temperature_c==3,'rain below the snow line coats the fox')
weather_type=0;freezing=true;api:environment()
assert(api:focus_camera(100,100,165,500))
assert(view_target==pawn and control_rotation==nil,'camera focus changed the normal controlled view')
local dx,dy,dz=100-camera_position.X,100-camera_position.Y,165-camera_position.Z
local yaw,pitch=camera_rotation.Yaw*math.pi/180,camera_rotation.Pitch*math.pi/180
local forward={X=math.cos(pitch)*math.cos(yaw),Y=math.cos(pitch)*math.sin(yaw),Z=math.sin(pitch)}
local length=math.sqrt(dx*dx+dy*dy+dz*dz)
assert(math.abs((dx*forward.X+dy*forward.Y+dz*forward.Z)/length-1)<1e-6,'camera does not centre its target')
assert(camera_position.Z>=192 and math.abs(length-500)<1e-6,'camera focus entered the ground or ignored the distance')
assert(not pcall(api.focus_camera,api,30000,0,0),'camera target outside the map accepted')
assert(not pcall(api.focus_camera,api,0,0,0,1),'unbounded camera distance accepted')
assert(not pcall(entity.look_at,entity,0,0,0,2,.1),'unbounded gaze weight accepted')
assert(not pcall(api.spawn_animated,api,files[1],{files[2],files[3],files[5]},{aim_rig='../private'}),'undeclared aim rig accepted')
local surface=api:environment(100,100);assert(surface.inside and surface.snow_cm==12 and surface.z==142 and not surface.trail)
assert(api:environment(0,0).trail and not api:environment(30000,0).inside)
second=2;api:environment();reads=0
for _=1,10 do api:environment(100,100) end
assert(reads==1,'snow readback was repeated for the same cached pixel')
depth=100;second=4;api:environment()
assert(api:environment(100,100).z==230,'one metre of native snow buried the entities')
terrain.active.runtime.snow_surface_bias_centimeters=-12
assert(api:environment(100,100).z==218,'visual snow calibration was ignored')
assert(api:footprint(100,100,0))
terrain.active.runtime.snow_surface_bias_centimeters=nil
fresh=20;second=6;api:environment()
surface=api:environment(100,100)
assert(surface.packed_cm==80 and surface.fresh_cm==20,'native fresh/compact layers were lost')
local grounded=api:spawn_animated(files[1],{files[2],files[3],files[5]},
    {ground_rig=files[6],paw_texture=files[7],snow_sound=true,snow_coat=true,snow_textures=coats})
assert(shell_visible==false,'texture-based coat still displays the triangle-cut white shell')
local sets=material_sets;grounded:snow(.5);assert(material_sets==sets+1,'partial snow amount did not change the fur')
grounded:snow(.5);assert(material_sets==sets+1,'unchanged snow level repeated material uploads')
grounded:snow(1);grounded:snow(0);assert(material_sets==sets+3 and shell_visible==false,'storm/shake reactivated the white shell')
grounded:pose('walk',0,100,100,999,0,0,0,{emit=false})
assert(crunches==0,'initial/paused placement played a snow sound')
local result=grounded:pose('walk',.4,119.2,100,999,0,0,0,{emit=true})
assert(math.abs(result.z-(230-17-.010752))<.001 and result.roll==0,'grounded entity used its caller box height')
assert(#result.contacts>0 and crunches==1 and sounds==1,'paw collision did not stamp/play a local snow crunch')
second=7;grounded:pose('walk',.8,138.4,100,999,0,0,0,{emit=true})
assert(sounds==1 and crunches==2,'snow sounds allocated an unbounded emitter per contact')
local stopped=stops;grounded:pause();assert(stops==stopped+1,'pause did not silence the snow crunch')
assert(retained>=9,'entity textures/materials were left as weak Lua references')
assert(not pcall(api.spawn_animated,api,'../private',{}),'undeclared model accepted')
local denied=Api.new(host,{id='test.denied',content=map.content,__read=map.__read})
assert(not pcall(denied.spawn_animated,denied,files[1],{files[2],files[3],files[5]}))
assert(not pcall(denied.focus_camera,denied,100,100,165),'camera focus bypassed gameplay permission')
assert(not pcall(denied.bind_key,denied,'F8',function()end),'keyboard input bypassed gameplay permission')
for i=1,300 do assert(api:footprint(100,100,0)) end
assert(created==3,'footprints allocated unbounded actors')
local count=0;for _ in pairs(session._entities.tracks) do count=count+1 end
assert(count==256,'footprint ring exceeded its limit')
hours=7;second=8;api:expire_footprints();assert(next(session._entities.tracks)==nil,'tracks never expired')
depth=0;fresh=0;second=10;api:environment();assert(not api:footprint(100,100,0))
session:_stop();assert(destroyed==created,'map stop leaked actors')
assert(not pcall(entity.pose,entity,'idle',0,0,0,0,0),'old entity survived its map')
print('Map entities: assets, permissions, scope, animation, native surface, snow cache, bounded tracks, expiry and cleanup OK')
