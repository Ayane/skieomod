-- Map-scoped instance overrides. The game's class defaults are never changed.
local UEHelpers = require('UEHelpers')
local json = require('json')
local Objects = {}
local SOURCE = debug.getinfo(1, 'S').source:match('^@(.*[/\\])[^/\\]+$')
local TYPES = {IntProperty='integer', ByteProperty='integer', FloatProperty='number', DoubleProperty='number',
    BoolProperty='boolean', StrProperty='string', NameProperty='name', TextProperty='text'}
local CATALOG = require('object_catalog')
CATALOG[#CATALOG+1] = {
    id='skier', name='Skier / crowd renderer', class='/Script/SkiResortSimulator.CrowdRenderingActor', kind='skier', components={'CrowdISM','EquippedISM','SnowboardISM'}
}
local function valid(object) return object and object:IsValid() end
local function unwrap(value)
    local ok, nested = pcall(function() return value:get() end)
    return ok and nested or value
end
local function load(path)
    local object = StaticFindObject(path)
    if not valid(object) then object = LoadAsset(path) end
    assert(valid(object), 'Game resource unavailable: '..path)
    return object
end
local function path_of(object)
    if not valid(object) then return nil end
    return object:GetFullName():match('^[^ ]+ (.+)$')
end
local function property(object, name)
    local class, found = object:GetClass(), nil
    while valid(class) and not found do
        class:ForEachProperty(function(p)
            if p:GetFName():ToString() == name then found=p; return true end
        end)
        class = class:GetSuperStruct()
    end
    assert(found, 'Property unavailable in this game version: '..name)
    return found
end
local function target(object, field)
    local component, name = field:match('^([A-Za-z_][A-Za-z0-9_]*)%.([A-Za-z_][A-Za-z0-9_]*)$')
    if component then
        property(object, component)
        object = unwrap(object[component])
        assert(valid(object), 'Component unavailable: '..component)
        return object, name
    end
    assert(field:match('^[A-Za-z_][A-Za-z0-9_]*$'), 'Invalid object field')
    return object, field
end
local function belongs(object, world)
    if not valid(object) or not valid(world) then return false end
    if object:GetFullName():find('Default__', 1, true) then return false end
    local ok, candidate = pcall(function() return object:GetWorld() end)
    return ok and valid(candidate) and candidate:GetAddress() == world:GetAddress()
end

local function matches_instance(actor, guid)
    if not guid then return true end
    local ok,id=pcall(function() return actor:GetPlaceableId() end)
    if not ok or not id then return false end
    for _,key in ipairs({'A','B','C','D'}) do if id[key]~=guid[key] then return false end end
    return true
end

local function set_value(object, name, value)
    if name=='InstanceName' and object:IsA('/Script/SkiResortSimulator.PlaceableActor') then
        object:SetInstanceName(value)
    elseif name=='VariantId' and object:IsA('/Script/SkiResortSimulator.BuildingActor') then
        require('building_variants').apply(object,type(value)=='string' and value or value:ToString())
    else object[name]=value end
end

-- This captures actual reflected class defaults. Missing classes/properties
-- are omitted, never replaced by guessed numbers. It runs on the game thread.
function Objects.export()
    -- Class defaults belong to the process, not to a map. Reuse the capture
    -- across editor tests instead of reloading every class during world GC.
    if Objects.defaults_exported then return end
    if not SOURCE then return end
    local output = {version=1, source='Game class default objects', objects={}}
    local descriptors,seen={},{}
    for _,item in ipairs(CATALOG) do descriptors[#descriptors+1]=item;seen[item.class]=true end
    local base=load('/Script/SkiResortSimulator.PlaceableActor')
    for _,cls in ipairs(FindAllOf('BlueprintGeneratedClass') or {}) do
        local path=path_of(cls)
        if path and not seen[path] and (cls:IsChildOf(base)) then
            descriptors[#descriptors+1]={id=cls:GetFName():ToString(),name=cls:GetFName():ToString(),class=path,components={'MeshComponent','StartTerminalMesh','EndTerminalMesh'}};seen[path]=true
        end
    end
    for _, descriptor in ipairs(descriptors) do
        local ok, result = pcall(function()
            local class = load(descriptor.class)
            -- UE4SS wrappers are weak references. Loading the next cooked
            -- class can collect previously inspected CDOs during export.
            -- Retain Unreal references throughout this world's capture.
            if type(StaticConstructObject)=='function' then
                require('native_terrain').retain_texture(class)
            end
            local cdo = class:GetCDO()
            assert(valid(cdo), 'Class default object unavailable')
            if type(StaticConstructObject)=='function' then
                require('native_terrain').retain_texture(cdo)
            end
            local item = {id=descriptor.id, name=descriptor.name, class=descriptor.class, kind=descriptor.kind, placeable=class:IsChildOf(base), fields={}}
            local parent = class
            while valid(parent) and parent:GetFName():ToString() ~= 'Actor' do
                parent:ForEachProperty(function(p)
                    local name = p:GetFName():ToString()
                    local kind = TYPES[p:GetClass():GetFName():ToString()]
                    if kind and not item.fields[name] then
                        local readable, value = pcall(function()
                            local v = cdo[name]
                            if kind == 'name' or kind == 'text' or kind == 'string' then return type(v)=='string' and v or v:ToString() end
                            return v
                        end)
                        if readable and (type(value)=='number' or type(value)=='string' or type(value)=='boolean') then
                            item.fields[name] = {type=kind, default=value}
                        end
                    elseif p:IsA(PropertyTypes.ObjectProperty) then
                        local readable, asset = pcall(function() return path_of(unwrap(cdo[name])) end)
                        if readable and asset and asset:match('^/Game/') then
                            local asset_class = p:GetPropertyClass():GetFName():ToString()
                            if asset_class == 'StaticMesh' or asset_class == 'SoundBase' or asset_class == 'SoundWave' or asset_class == 'SoundCue' then
                                item.fields[name]={type=asset_class:find('Sound') and 'sound' or 'asset', default=asset}
                            end
                        end
                    end
                end)
                parent=parent:GetSuperStruct()
            end
            for _, component in ipairs(descriptor.components) do
                local readable, mesh = pcall(function()
                    local target_component=unwrap(cdo[component])
                    return path_of(unwrap(target_component.StaticMesh))
                end)
                if readable and mesh then
                    item.fields[component..'.StaticMesh']={type=component:find('ISM') and 'asset' or 'model', default=mesh}
                end
            end
            return item
        end)
        if ok then output.objects[#output.objects+1]=result end
    end
    if #output.objects == 0 then return end
    local path=SOURCE..'object-defaults.json'
    local file=io.open(path..'.part','wb')
    if file then
        file:write(json.encode(output));file:close()
        os.remove(path)
        Objects.defaults_exported = os.rename(path..'.part',path) and true or nil
    end
end

local function portable_model(actor, source, mesh)
    assert(source:IsA('/Script/Engine.StaticMeshComponent') and not source:IsA('/Script/Engine.InstancedStaticMeshComponent'),
        'Portable models require an individual StaticMeshComponent')
    assert(#mesh.vertices <= 150000 and #mesh.triangles <= 150000, 'Portable mesh is too large')
    local cls = load('/Script/ProceduralMeshComponent.ProceduralMeshComponent')
    local identity={Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1},Translation={X=0,Y=0,Z=0}}
    local replacement=actor:AddComponentByClass(cls,true,identity,false)
    assert(valid(replacement),'Could not create portable model component')
    local ok,message=pcall(function()
        replacement:K2_AttachToComponent(source,UEHelpers.FindOrAddFName(''),2,2,2,false)
        local vertices,normals,uv={},{},{}
        for i,v in ipairs(mesh.vertices) do vertices[i]={X=v[1],Y=v[2],Z=v[3]} end
        for i,v in ipairs(mesh.normals) do normals[i]={X=v[1],Y=v[2],Z=v[3]} end
        for i,v in ipairs(mesh.uv) do uv[i]={X=v[1],Y=v[2]} end
        replacement:CreateMeshSection(0,vertices,mesh.triangles,normals,uv,{},{},false)
        replacement:SetCollisionEnabled(0)
        local material=source:GetMaterial(0)
        replacement:SetMaterial(0,material)
        replacement:SetVisibility(true,false)
        source:SetVisibility(false,false)
    end)
    if not ok then replacement:K2_DestroyComponent(actor);error(message) end
    return replacement
end

function Objects.apply(api, edits, meshes)
    assert(type(edits)=='table' and #edits<=2048 and type(meshes)=='table','Invalid object overrides')
    local world = UEHelpers.GetWorld()
    assert(valid(world),'Map world unavailable')
    local state={seen={},restores={},replacements={}}
    local stopped=false
    local groups={}
    for _,edit in ipairs(edits) do
        assert(type(edit.object)=='string' and type(edit.field)=='string','Invalid object override')
        local group=groups[edit.object]
        if not group then
            group={class=load(edit.object),name=edit.object:match('%.([^%.]+)$'),edits={}}
            groups[edit.object]=group
        end
        group.edits[#group.edits+1]=edit
    end
    -- Defaults for the map are applied first, followed by this instance's
    -- differences. Later spawned actors receive only matching differences.
    for _,group in pairs(groups) do
        table.sort(group.edits,function(a,b) return not a.instance and b.instance~=nil end)
    end
    local function tick()
        if stopped then return false end
        for _,group in pairs(groups) do
            for _,actor in ipairs(FindAllOf(group.name) or {}) do
                if belongs(actor,world) and actor:GetClass():IsChildOf(group.class) then
                    local address=actor:GetAddress()
                    local seen=state.seen[address]
                    if not seen or not valid(seen.actor) then
                        seen={actor=actor,done={},attempts={}};state.seen[address]=seen
                    end
                    for index,edit in ipairs(group.edits) do
                        if not seen.done[index] and matches_instance(actor,edit.instance) then
                            local ok,message=pcall(function()
                                local object,name=target(actor,edit.field)
                                local prop=property(object,name)
                                local kind=TYPES[prop:GetClass():GetFName():ToString()]
                                local previous=object[name]
                                if edit.type=='model' and edit.value:match('^asset:') then
                                    assert(name=='StaticMesh' and prop:IsA(PropertyTypes.ObjectProperty),'Portable models replace StaticMesh components')
                                    local mesh=assert(meshes[edit.value:sub(7)],'Portable model resource unavailable')
                                    local visibility=object:IsVisible()
                                    local replacement=portable_model(actor,object,mesh)
                                    state.replacements[#state.replacements+1]={actor=actor,source=object,mesh=replacement,visible=visibility}
                                elseif edit.type=='asset' or edit.type=='model' or edit.type=='sound' then
                                    assert(prop:IsA(PropertyTypes.ObjectProperty),'Resource override requires an object property')
                                    local value=load(edit.value)
                                    assert(value:GetClass():IsChildOf(prop:GetPropertyClass()),'Replacement resource has the wrong class')
                                    state.restores[#state.restores+1]={object=object,name=name,value=previous,mesh=name=='StaticMesh'}
                                    if name=='StaticMesh' then assert(object:SetStaticMesh(value),'Could not replace static mesh')
                                    else object[name]=value end
                                else
                                    assert(kind==edit.type or kind=='number' and edit.type=='integer','Property type differs from the source CSV')
                                    local value=edit.value
                                    if kind=='name' then value=UEHelpers.FindOrAddFName(value)
                                    elseif kind=='text' then value=FText(value) end
                                    state.restores[#state.restores+1]={object=object,name=name,value=previous}
                                    set_value(object,name,value)
                                end
                            end)
                            if ok then seen.done[index]=true
                            else
                                local attempts=(seen.attempts[index] or 0)+1;seen.attempts[index]=attempts
                                if attempts==1 or attempts==60 then api:log('Object override '..edit.field..' failed: '..tostring(message)) end
                                -- Components may not exist during the first construction
                                -- tick. Retry without reapplying successful differences.
                                if attempts>=60 then seen.done[index]=true end
                            end
                        end
                    end
                end
            end
        end
    end
    tick()
    api:every(500,tick)
    api:on('map.unloading',function()
        stopped=true
        for i=#state.restores,1,-1 do
            local item=state.restores[i]
            if valid(item.object) then pcall(function()
                if item.mesh then item.object:SetStaticMesh(item.value) else set_value(item.object,item.name,item.value) end
            end) end
        end
        for _,item in ipairs(state.replacements) do
            if valid(item.source) then pcall(function() item.source:SetVisibility(item.visible,false) end) end
            if valid(item.mesh) then pcall(function() item.mesh:K2_DestroyComponent(item.actor) end) end
        end
    end)
end
return Objects
