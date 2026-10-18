-- Authored scene instances. Native saves own these actors after first creation.
local UEHelpers=require('UEHelpers')
local Terrain=require('terrain')
local Scene={}
local function valid(o) return o and o:IsValid() end
local function unwrap(o) local ok,v=pcall(function() return o:get() end);return ok and v or o end
local function in_world(o,world)
    if not valid(o) or o:GetFullName():find('Default__',1,true) then return false end
    local ok,w=pcall(function() return o:GetWorld() end)
    return ok and valid(w) and w:GetAddress()==world:GetAddress()
end
local function subsystem(name,world)
    for _,o in ipairs(FindAllOf(name) or {}) do if in_world(o,world) then return o end end
end
local function location(position,offset)
    local z=Terrain.surface_height_at(position[1],position[2])
    assert(type(z)=='number','Scene position is outside the final terrain')
    return {X=position[1],Y=position[2],Z=z+offset}
end
local function arrays(registry,created,remove)
    if not valid(registry) then return end
    for _,key in ipairs({'Buildings','Lifts','Snowblowers'}) do
        local entries,seen={},{}
        registry[key]:ForEach(function(_,remote)
            local o=unwrap(remote)
            if valid(o) then
                local owned=false;for _,actor in ipairs(created) do if actor:GetAddress()==o:GetAddress() then owned=true end end
                if not remove or not owned then entries[#entries+1]=o;seen[o:GetAddress()]=true end
            end
        end)
        if not remove then
            for _,actor in ipairs(created) do
                local target=actor:IsA('/Script/SkiResortSimulator.LiftActor') and 'Lifts'
                    or actor:IsA('/Script/SkiResortSimulator.SnowblowerActor') and 'Snowblowers'
                    or actor:IsA('/Script/SkiResortSimulator.BuildingActor') and 'Buildings'
                if target==key and not seen[actor:GetAddress()] then entries[#entries+1]=actor end
            end
        end
        registry[key]=entries
    end
end
function Scene.place(api,definitions)
    if api._restoring then return end -- Do not recreate buildings removed in a native save.
    local world=UEHelpers.GetWorld();assert(valid(world),'Scene world is unavailable')
    local statics=UEHelpers.GetGameplayStatics()
    local registry=subsystem('PlaceableRegistrySubsystem',world)
    assert(valid(registry),'Native placeable registry is unavailable')
    local created={}
    local function cleanup()
        pcall(arrays,registry,created,true)
        for i=#created,1,-1 do if valid(created[i]) then pcall(function() created[i]:K2_DestroyActor() end) end end
    end
    local ok,message=pcall(function()
        for _,definition in ipairs(definitions) do
            local cls=LoadAsset(definition.class);assert(valid(cls),'Scene class unavailable: '..definition.class)
            local position=location(definition.position_cm,definition.offset_cm or 0)
            local yaw=(definition.yaw or 0)*math.pi/360
            local transform={Translation=position,Rotation={X=0,Y=0,Z=math.sin(yaw),W=math.cos(yaw)},Scale3D={X=1,Y=1,Z=1}}
            local actor=statics:BeginDeferredActorSpawnFromClass(world,cls,transform,1,nil,0)
            assert(valid(actor),'Scene spawn failed: '..definition.id);created[#created+1]=actor
            assert(actor:IsA('/Script/SkiResortSimulator.PlaceableActor'),'Scene class must be a PlaceableActor')
            actor.bIsPreview=true
            actor=statics:FinishSpawningActor(actor,transform,0);assert(valid(actor),'Scene construction failed')
            created[#created]=actor
            actor:SetPreviewMode(true,true)
            actor.PlaceableComponent:GenerateNewId()
            actor.PlaceableComponent.PlaceableId=definition.guid
            if definition.kind=='lift' then
                assert(actor:IsA('/Script/SkiResortSimulator.LiftActor'),'Lift scene object must be a LiftActor')
                actor:Initialize(position,location(definition.end_position_cm,definition.offset_cm or 0))
                if definition.capacity then actor.Capacity=definition.capacity end
                if definition.dispatch_seconds then actor.DispatchIntervalSeconds=definition.dispatch_seconds end
                actor.HubId=definition.hub;actor.TopHubId=definition.top_hub
                actor:GenerateTowers();actor:Finalize()
            else actor.HubId=definition.hub end
            if definition.variant then
                assert(actor:IsA('/Script/SkiResortSimulator.BuildingActor'), 'Variants require a BuildingActor')
                actor:ApplyVariant(UEHelpers.FindOrAddFName(definition.variant))
                assert(actor.VariantId:ToString()==definition.variant, 'Scene variant unavailable: '..definition.variant)
            end
            actor:FinalizePlacement()
            -- Finalization can assign a generated label. Keep an empty
            -- instance name for the type default, or the authored custom name.
            actor:SetInstanceName(FText(definition.name))
        end
        arrays(registry,created,false)
        for _,name in ipairs({'GuestSimulationSubsystem','MilestoneObjectiveSubsystem','RoofSnowSubsystem','TutorialChecklistSubsystem','WalkNavSubsystem'}) do
            local o=subsystem(name,world);if valid(o) then pcall(function() o:HandlePlaceableRegistered() end) end
        end
    end)
    if not ok then cleanup();error(message,2) end
    api:on('map.unloading',cleanup)
    api:log('Created '..#created..' authored scene objects')
    return created
end
return Scene
