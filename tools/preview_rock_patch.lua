-- UE4SS diagnostic, run through SkiEOLiveProbe in an isolated game instance.
-- RockPatchPreview = { directory='Z:/.../surface/', output='Z:/.../proof/' }
-- This renders the exported vertices through PMC; it does not build Nanite.
local P = assert(Probe, 'SkiEOLiveProbe is required')
local settings = assert(RockPatchPreview, 'RockPatchPreview settings are required')
local package_root = settings.scripts or 'Z:/media/lycos/dev/extern/skieo/mod/SkiEO-CustomMaps/Scripts/'
package.path = package_root .. '?.lua;' .. package.path
local json = require('json')
local function read(path)
    local file = assert(io.open(path, 'rb')); local bytes = file:read('*a'); file:close()
    return bytes
end
local report = json.decode(read(settings.directory .. 'surface.json'))
local vertex_budget = settings.max_vertices or 65536
local triangle_budget = settings.max_triangles or 100000
assert(vertex_budget > 0 and vertex_budget <= 100000 and triangle_budget > 0
    and triangle_budget <= 200000, 'invalid diagnostic geometry budget')
local function number(value)
    local result = tonumber(value)
    assert(result and result == result and math.abs(result) < 1e9, 'invalid OBJ coordinate')
    return result
end
local function obj(path, center)
    local vertices, normals, uv, triangles = {}, {}, {}, {}
    for line in read(path):gmatch('[^\r\n]+') do
        local kind, a, b, c = line:match('^(%w+) (%S+) (%S+)%s*(%S*)')
        if kind == 'v' then
            vertices[#vertices+1] = {X=(number(a)-center[1])*100,
                Y=(number(b)-center[2])*100, Z=(number(c)-center[3])*100}
        elseif kind == 'vn' then
            normals[#normals+1] = {X=number(a), Y=number(b), Z=number(c)}
        elseif kind == 'vt' then uv[#uv+1] = {X=number(a), Y=number(b)}
        elseif kind == 'f' then
            local indices = {}
            for _, value in ipairs({a,b,c}) do
                local v,t,n = value:match('^(%d+)/(%d+)/(%d+)$')
                assert(v and v==t and v==n, 'preview expects the exporter unified OBJ indices')
                local index = number(v)
                assert(index>=1 and index<=#vertices, 'OBJ face index outside vertices')
                indices[#indices+1] = index-1
            end
            -- Portable OBJ uses CCW fronts; Unreal PMC uses CW fronts.
            for _, index in ipairs({indices[1], indices[3], indices[2]}) do
                triangles[#triangles+1] = index
            end
        end
        assert(#vertices<=vertex_budget and #triangles<=triangle_budget*3,
            'patch exceeds diagnostic memory budget')
    end
    assert(#vertices>0 and #normals==#vertices and #uv==#vertices and #triangles>0,
        'incomplete exported OBJ')
    return {v=vertices, n=normals, uv=uv, t=triangles}
end
local center = {}
for i=1,3 do
    center[i] = report.origin_meters[i]
        +report.basis_columns[i][1]*report.spacing_meters[1]*(report.size[1]-1)/2
        +report.basis_columns[i][2]*report.spacing_meters[2]*(report.size[2]-1)/2
end
local base = obj(settings.directory .. 'patch-base.obj', center)
local corrected = obj(settings.directory .. 'patch.obj', center)
assert(settings.allow_topology_change == true or (#base.v==#corrected.v and #base.t==#corrected.t),
    'base/corrected topology differs; volumetric preview requires explicit opt-in')
local world, pc = P.helpers.GetWorld(), P.helpers.GetPlayerController()
local g, sys = P.helpers.GetGameplayStatics(), P.helpers.GetKismetSystemLibrary()
assert(P.valid(world) and P.valid(pc), 'game world is unavailable')
local qa = {phase='base', actors={}, original_view=pc:GetViewTarget()}
P.rock_patch_preview = qa -- Retain delayed callbacks and wrappers.
qa.cleanup = function()
    if qa.cleaned then return end
    qa.cleaned = true
    if qa.previous_async then
        sys:ExecuteConsoleCommand(world,'AllowAsyncRenderThreadUpdates '..qa.previous_async,nil)
    end
    if qa.previous_exposure then
        sys:ExecuteConsoleCommand(world,'r.EyeAdaptationQuality '..qa.previous_exposure,nil)
    end
    if P.valid(qa.hidden_widget) then qa.hidden_widget:SetVisibility(qa.widget_visibility) end
    if P.valid(qa.original_view) then pc:SetViewTargetWithBlend(qa.original_view,0,0,0,false) end
    for _, item in ipairs(qa.actors) do if P.valid(item) then item:K2_DestroyActor() end end
    P.log('ROCK PATCH PREVIEW restored original view; temporary actors removed')
end
local function begin_preview()
    local pose = {Rotation={X=0,Y=0,Z=0,W=1},
        Translation={X=center[1]*100,Y=center[2]*100,Z=center[3]*100}, Scale3D={X=1,Y=1,Z=1}}
    local function spawn(class, transform)
        local actor = g:BeginDeferredActorSpawnFromClass(world, StaticFindObject(class), transform, 1, nil, 0)
        assert(P.valid(actor), 'actor spawn failed: ' .. class)
        actor = g:FinishSpawningActor(actor, transform, 0)
        qa.actors[#qa.actors+1] = actor
        return actor
    end
    local actor = spawn('/Script/Engine.Actor', pose)
    qa.mesh = actor:AddComponentByClass(StaticFindObject('/Script/ProceduralMeshComponent.ProceduralMeshComponent'),
        false, {Rotation={X=0,Y=0,Z=0,W=1},Translation={X=0,Y=0,Z=0},Scale3D={X=1,Y=1,Z=1}}, false)
    qa.mesh:SetCollisionEnabled(0)
    actor:K2_SetActorLocation(pose.Translation,false,{},true)
    P.log('ROCK PATCH PREVIEW mesh world location '..P.vec(actor:K2_GetActorLocation()))
    local front = {}; local light = {}
    local light_local = settings.light_local or {.55,.25,.8}
    for i=1,3 do
        front[i] = report.basis_columns[i][3]
        light[i] = light_local[3]*front[i]+light_local[1]*report.basis_columns[i][1]
            +light_local[2]*report.basis_columns[i][2]
    end
    local sun = spawn('/Script/Engine.DirectionalLight', pose)
    qa.sun = sun
    sun.LightComponent:SetMobility(2)
    sun:K2_SetActorRotation({Pitch=-math.deg(math.atan(light[3],math.sqrt(light[1]^2+light[2]^2))),
        Yaw=math.deg(math.atan(-light[2],-light[1])),Roll=0}, true)
    sun.LightComponent:SetIntensity(settings.light_intensity or .5)
    sun.LightComponent:SetLightColor({R=1,G=1,B=1,A=1}, false)
    if settings.fill_intensity then
        assert(settings.fill_intensity >= 0 and settings.fill_intensity <= 1,
            'invalid diagnostic fill intensity')
        local fill = spawn('/Script/Engine.DirectionalLight', pose)
        fill.LightComponent:SetMobility(2)
        fill.LightComponent:SetCastShadows(false)
        fill.LightComponent:SetIntensity(settings.fill_intensity)
        fill.LightComponent:SetLightColor({R=1,G=1,B=1,A=1},false)
        local f = {}
        for i=1,3 do f[i]=front[i]-.3*report.basis_columns[i][1]+.2*report.basis_columns[i][2] end
        fill:K2_SetActorRotation({Pitch=-math.deg(math.atan(f[3],math.sqrt(f[1]^2+f[2]^2))),
            Yaw=math.deg(math.atan(-f[2],-f[1])),Roll=0},true)
    end
    qa.camera = spawn('/Script/Engine.CameraActor', pose)
    local distance_multiplier = settings.camera_distance_multiplier or 2.5
    assert(distance_multiplier >= 1 and distance_multiplier <= 4, 'invalid diagnostic camera distance')
    local distance = math.max(report.spacing_meters[1]*(report.size[1]-1),
                              report.spacing_meters[2]*(report.size[2]-1))*distance_multiplier
    qa.camera:K2_SetActorLocation({X=(center[1]+front[1]*distance)*100,
        Y=(center[2]+front[2]*distance)*100,Z=(center[3]+front[3]*distance)*100},false,{},true)
    qa.camera:K2_SetActorRotation({Pitch=0,Yaw=math.deg(math.atan(-front[2],-front[1])),Roll=0},true)
    qa.camera.CameraComponent:SetFieldOfView(55)
    pc:SetViewTargetWithBlend(qa.camera,0,0,0,false)
    if settings.hide_menu and P.valid(pc.MainMenuWidget) then
        qa.hidden_widget = pc.MainMenuWidget
        qa.widget_visibility = qa.hidden_widget:GetVisibility()
        qa.hidden_widget:SetVisibility(1)
    end
    local rendering = StaticFindObject('/Script/Engine.Default__KismetRenderingLibrary')
    local albedo_path = assert(settings.albedo, 'albedo PNG path required')
    qa.texture = rendering:ImportFileAsTexture2D(world, albedo_path)
    assert(P.valid(qa.texture), 'albedo import failed')
    require('native_terrain').retain_texture(qa.texture)
    -- Load assets before calling UFunctions to avoid re-entering UE4SS wrappers.
    local material = LoadAsset('/Game/Materials/M_Prop_albtex.M_Prop_albtex')
    assert(P.valid(material), 'white rock material is unavailable')
    qa.material = StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary'):
        CreateDynamicMaterialInstance(world, material, FName('SkiEORockPatchPreview'), 0)
    qa.material:SetTextureParameterValue(FName('Albedo'), qa.texture)
    qa.previous_async = sys:GetConsoleVariableIntValue('AllowAsyncRenderThreadUpdates')
    qa.previous_exposure = sys:GetConsoleVariableIntValue('r.EyeAdaptationQuality')
    sys:ExecuteConsoleCommand(world,'AllowAsyncRenderThreadUpdates 0',nil)
    sys:ExecuteConsoleCommand(world,'r.EyeAdaptationQuality 0',nil)
    local function geometry(data)
        qa.mesh:CreateMeshSection(0,data.v,data.t,data.n,data.uv,{},{},false)
    end
    qa.capture = function()
        local ok,message = pcall(function()
            sys:ExecuteConsoleCommand(world,'HighResShot 1 filename='..settings.output..qa.phase..'.png',pc)
            local data = (qa.phase=='base' or qa.phase=='base_oblique') and base or corrected
            P.log('ROCK PATCH PREVIEW '..qa.phase..' UE API capture; vertices='..#data.v..' triangles='..#data.t/3)
            if qa.phase=='base' then ExecuteInGameThreadWithDelay(1500,qa.correct)
            elseif qa.phase=='corrected' and settings.oblique then
                ExecuteInGameThreadWithDelay(1500,qa.oblique)
            elseif qa.phase=='base_oblique' then
                ExecuteInGameThreadWithDelay(1500,qa.correct_oblique)
            else qa.complete=true;ExecuteInGameThreadWithDelay(1500,qa.cleanup) end
        end)
        if not ok then P.log('ROCK PATCH PREVIEW FAILED '..tostring(message));qa.cleanup() end
    end
    qa.correct = function()
        local ok,message = pcall(function()
            qa.phase='corrected'; geometry(corrected)
            ExecuteInGameThreadWithDelay(3000,qa.capture)
        end)
        if not ok then P.log('ROCK PATCH PREVIEW FAILED '..tostring(message));qa.cleanup() end
    end
    qa.oblique = function()
        local ok,message = pcall(function()
            qa.phase=settings.compare_oblique and 'base_oblique' or 'oblique'
            if settings.compare_oblique then geometry(base) end
            local d = distance
            local x = .88*front[1]+.48*report.basis_columns[1][1]
            local y = .88*front[2]+.48*report.basis_columns[2][1]
            qa.camera:K2_SetActorLocation({X=(center[1]+x*d)*100,Y=(center[2]+y*d)*100,
                Z=center[3]*100},false,{},true)
            qa.camera:K2_SetActorRotation({Pitch=0,Yaw=math.deg(math.atan(-y,-x)),Roll=0},true)
            for i=1,3 do light[i]=light_local[3]*front[i]-light_local[1]*report.basis_columns[i][1]
                +light_local[2]*report.basis_columns[i][2] end
            qa.sun:K2_SetActorRotation({Pitch=-math.deg(math.atan(light[3],math.sqrt(light[1]^2+light[2]^2))),
                Yaw=math.deg(math.atan(-light[2],-light[1])),Roll=0},true)
            ExecuteInGameThreadWithDelay(3000,qa.capture)
        end)
        if not ok then P.log('ROCK PATCH PREVIEW FAILED '..tostring(message));qa.cleanup() end
    end
    qa.correct_oblique = function()
        local ok,message = pcall(function()
            qa.phase='oblique';geometry(corrected)
            ExecuteInGameThreadWithDelay(3000,qa.capture)
        end)
        if not ok then P.log('ROCK PATCH PREVIEW FAILED '..tostring(message));qa.cleanup() end
    end
    geometry(base)
    qa.set_material = function()
        local ok,message = pcall(function()
            qa.mesh:SetMaterial(0,qa.material)
            ExecuteInGameThreadWithDelay(3000,qa.capture)
        end)
        if not ok then P.log('ROCK PATCH PREVIEW FAILED '..tostring(message));qa.cleanup() end
    end
    ExecuteInGameThreadWithDelay(250,qa.set_material)
end
local ok,message = pcall(begin_preview)
if not ok then
    P.log('ROCK PATCH PREVIEW FAILED '..tostring(message))
    qa.cleanup()
    error(message)
end
