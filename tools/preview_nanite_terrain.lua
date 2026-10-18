-- Run through SkiEOLiveProbe after a complete custom-map load with its cache.
-- NaniteTerrainPreview={cache='Z:/.../cache.json',output='Z:/.../captures/',
--   camera={position={-1250,850,2100},target={-1650,1500,2210}}}
-- Captures the original PMC, installed Nanite and fallback with one camera.
local P=assert(Probe)
local settings=assert(NaniteTerrainPreview)
local resolution=settings.resolution_scale or 1
assert(resolution==1 or resolution==2,'capture resolution scale must be 1 or 2')
package.path=(settings.scripts or 'Z:/media/lycos/dev/extern/skieo/mod/SkiEO-CustomMaps/Scripts/')..'?.lua;'..package.path
local file=assert(io.open(settings.cache,'rb'))
local cache=require('json').decode(file:read('*a'));file:close()
local world,pc=P.helpers.GetWorld(),P.helpers.GetPlayerController()
local system,gameplay=P.helpers.GetKismetSystemLibrary(),P.helpers.GetGameplayStatics()
local qa={meshes={},callbacks={},previous_view=pc:GetViewTarget(),phase='original'}
P.nanite_terrain_preview=qa
for _,component in ipairs(P.actors('StaticMeshComponent')) do
    local mesh=component.StaticMesh
    if P.valid(mesh) then
        for _,entry in ipairs(cache.sections) do
            if mesh:GetFullName()=='StaticMesh '..entry.asset then
                -- UE releases CPU root pages after upload; the loader checks Nanite
                -- before the component initializes its render resources.
                qa.meshes[#qa.meshes+1]={component=component,entry=entry,visible=component:IsVisible()}
            end
        end
    end
end
assert(#qa.meshes==#cache.sections,'the loader did not install every Nanite section')
qa.source=qa.meshes[1].component:GetOwner()
local source
qa.sources={}
for _,component in ipairs(P.actors('ProceduralMeshComponent')) do
    if component:GetOwner():GetAddress()==qa.source:GetAddress() and component:GetNumSections()==64 then
        local layer=component:GetCollisionEnabled()~=0 and 'terrain' or 'snow'
        assert(not qa.sources[layer],'ambiguous source surface');qa.sources[layer]=component
        if layer=='terrain' then source=component end
    end
end
assert(P.valid(source) and source:GetNumSections()==64,'original collision mesh unavailable')
qa.source=source
local function visibility(item,value)
    if require('nanite_snow').is_coat(item.entry) then return end
    local source=assert(qa.sources[item.entry.layer or 'terrain'])
    for _,section in ipairs(item.entry.source_sections or {item.entry.section}) do source:SetMeshSectionVisible(section,value) end
end
for _,item in ipairs(qa.meshes) do
    item.source=assert(qa.sources[require('nanite_snow').is_coat(item.entry) and 'snow' or (item.entry.layer or 'terrain')])
    for _,section in ipairs(item.entry.source_sections or {item.entry.section}) do
        assert(not item.source:IsMeshSectionVisible(section),'original section was not hidden')
    end
    assert(item.component:GetCollisionEnabled()==0,'Nanite must not duplicate terrain collision')
end
for _,time in ipairs(FindAllOf('TimeSubsystem') or {}) do
    if P.valid(time) and time:GetWorld():GetAddress()==world:GetAddress() then
        qa.time=time;qa.was_paused=time:IsTimePaused();time:PauseTime()
    end
end
local function deferred(delay,callback)
    local pending
    pending=function()
        qa.callbacks[pending]=nil
        if qa.cleaned then return end
        local ok,message=pcall(callback)
        if not ok then P.log('NANITE TERRAIN PREVIEW FAILED '..tostring(message));qa.cleanup() end
    end
    qa.callbacks[pending]=true
    ExecuteInGameThreadWithDelay(delay,pending)
end
qa.cleanup=function()
    if qa.cleaned then return end
    qa.cleaned=true
    for _,item in ipairs(qa.meshes) do
        if P.valid(item.component) then
            item.component:SetForceDisableNanite(false)
            item.component:SetVisibility(item.visible,false)
            visibility(item,false)
        end
    end
    if P.valid(qa.previous_view) then pc:SetViewTargetWithBlend(qa.previous_view,0,0,0,false) end
    if P.valid(qa.camera) then qa.camera:K2_DestroyActor() end
    if P.valid(qa.time) and not qa.was_paused then qa.time:ResumeTime() end
    P.log('NANITE TERRAIN PREVIEW restored installed rendering, view and time; collision retained')
end
local camera=assert(settings.camera)
local delta={}
for i=1,3 do delta[i]=camera.target[i]-camera.position[i] end
local pose={Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1},
    Translation={X=camera.position[1]*100,Y=camera.position[2]*100,Z=camera.position[3]*100}}
qa.camera=gameplay:BeginDeferredActorSpawnFromClass(world,StaticFindObject('/Script/Engine.CameraActor'),pose,1,nil,0)
qa.camera=gameplay:FinishSpawningActor(qa.camera,pose,0)
qa.camera:K2_SetActorRotation({Pitch=math.deg(math.atan(delta[3],math.sqrt(delta[1]^2+delta[2]^2))),
    Yaw=math.deg(math.atan(delta[2],delta[1])),Roll=0},true)
qa.camera.CameraComponent:SetFieldOfView(camera.fov or 55)
pc:SetViewTargetWithBlend(qa.camera,0,0,0,false)
qa.capture=function()
    system:ExecuteConsoleCommand(world,'HighResShot '..resolution..' filename='..settings.output..
        (settings.prefix or 'veymont-')..qa.phase..'.png',pc)
    P.log('NANITE TERRAIN PREVIEW UE API capture '..qa.phase..'; sections='..#qa.meshes)
    if qa.phase=='original' then
        deferred(1500,function()
            qa.phase='nanite'
            for _,item in ipairs(qa.meshes) do
                item.component:SetVisibility(item.visible,false)
                visibility(item,false)
            end
            deferred(3000,qa.capture)
        end)
    elseif qa.phase=='nanite' then
        deferred(1500,function()
            qa.phase='fallback'
            for _,item in ipairs(qa.meshes) do item.component:SetForceDisableNanite(true) end
            deferred(3000,qa.capture)
        end)
    else deferred(1500,qa.cleanup) end
end
for _,item in ipairs(qa.meshes) do
    item.component:SetVisibility(false,false)
    visibility(item,true)
end
deferred(3000,qa.capture)
