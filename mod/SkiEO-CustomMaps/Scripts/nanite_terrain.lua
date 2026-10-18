-- Optional Unreal cache beside the portable map. Missing/stale caches keep the
-- original renderer; terrain collision and simulation always use the R16.
local json = require('json')
local Snow = require('nanite_snow')
local Nanite = {validated_meshes={}}
local function valid(object) return object and object:IsValid() end
local function finite(value)
    return type(value)=='number' and value==value and math.abs(value)<math.huge
end
local function integer(value, maximum)
    return finite(value) and value>=0 and value%1==0 and value<maximum
end
local function read(path)
    if not path then return nil end
    local file=io.open(path,'rb'); if not file then return nil end
    local text=file:read(131073); file:close()
    assert(#text<=131072,'Nanite cache metadata exceeds 128 KiB')
    return text
end
-- UE4SS LoadAsset only searches the existing AssetRegistry. Newly mounted
-- IoStore packages need Unreal's soft-reference loader instead. Construct the
-- reference through UFUNCTIONs: a Lua table is not a TSoftObjectPtr.
function Nanite.load_asset(path,system)
    system=system or require('UEHelpers').GetKismetSystemLibrary()
    assert(valid(system),'KismetSystemLibrary unavailable')
    local soft_path=system:MakeSoftObjectPath(path)
    local reference=system:Conv_SoftObjPathToSoftObjRef(soft_path)
    local canonical=system:Conv_SoftObjectReferenceToString(reference)
    assert(canonical:ToString()==path,
        'UE4SS altered the soft package path: '..path)
    return system:LoadAsset_Blocking(reference)
end
function Nanite.has_validated_data(path,mesh)
    if not valid(mesh) then return false end
    if mesh:GetNumNaniteTriangles()>0 then
        Nanite.validated_meshes[path]=mesh
        return true
    end
    -- In shipping builds NaniteStreamingManager frees CPU RootData after GPU
    -- upload. GetNumNaniteTriangles then returns zero for a valid mesh. Reuse
    -- our initial validation only for the same still-live Unreal object.
    local previous=Nanite.validated_meshes[path]
    return valid(previous) and previous:GetAddress()==mesh:GetAddress() or false
end
function Nanite.cache_path(map)
    if map.__archive then return map.__manifest_path..'.nanite-5.8.json' end
    return map.__root and map.__root..'/Runtime/Nanite/cache.json'
end
function Nanite.covered_sections(entry)
    return entry.source_sections or {entry.section}
end
function Nanite.validate(cache,state)
    assert(cache.version==1 and cache.target_platform=='Windows' and cache.engine_family=='5.8'
        and (cache.mesh_algorithm==1 or cache.mesh_algorithm==2 or cache.mesh_algorithm==3)
        and cache.map_id==state.map.id,'incompatible Nanite cache')
    assert(cache.game_render_verified==true,'Nanite cache has not passed game validation')
    assert(cache.sample_step==math.max(1,math.floor(state.runtime.sample_step or 4))
        and cache.tile_quads==math.max(8,math.min(127,math.floor(state.runtime.tile_quads or 63)))
        and cache.uv_tile_meters==(state.runtime.uv_tile_meters or 20),'stale Nanite mesh settings')
    local definition=state.map.terrain.source
    for _,key in ipairs({'format','spacing_meters','height_scale_meters','height_offset_meters'}) do
        assert(cache.source[key]==definition[key],'stale Nanite source '..key)
    end
    assert(cache.source.row_order==(definition.row_order or 'north_to_south')
        and cache.source.vertices[1]==state.width and cache.source.vertices[2]==state.height,
        'stale Nanite source dimensions')
    local origin={state.origin_x,state.origin_y,state.origin_z}
    for axis=1,3 do assert(cache.source_origin_centimeters[axis]==origin[axis],'stale Nanite origin') end
    assert(type(cache.sections)=='table' and #cache.sections>0 and #cache.sections<=(cache.mesh_algorithm==3 and 128 or 64),'invalid Nanite section count')
    local seen,parts={},{ }
    for _,entry in ipairs(cache.sections) do
        local layer=entry.layer or 'terrain'
        assert(layer=='terrain' or layer=='snow' or (cache.mesh_algorithm==3 and Snow.is_coat(entry)),
            'invalid Nanite layer')
        if Snow.is_coat(entry) then
            assert(entry.coat_material=='/Game/Materials/Backgrounds/M_Snow.M_Snow','invalid snow coat material')
            local b=entry.snow_uv_bounds
            assert(type(b)=='table' and #b==2,'invalid snow coat bounds')
            for _,row in ipairs(b) do
                assert(type(row)=='table' and #row==2,'invalid snow coat bounds')
                for _,value in ipairs(row) do assert(finite(value) and value>=0 and value<=1,'invalid snow coat bounds') end
            end
            for axis=1,2 do assert(b[1][axis]<=b[2][axis],'invalid snow coat bounds') end
        end
        local covered=Nanite.covered_sections(entry)
        assert(type(covered)=='table' and #covered>0 and #covered<=64,'invalid covered section count')
        for _,section in ipairs(covered) do
            local key=layer..':'..tostring(section)
            if cache.mesh_algorithm==3 then
                assert(#covered==1 and integer(entry.parts,33) and entry.parts>0
                    and integer(entry.part,entry.parts),'invalid Nanite partition')
                local group=parts[key] or {count=0,total=entry.parts}
                assert(group.total==entry.parts,'inconsistent Nanite partition count')
                group.count=group.count+1;parts[key]=group
                key=key..':'..entry.part
            end
            assert(integer(section,state.section_count) and not seen[key],'invalid/duplicate Nanite section')
            seen[key]=true
        end
        assert(type(entry.asset)=='string' and #entry.asset<240
            and entry.asset:match('^/Game/CustomMaps/[A-Za-z0-9_/]+%.[A-Za-z0-9_]+$'),'invalid Nanite asset path')
        assert(type(entry.origin_meters)=='table' and #entry.origin_meters==3,'invalid Nanite mesh origin')
        for _,value in ipairs(entry.origin_meters) do assert(finite(value) and math.abs(value)<100000,'invalid Nanite mesh origin') end
    end
    if cache.mesh_algorithm==2 or cache.mesh_algorithm==3 then
        assert(cache.snow_offset_centimeters==(state.runtime.snow_offset_centimeters or 30),
            'stale Nanite snow offset')
        for _,entry in ipairs(cache.sections) do
            for _,section in ipairs(Nanite.covered_sections(entry)) do
                if cache.mesh_algorithm==3 then
                    local rock,snow=parts['terrain:'..section],parts['snow:'..section]
                    assert(rock and snow and rock.total==snow.total
                        and rock.count==rock.total and snow.count==snow.total,
                        'massif requires every rock and snow partition')
                    assert(entry.parts==rock.total,'snow coat partition count differs from terrain')
                else
                    assert(seen['terrain:'..section] and seen['snow:'..section],
                        'massif must replace both rock and snow')
                end
            end
        end
    end
    assert(type(cache.source_crc32)=='string' and cache.source_crc32:match('^[a-f0-9]+$')
        and #cache.source_crc32==8,'invalid Nanite checksum')
    state.nanite_source_crc32=state.nanite_source_crc32 or string.format('%08x',require('archive').crc32(state.bytes))
    assert(cache.source_crc32==state.nanite_source_crc32,'stale Nanite R16 checksum')
    return cache.sections
end
function Nanite.apply(terrain,schedule,done,log)
    local state=terrain.active
    if not state or not state.independent_world then done(); return end
    local ok,cache=pcall(function()
        local text=read(Nanite.cache_path(state.map))
        if not text then return nil end
        local decoded=json.decode(text)
        Nanite.validate(decoded,state)
        return decoded
    end)
    if not ok then log('Nanite cache skipped: '..tostring(cache)); done(); return end
    if not cache then done(); return end
    local generation,index=terrain.generation,1
    state.nanite_components={}
    local replacements={}
    local coats={}
    local coat_material
    local function source_visibility(source,entry,visible)
        if Snow.is_coat(entry) then return end
        for _,section in ipairs(Nanite.covered_sections(entry)) do
            source:SetMeshSectionVisible(section,visible)
        end
    end
    local function rollback()
        for _,replacement in ipairs(replacements) do
            pcall(source_visibility,replacement.source,replacement.entry,true)
            if valid(replacement.component) then replacement.component:K2_DestroyComponent(terrain.actor) end
        end
        state.nanite_components={}
    end
    local system=require('UEHelpers').GetKismetSystemLibrary()
    local available,enabled=pcall(function()
        return valid(system) and system:GetConsoleVariableIntValue('r.Nanite')==1
            and system:GetConsoleVariableIntValue('r.Nanite.ProjectEnabled')==1
    end)
    if not available or not enabled then
        log('Nanite cache skipped: Nanite is unavailable'); done(); return
    end
    local function next_section()
        if terrain.generation~=generation then return end
        local entry=cache.sections[index]
        if not entry then
            if cache.mesh_algorithm>=2 and #state.nanite_components~=#cache.sections then
                rollback();log('Nanite massif skipped: rock and snow must initialize together')
            else
                -- Partitioned caches hide a complete native section only once
                -- all its pieces and their snow shells are ready.
                if cache.mesh_algorithm==3 then
                    local activated,failure=pcall(function()
                        for _,replacement in ipairs(replacements) do
                            replacement.component:SetVisibility(not Snow.is_coat(replacement.entry),false)
                            source_visibility(replacement.source,replacement.entry,false)
                        end
                    end)
                    if not activated then
                        rollback();log('Nanite massif activation failed: '..tostring(failure));done();return
                    end
                end
                Snow.start(terrain,state,coats,schedule,log)
                log('Nanite terrain: '..#state.nanite_components..' mesh(es), original collision retained')
            end
            done();return
        end
        local component
        local source=(entry.layer=='snow' or Snow.is_coat(entry)) and terrain.snow_component or terrain.component
        local success,message=pcall(function()
            local mesh=Nanite.load_asset(entry.asset,system)
            assert(Nanite.has_validated_data(entry.asset,mesh),'Nanite mesh unavailable: '..entry.asset)
            assert(valid(source),'source '..tostring(entry.layer or 'terrain')..' component unavailable')
            local material
            if Snow.is_coat(entry) then
                if not valid(coat_material) then
                    coat_material=Snow.material(terrain.actor:GetWorld(),entry,function(path) return Nanite.load_asset(path,system) end)
                end
                material=coat_material
            else material=source:GetMaterial(Nanite.covered_sections(entry)[1]) end
            assert(valid(material) and material:GetBaseMaterial().bUsedWithNanite,'terrain material lacks its Nanite variant')
            local class=StaticFindObject('/Script/Engine.StaticMeshComponent')
            assert(valid(class),'StaticMeshComponent unavailable')
            local origin=entry.origin_meters
            component=terrain.actor:AddComponentByClass(class,false,{
                Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1},
                Translation={X=origin[1]*100,Y=origin[2]*100,Z=origin[3]*100}},false)
            assert(valid(component),'Nanite component creation failed')
            component:SetVisibility(false,false)
            component:SetCollisionEnabled(0)
            component:SetStaticMesh(mesh)
            component:SetForceDisableNanite(false)
            -- One deferred material assignment avoids parallel render-state updates.
            schedule(1,function()
                if terrain.generation~=generation or not valid(component) then return end
                local assigned,failure=pcall(function()
                    component:SetMaterial(0,material)
                end)
                if assigned then
                    schedule(1,function()
                        if terrain.generation~=generation or not valid(component) then return end
                        local installed,problem=pcall(function()
                            if cache.mesh_algorithm~=3 then component:SetVisibility(true,false) end
                            if cache.mesh_algorithm~=3 then source_visibility(source,entry,false) end
                            state.nanite_components[#state.nanite_components+1]=component
                            replacements[#replacements+1]={component=component,source=source,entry=entry}
                            if Snow.is_coat(entry) then coats[#coats+1]={component=component,material=material,entry=entry} end
                        end)
                        if not installed then
                            pcall(source_visibility,source,entry,true)
                            component:K2_DestroyComponent(terrain.actor)
                            log('Nanite section '..entry.section..' skipped: '..tostring(problem))
                        end
                        index=index+1; schedule(1,next_section)
                    end)
                else
                    component:K2_DestroyComponent(terrain.actor)
                    log('Nanite section '..entry.section..' skipped: '..tostring(failure))
                    index=index+1; schedule(1,next_section)
                end
            end)
        end)
        if not success then
            if valid(component) then component:K2_DestroyComponent(terrain.actor) end
            log('Nanite section '..entry.section..' skipped: '..tostring(message))
            index=index+1; schedule(1,next_section)
        end
    end
    schedule(1,next_section)
end
return Nanite
