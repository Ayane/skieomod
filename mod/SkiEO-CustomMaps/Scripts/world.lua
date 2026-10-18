local UEHelpers = require('UEHelpers')
local Heightmap = require('heightmap')
local NativeTerrain = require('native_terrain')

-- The neutral engine map supplies world travel/lifecycle only. All map data
-- belongs to the portable source and is installed before World BeginPlay.
local World = { level = '/Engine/Maps/Entry', pending = nil, active = nil }
local function valid(object) return object and object:IsValid() end
local function transform(location)
    return { Rotation={X=0,Y=0,Z=0,W=1}, Translation=location or {X=0,Y=0,Z=0},
        Scale3D={X=1,Y=1,Z=1} }
end
local function spawn(world, class, pose, configure)
    local gameplay = UEHelpers.GetGameplayStatics()
    local actor = gameplay:BeginDeferredActorSpawnFromClass(world,
        StaticFindObject('/Script/' .. class),pose or transform(),1,nil,0)
    assert(valid(actor), 'could not create ' .. class)
    if configure then configure(actor) end
    return gameplay:FinishSpawningActor(actor,pose or transform(),0)
end
local function initialize(pending, world)
    local state = pending.state
    local system = UEHelpers.GetKismetSystemLibrary()
    World.previous_async_updates = system:GetConsoleVariableIntValue('AllowAsyncRenderThreadUpdates')
    system:ExecuteConsoleCommand(world, 'AllowAsyncRenderThreadUpdates 0', nil)
    World.previous_slate_throttling = system:GetConsoleVariableIntValue('Slate.bAllowThrottling')
    system:ExecuteConsoleCommand(world, 'Slate.bAllowThrottling 0', nil)
    for _, time in ipairs(FindAllOf('TimeSubsystem') or {}) do
        if valid(time) and time:GetWorld():GetAddress() == world:GetAddress() then
            if not pending.restoring then
                local date = time.GameTime
                date.Month, date.MonthPhase = 5, 0.5
                time.GameTime = date
            end
            time:PauseTime()
        end
    end
    local terrain = NativeTerrain.bootstrap_world(state,world)
    local environment = spawn(world,'SkiResortSimulator.LevelEnvironmentSettings',nil,function(actor)
        actor.LandscapeActor = terrain.landscape
        actor.HeightmapReference = terrain.height_texture
        actor.BiomeSettings = LoadAsset('/Game/Data/DA_BiomeSettings_Alps.DA_BiomeSettings_Alps')
        actor.WeatherMPC = LoadAsset('/Game/Materials/MPC_Weather.MPC_Weather')
        assert(valid(actor.BiomeSettings) and valid(actor.WeatherMPC),'environment assets are unavailable')
        -- Weather converts world Z against the Landscape's full quantized
        -- vertical span. R16 heights already include their absolute datum;
        -- adding height_offset again reports every elevation twice.
        actor.BaseElevationMeters = -state.origin_z / 100
        local native = state.native_encoding or state
        actor.PeakElevationMeters = actor.BaseElevationMeters + native.height_scale_cm * 65536 / 100
    end)
    local sun = spawn(world,'Engine.DirectionalLight',nil,function(actor)
        actor.LightComponent:SetMobility(2)
        actor.LightComponent:SetIntensity(5)
        actor.LightComponent:SetAtmosphereSunLight(true)
    end)
    local moon = spawn(world,'Engine.DirectionalLight',nil,function(actor)
        actor.LightComponent:SetMobility(2)
        actor.LightComponent:SetIntensity(0)
    end)
    spawn(world,'Engine.SkyAtmosphere')
    local sky = spawn(world,'Engine.SkyLight',nil,function(actor)
        local light = actor.LightComponent
        light:SetMobility(2)
        -- The cooked game's captured sky is supplied by its shared scene.
        -- A neutral world needs its own ambient source, including below the
        -- horizon, rather than capturing an empty/black scene.
        local cube = LoadAsset('/Engine/MapTemplates/Sky/DaylightAmbientCubemap.DaylightAmbientCubemap')
        assert(valid(cube), 'daylight ambient cubemap is unavailable')
        light.SourceType = 1
        light:SetRealTimeCapture(false)
        light:SetCubemap(cube)
        light.bLowerHemisphereIsBlack = false
        light:SetLowerHemisphereColor({R=0.15,G=0.18,B=0.22,A=1})
        light:SetIntensity(3)
    end)
    local post_process = spawn(world,'Engine.PostProcessVolume',nil,function(actor)
        actor.bUnbound = true
        actor.Settings.bOverride_AutoExposureBias = true
        actor.Settings.AutoExposureBias = -2
    end)
    -- This native controller tracks the calendar and weather, rotates the
    -- sun/moon and adjusts ambient light and exposure throughout the day.
    local lighting = spawn(world,'SkiResortSimulator.ClayEnvironmentController',nil,function(actor)
        actor.SunLight,actor.MoonLight,actor.SkyLight = sun,moon,sky
        actor.PostProcessVolume,actor.MPC_Weather = post_process,environment.WeatherMPC
        actor.SunIntensity_Day = 5
        actor.AutoExposureMinEV100,actor.AutoExposureMaxEV100 = 0,1
    end)
    sky.LightComponent:RecaptureSky()
    World.active = {map=pending.map,state=state,world_address=world:GetAddress(),
        environment=environment,lighting=lighting,sky=sky,restoring=pending.restoring}
    pending.initialized = true
    pending.log('independent world initialized from ' .. pending.map.id .. ' (no stock map loaded)')
end
function World.install()
    if World.installed then return end
    assert(type(RegisterInitGameStatePreHook)=='function','UE4SS world initialization hook is unavailable')
    World.init_callback = function(context)
        local mode = context:get()
        local world = mode:GetWorld()
        if not valid(world) then return end
        if world:GetFullName() ~= 'World /Engine/Maps/Entry.Entry' then
            World.restore_candidate = nil
            return
        end
        if not World.pending and World.restore_candidate and World.restore_handler then
            local saved = World.restore_candidate
            World.restore_candidate = nil
            local ok, message = pcall(World.restore_handler,saved)
            if not ok then print('[SkiEO-CustomMaps] save restoration failed: ' .. tostring(message) .. '\n') end
        end
        local pending = World.pending
        if not pending then return end
        World.pending = nil
        local ok,message = pcall(initialize,pending,world)
        if not ok then
            pending.error = tostring(message)
            pending.log('independent world initialization failed: ' .. pending.error)
            pending.failed(pending.error)
        end
    end
    RegisterInitGameStatePreHook(World.init_callback)
    World.installed = true
end
function World.prepare(map,log,failed,restoring)
    World.install()
    local state = NativeTerrain.prepare_world(Heightmap.load(map))
    World.active = nil
    World.pending = {map=map,state=state,log=log,failed=failed,restoring=restoring}
    return World.pending
end
function World.matches(map)
    local world = UEHelpers.GetWorld()
    return World.active and World.active.map == map and valid(world)
        and world:GetAddress() == World.active.world_address
end
function World.state(map)
    return World.active and World.active.map == map and World.active.state or nil
end
function World.pause_loading(map)
    if not World.matches(map) then return end
    local world = UEHelpers.GetWorld()
    for _, time in ipairs(FindAllOf('TimeSubsystem') or {}) do
        if valid(time) and time:GetWorld():GetAddress() == world:GetAddress() then
            if World.active.restoring then
                if World.active.loading_rate == nil then
                    World.active.loading_rate = time:GetTargetTimeMultiplier()
                end
                -- The restored native snow/guest simulations use the rate
                -- independently of the calendar's paused flag.
                time:SetTimeRate(0)
            end
            time:PauseTime()
        end
    end
end
function World.initialize_simulation(map)
    assert(World.matches(map), 'source world is unavailable')
    if World.active.simulation_initialized then return end
    local world = UEHelpers.GetWorld()
    local gameplay = UEHelpers.GetGameplayStatics()
    local mode = gameplay:GetGameMode(world)
    assert(valid(mode), 'source game mode is unavailable')
    if not World.active.restoring then
        mode:OpenSeason()
        mode.bIsOperatingSeason = true
        -- Console snow delegates resolve the game's gameplay world through
        -- GameInstance, which excludes Entry. Initialize the current world's
        -- native snow plane through reflected APIs instead. ClearSnow also
        -- invalidates resident tiles and CPU readback caches.
        local snow
        for _, candidate in ipairs(FindAllOf('SnowSimulationSubsystem') or {}) do
            if valid(candidate) and candidate:GetWorld():GetAddress() == world:GetAddress() then
                snow = candidate
                break
            end
        end
        assert(valid(snow) and valid(snow.CoarseMipRT), 'source snow plane is unavailable')
        local rendering = StaticFindObject('/Script/Engine.Default__KismetRenderingLibrary')
        assert(valid(rendering), 'snow initialization API is unavailable')
        snow:ClearSnow()
        rendering:ClearRenderTarget2D(world, snow.CoarseMipRT, {R=100,G=20,B=0,A=0})
    end
    local refreshed, message = NativeTerrain.refresh_navigation()
    assert(refreshed, message)
    World.active.simulation_initialized = true
end
function World.update_snow_lighting(map)
    if not World.matches(map) then return end
    local world = UEHelpers.GetWorld()
    local snow_class = StaticFindObject('/Game/EasySnow/Blueprints/BP_EasySnow_Games.BP_EasySnow_Games_C')
    if not valid(snow_class) then return end
    local strength = math.max(0, World.active.sky.LightComponent.Intensity) * 0.4
    for _,effects in ipairs(FindAllOf('WeatherEffectsSubsystem') or {}) do
        if valid(effects) and effects:GetWorld():GetAddress() == world:GetAddress() then
            local snow = effects.SnowDetailActor
            if valid(snow) and snow:GetClass():GetAddress() == snow_class:GetAddress() then
                local material = snow.spriteDynamicMaterial
                if valid(material) and (World.active.snow_material ~= material:GetAddress()
                    or math.abs(snow.snowEmissive.R - strength) > 0.001) then
                    -- Lit Niagara sprites have no useful ambient contribution
                    -- in this scene. Keep flakes visible in shade using their
                    -- existing MID parameter; follow native night/storm light.
                    local color = {R=strength,G=strength,B=strength,A=1}
                    snow.snowEmissive = color
                    material:SetVectorParameterValue(FName('snowEmissive'),color)
                    snow.CastShadow = false
                    if valid(snow.SnowNS) then snow.SnowNS:SetCastShadow(false) end
                    World.active.snow_material = material:GetAddress()
                end
            end
        end
    end
end
function World.finish_loading(map)
    assert(World.matches(map), 'source world is unavailable')
    local world = UEHelpers.GetWorld()
    for _,time in ipairs(FindAllOf('TimeSubsystem') or {}) do
        if valid(time) and time:GetWorld():GetAddress() == world:GetAddress() then
            if World.active.loading_rate ~= nil then time:SetTimeRate(World.active.loading_rate) end
            time:ResumeTime()
        end
    end
    World.active.loading_rate = nil
    World.update_snow_lighting(map)
    if World.previous_slate_throttling ~= nil then
        UEHelpers.GetKismetSystemLibrary():ExecuteConsoleCommand(world,
            'Slate.bAllowThrottling ' .. tostring(World.previous_slate_throttling),nil)
        World.previous_slate_throttling = nil
    end
end
function World.cancel()
    if World.active and World.active.loading_rate ~= nil and World.matches(World.active.map) then
        for _,time in ipairs(FindAllOf('TimeSubsystem') or {}) do
            if valid(time) and time:GetWorld():GetAddress() == World.active.world_address then
                time:SetTimeRate(World.active.loading_rate)
            end
        end
    end
    if World.previous_slate_throttling ~= nil then
        local world = UEHelpers.GetWorld()
        if valid(world) then
            UEHelpers.GetKismetSystemLibrary():ExecuteConsoleCommand(world,
                'Slate.bAllowThrottling ' .. tostring(World.previous_slate_throttling),nil)
        end
        World.previous_slate_throttling = nil
    end
    if World.previous_async_updates ~= nil then
        local world = UEHelpers.GetWorld()
        if valid(world) then
            UEHelpers.GetKismetSystemLibrary():ExecuteConsoleCommand(world,
                'AllowAsyncRenderThreadUpdates ' .. tostring(World.previous_async_updates), nil)
        end
        World.previous_async_updates = nil
    end
    World.pending,World.active,World.restore_candidate = nil,nil,nil
end
return World
