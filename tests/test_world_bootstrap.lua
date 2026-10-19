package.path = 'mod/SkiEO-CustomMaps/Scripts/?.lua;' .. package.path
local order, hook, current, commands = {}, nil, nil, {}
local address = 10
local function object(name)
    address = address + 1
    return { IsValid=function() return true end,GetAddress=function() return address end,
        GetFullName=function() return name end }
end
local old = object('World /Game/Maps/MainMenu.MainMenu')
local world = object('World /Engine/Maps/Entry.Entry')
old.GetAddress = function() return 1 end
world.GetAddress = function() return 2 end
current = old
local time = object('time')
time.rate=3
time.GetTargetTimeMultiplier=function(self) return self.rate end
time.SetTimeRate=function(self,rate) self.rate=rate end
time.GameTime={Month=0,MonthPhase=0}
time.GetWorld=function() return world end
time.PauseTime=function(self) self.paused=true end
time.ResumeTime=function(self) self.paused=false end
local foreign_time = object('foreign time')
foreign_time.GetWorld=function() return old end
foreign_time.PauseTime=function() error('paused another world') end
foreign_time.ResumeTime=function() error('resumed another world') end
local snow_class = object('snow class')
local snow_material = object('snow MID')
snow_material.updates = 0
snow_material.SetVectorParameterValue = function(self,name,color)
    assert(name=='snowEmissive');self.color=color;self.updates=self.updates+1
end
local snow = object('snow')
snow.GetClass=function() return snow_class end
snow.snowEmissive={R=0,G=0,B=0,A=0}
snow.CastShadow=true
snow.SnowNS={IsValid=function() return true end,
    SetCastShadow=function(_,value) assert(not value) end}
snow.spriteDynamicMaterial=snow_material
local effects=object('effects')
effects.GetWorld=function() return world end
effects.SnowDetailActor=snow
local foreign_effects=object('foreign effects')
foreign_effects.GetWorld=function() return old end
local snow_resets, snow_seeds = 0, 0
local simulation = object('native snow')
simulation.GetWorld=function() return world end
simulation.CoarseMipRT=object('native snow plane')
simulation.ClearSnow=function()
    snow_resets=snow_resets+1
    order[#order+1]='clear snow'
end
local foreign_snow=object('previous world snow')
foreign_snow.GetWorld=function() return old end
foreign_snow.ClearSnow=function() error('cleared saved snow in another world') end
local rendering=object('rendering library')
rendering.ClearRenderTarget2D=function(_,w,target,color)
    assert(w==world and target==simulation.CoarseMipRT)
    assert(order[#order]=='clear snow','resident snow tiles were not invalidated')
    assert(color.R==100 and color.G==20 and color.B==0 and color.A==0)
    snow_seeds=snow_seeds+1
end
local gameplay = {
    GetGameMode=function() return {IsValid=function() return true end,
        OpenSeason=function() order[#order+1]='season' end} end,
    GetPlayerController=function() return object('controller') end,
    BeginDeferredActorSpawnFromClass=function(_,w,class,pose)
        assert(w == world)
        order[#order+1] = 'spawn:' .. class
        local actor = object(class)
        actor.LightComponent = {SetMobility=function() end,
            SetIntensity=function(self,value) self.Intensity=value end,
            SetAtmosphereSunLight=function() end,
            SetRealTimeCapture=function(self,value) self.bRealTimeCapture=value end,
            SetCubemap=function(self,value) self.Cubemap=value end,
            SetLowerHemisphereColor=function(self,value) self.LowerHemisphereColor=value end,
            RecaptureSky=function(self) self.recaptured=true end}
        actor.Settings = {}
        actor.K2_SetActorRotation = function() end
        return actor
    end,
    FinishSpawningActor=function(_,actor) return actor end,
}
package.preload.UEHelpers = function() return {GetWorld=function() return current end,
    GetKismetSystemLibrary=function() return {ExecuteConsoleCommand=function(_,w,command)
        commands[#commands+1]=command
    end,GetConsoleVariableIntValue=function() return 1 end} end,
    GetGameplayStatics=function() return gameplay end} end
local terrain = { bootstrap_world=function(state,w)
    assert(w == world and time.paused and time.GameTime.Month==5);order[#order+1] = 'terrain'
    return {landscape=object('landscape'),height_texture=object('height')}
end,prepare_world=function(state) order[#order+1]='prepare';return state end,
refresh_navigation=function() order[#order+1]='navigation';return true end }
package.preload.native_terrain = function() return terrain end
package.preload.heightmap = function() return {load=function(map)
    assert(map.terrain);return {map=map,origin_z=12000,height_offset_cm=70000,height_scale_cm=2.5}
end} end
FindAllOf = function(class)
    if class=='TimeSubsystem' then return {time,foreign_time} end
    if class=='WeatherEffectsSubsystem' then return {effects,foreign_effects} end
    if class=='SnowSimulationSubsystem' then return {foreign_snow,simulation} end
    return {}
end
StaticFindObject = function(path)
    if path=='/Game/EasySnow/Blueprints/BP_EasySnow_Games.BP_EasySnow_Games_C' then return snow_class end
    if path=='/Script/Engine.Default__KismetRenderingLibrary' then return rendering end
    return path
end
FName=function(value) return value end
LoadAsset = function(path) return object(path) end
RegisterInitGameStatePreHook = function(callback) assert(not hook);hook=callback end
local World = require('world')
local map = {id='test.source',terrain={},game={template_level='/Game/Maps/Generated/Map_sugar_bowl_real'}}
local failed = nil
World.prepare(map,function() end,function(message) failed=message end)
assert(World.level == '/Engine/Maps/Entry')
assert(not World.matches(map))
local menu_context = {get=function() return {GetWorld=function() return old end} end}
hook(menu_context)
assert(World.pending and #order == 1,'unrelated world consumed pending bootstrap')
local context = {get=function() return {GetWorld=function() return world end} end}
hook(context)
assert(not failed,failed)
assert(order[2] == 'terrain','environment was initialized before source terrain')
assert(World.active.environment.LandscapeActor and World.active.environment.HeightmapReference)
assert(World.active.environment.BaseElevationMeters==-120,'source datum was added twice')
assert(World.active.environment.PeakElevationMeters==1518.4,'native vertical span was changed')
assert(World.active.sky.LightComponent.Cubemap and World.active.sky.LightComponent.SourceType==1)
assert(not World.active.sky.LightComponent.bRealTimeCapture and not World.active.sky.LightComponent.bLowerHemisphereIsBlack)
assert(World.active.lighting.SunLight and World.active.lighting.MoonLight
    and World.active.lighting.SkyLight==World.active.sky,'native lighting references are incomplete')
-- The sky light is a static daylight cubemap at intensity 3: the night value must stay below it.
assert(World.active.lighting.SkyLightIntensity_Night and World.active.lighting.SkyLightIntensity_Night < 3,
    'night sky light would make nights brighter than noon')
assert(not World.matches(map),'old world matched before travel completed')
current = world
assert(World.matches(map) and World.state(map).map == map)
World.initialize_simulation(map)
local simulation_count=#commands
assert(order[#order]=='navigation','native navigation was not invalidated after installing source heights')
assert(snow_resets==1 and snow_seeds==1,'new world snow was not initialized')
World.initialize_simulation(map)
assert(#commands==simulation_count and snow_resets==1 and snow_seeds==1,'initial snow was applied twice')
World.finish_loading(map)
assert(not time.paused,'loading did not resume the source simulation')
assert(commands[#commands]=='Slate.bAllowThrottling 1','UI throttling was not restored after loading')
assert(math.abs(snow_material.color.R-1.2)<0.0001 and not snow.CastShadow,'snow sprites stayed black')
World.update_snow_lighting(map)
assert(snow_material.updates==1,'unchanged snow material was updated again')
World.active.sky.LightComponent.Intensity=0.3
World.update_snow_lighting(map)
assert(math.abs(snow_material.color.R-0.12)<0.0001,'snow emission did not follow night lighting')
snow.snowEmissive={R=0,G=0,B=0,A=0}
World.update_snow_lighting(map)
assert(snow_material.updates==3,'weather preset reset was not corrected')
local count = #order
hook(context)
assert(#order == count,'world initialized twice')
World.cancel()
assert(not World.matches(map) and not World.state(map))
assert(commands[#commands]=='AllowAsyncRenderThreadUpdates 1','render setting was not restored')
-- Native saved state must survive reconstruction: no December reset, season
-- opening or replacement of the restored snowpack.
time.GameTime={Year=3,Month=2,MonthPhase=0.75}
terrain.bootstrap_world=function(_,w)
    assert(w==world and time.paused and time.GameTime.Month==2)
    return {landscape=object('landscape'),height_texture=object('height')}
end
World.restore_handler=function(saved)
    assert(saved.map==map)
    World.prepare(map,function() end,function(message) failed=message end,true)
end
World.restore_candidate={map=map}
hook(context)
assert(World.matches(map) and World.active.restoring)
World.pause_loading(map)
assert(time.rate==0,'restored native simulations kept their running multiplier during loading')
World.pause_loading(map)
assert(World.active.loading_rate==3,'loading overwrote the saved multiplier with zero')
assert(time.GameTime.Year==3 and time.GameTime.MonthPhase==0.75)
local season_count=#order
local before_restore_commands=#commands
World.initialize_simulation(map)
assert(#commands==before_restore_commands,'saved snowpack was replaced')
assert(snow_resets==1 and snow_seeds==1,'restored snowpack was cleared or reseeded')
assert(#order==season_count+1 and order[#order]=='navigation','saved season was reopened')
World.finish_loading(map)
assert(time.rate==3,'restored multiplier was not returned after reconstruction')
World.pause_loading(map)
World.cancel()
assert(time.rate==3,'cancellation kept the loading multiplier')
-- A bootstrap failure must be surfaced and must not match as a ready world.
terrain.bootstrap_world = function() error('source initialization failed',0) end
World.prepare(map,function() end,function(message) failed=message end)
hook(context)
assert(failed == 'source initialization failed' and not World.matches(map))
-- Cancellation invalidates pending initialization, including a later hook.
World.prepare(map,function() end,function() error('cancelled bootstrap ran') end)
World.cancel()
hook(context)
assert(not World.active)
print('Independent world: lifecycle ordering, identity, legacy metadata, failures and cancellation OK')
