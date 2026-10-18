-- Isolated UE4SS diagnostic through SkiEOLiveProbe. Captures use Unreal's API.
-- NaniteRockPreview = {report='Z:/.../cook-report.json', surface='Z:/.../surface.json',
--                     albedo='Z:/.../limestone-albedo.png', output='Z:/.../captures/'}
local P = assert(Probe, 'SkiEOLiveProbe is required')
local settings = assert(NaniteRockPreview, 'NaniteRockPreview settings are required')
package.path = (settings.scripts or 'Z:/media/lycos/dev/extern/skieo/mod/SkiEO-CustomMaps/Scripts/')..'?.lua;'..package.path
local json = require('json')
local function read_json(path)
    local file = assert(io.open(path, 'rb')); local text = file:read('*a'); file:close()
    return json.decode(text)
end
local report = read_json(settings.report)
local source = read_json(settings.surface)
assert(report.nanite_built == true and report.target_platform == 'Windows'
    and report.nanite_clusters > 0, 'a successful Windows Nanite cook is required')
local world, pc = P.helpers.GetWorld(), P.helpers.GetPlayerController()
local gameplay, system = P.helpers.GetGameplayStatics(), P.helpers.GetKismetSystemLibrary()
assert(P.valid(world) and P.valid(pc), 'game world is unavailable')
local qa = {actors={}, previous_view=pc:GetViewTarget(), phase='nanite'}
P.nanite_rock_preview = qa -- UE4SS callbacks need strong Lua references.
qa.cleanup = function()
    if qa.cleaned then return end
    qa.cleaned = true
    for name, value in pairs(qa.variables or {}) do
        pcall(function() system:ExecuteConsoleCommand(world,name..' '..value,nil) end)
    end
    if P.valid(qa.previous_view) then pc:SetViewTargetWithBlend(qa.previous_view,0,0,0,false) end
    for _, actor in ipairs(qa.actors) do if P.valid(actor) then actor:K2_DestroyActor() end end
    P.log('NANITE ROCK PREVIEW restored view, variables and temporary actors')
end
local function guarded(callback)
    return function()
        local ok,message = pcall(callback)
        if not ok then P.log('NANITE ROCK PREVIEW FAILED '..tostring(message)); qa.cleanup() end
    end
end
local function spawn(path, pose)
    local class = StaticFindObject(path)
    assert(P.valid(class), 'actor class unavailable: '..path)
    local actor = gameplay:BeginDeferredActorSpawnFromClass(world,class,pose,1,nil,0)
    assert(P.valid(actor), 'deferred actor spawn failed')
    qa.actors[#qa.actors+1] = actor
    actor = gameplay:FinishSpawningActor(actor,pose,0)
    assert(P.valid(actor), 'actor spawn failed')
    return actor
end
local function begin()
    qa.asset = require('nanite_terrain').load_asset(report.asset,system)
    assert(P.valid(qa.asset), 'Nanite pak must be mounted before starting the diagnostic')
    assert(qa.asset:GetNumNaniteTriangles()>0, 'loaded mesh has no Nanite triangles')
    local material = LoadAsset('/Game/Materials/M_Prop_albtex.M_Prop_albtex')
    assert(P.valid(material) and material.bUsedWithNanite,
        'the game material lacks a cooked Nanite variant; rendering cannot be validated with it')
    local origin, front = report.origin_meters, {}
    for i=1,3 do front[i] = source.basis_columns[i][3] end
    local pose = {Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1},
                  Translation={X=origin[1]*100,Y=origin[2]*100,Z=origin[3]*100}}
    qa.actor = spawn('/Script/Engine.Actor',pose)
    local component_class = StaticFindObject('/Script/Engine.StaticMeshComponent')
    assert(P.valid(component_class), 'StaticMeshComponent unavailable')
    qa.mesh = qa.actor:AddComponentByClass(component_class,false,
        {Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1},Translation={X=0,Y=0,Z=0}},false)
    assert(P.valid(qa.mesh), 'StaticMeshComponent creation failed')
    qa.mesh:SetCollisionEnabled(0)
    qa.mesh:SetStaticMesh(qa.asset)
    qa.mesh:SetForceDisableNanite(false)
    qa.actor:K2_SetActorLocation(pose.Translation,false,{},true)
    qa.camera = spawn('/Script/Engine.CameraActor',pose)
    local distance = math.max(source.spacing_meters[1]*(source.size[1]-1),
                              source.spacing_meters[2]*(source.size[2]-1))*1.8
    local camera = settings.camera or {position={origin[1]+front[1]*distance,
        origin[2]+front[2]*distance,origin[3]+front[3]*distance},target=origin}
    local delta = {}
    for i=1,3 do delta[i]=camera.target[i]-camera.position[i] end
    qa.camera:K2_SetActorLocation({X=camera.position[1]*100,
        Y=camera.position[2]*100,Z=camera.position[3]*100},false,{},true)
    qa.camera:K2_SetActorRotation({Pitch=math.deg(math.atan(delta[3],
        math.sqrt(delta[1]^2+delta[2]^2))),Yaw=math.deg(math.atan(delta[2],delta[1])),Roll=0},true)
    qa.camera.CameraComponent:SetFieldOfView(55)
    pc:SetViewTargetWithBlend(qa.camera,0,0,0,false)
    local sun = spawn('/Script/Engine.DirectionalLight',pose)
    local light = {}
    for i=1,3 do light[i]=.8*front[i]+.55*source.basis_columns[i][1]+.25*source.basis_columns[i][2] end
    sun.LightComponent:SetMobility(2)
    sun:K2_SetActorRotation({Pitch=-math.deg(math.atan(light[3],math.sqrt(light[1]^2+light[2]^2))),
        Yaw=math.deg(math.atan(-light[2],-light[1])),Roll=0},true)
    sun.LightComponent:SetIntensity(settings.light_intensity or 2)
    sun.LightComponent:SetLightColor({R=1,G=1,B=1,A=1},false)
    local rendering = StaticFindObject('/Script/Engine.Default__KismetRenderingLibrary')
    qa.texture = rendering:ImportFileAsTexture2D(world,settings.albedo)
    assert(P.valid(qa.texture), 'white albedo import failed')
    require('native_terrain').retain_texture(qa.texture)
    qa.material = StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary'):
        CreateDynamicMaterialInstance(world,material,FName('SkiEONaniteRockPreview'),0)
    qa.material:SetTextureParameterValue(FName('Albedo'),qa.texture)
    qa.mesh:SetMaterial(0,qa.material)
    qa.variables = {}
    for name,value in pairs({['r.Nanite']=1,['r.EyeAdaptationQuality']=0,
                              ['AllowAsyncRenderThreadUpdates']=0}) do
        qa.variables[name] = system:GetConsoleVariableIntValue(name)
        system:ExecuteConsoleCommand(world,name..' '..value,nil)
    end
    qa.capture = guarded(function()
        system:ExecuteConsoleCommand(world,'HighResShot 1 filename='..settings.output..
            (settings.prefix or '')..qa.phase..'.png',pc)
        P.log('NANITE ROCK PREVIEW UE API capture '..qa.phase..'; cooked clusters='..report.nanite_clusters)
        if qa.phase=='nanite' then ExecuteInGameThreadWithDelay(1500,qa.fallback)
        else ExecuteInGameThreadWithDelay(1500,qa.cleanup) end
    end)
    qa.fallback = guarded(function()
        qa.phase='fallback'
        qa.mesh:SetForceDisableNanite(true)
        ExecuteInGameThreadWithDelay(3000,qa.capture)
    end)
    ExecuteInGameThreadWithDelay(3000,qa.capture)
end
guarded(begin)()
