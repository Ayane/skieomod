-- Loaded only by tools/check_game_compatibility.py in its isolated game copy.
-- Keep callbacks strongly reachable and communicate with atomic JSON files.
return function(runtime,spec_path)
    local Json,Helpers=require('json'),require('UEHelpers')
    local file=assert(io.open(spec_path,'rb'));local spec=Json.decode(file:read('*a'));file:close()
    local Q={phase='boot',ticks=0,index=0,started=os.time(),spec=spec,
        result={run_id=spec.run_id,complete=false,maps_enabled=false,checks={}}}
    _G.SkiEOCompatibilityProbe=Q
    local function valid(o) return o and o:IsValid() end
    local function unwrap(value)
        local ok,nested=pcall(function() return value:get() end)
        return ok and nested or value
    end
    local function string_value(value)
        value=unwrap(value)
        return type(value)=='string' and value or value:ToString()
    end
    local function current(o)
        if not valid(o) or o:GetFullName():find('Default__',1,true) then return false end
        local ok,w=pcall(function() return o:GetWorld() end)
        return ok and valid(w) and w:GetAddress()==Helpers.GetWorld():GetAddress()
    end
    local function actors(class)
        local result={}
        -- UObject enumeration retains destroyed actor shells until GC. Use
        -- the native world iterator, as the runtime does when aligning a save.
        -- Keep identity/count comparisons strict for every live actor.
        local entries={}
        Helpers.GetGameplayStatics():GetAllActorsOfClass(Helpers.GetWorld(),
            StaticFindObject('/Script/SkiResortSimulator.'..class),entries)
        for _,entry in ipairs(entries) do
            local o=unwrap(entry)
            if current(o) and not o:IsActorBeingDestroyed() then result[#result+1]=o end
        end
        return result
    end
    local function subsystem(class)
        for _,o in ipairs(FindAllOf(class) or {}) do if current(o) then return o end end
    end
    local function write(name,value)
        local path=spec.root..name
        local stream=assert(io.open(path..'.part','wb'))
        assert(stream:write(Json.encode(value)));assert(stream:close())
        os.remove(path);assert(os.rename(path..'.part',path))
    end
    local function add(id,passed,detail,evidence)
        Q.result.checks[#Q.result.checks+1]={id=id,status=passed and 'pass' or 'fail',detail=detail,evidence=evidence}
        print('[Compatibility] '..id..': '..(passed and 'pass' or 'fail')..' '..detail..'\n')
    end
    local function properties(cls,inherited)
        local result,seen={},{}
        while valid(cls) and not seen[cls:GetAddress()] do
            seen[cls:GetAddress()]=true
            cls:ForEachProperty(function(p)
                local name=p:GetFName():ToString()
                if not result[name] then result[name]=p:GetClass():GetFName():ToString() end
            end)
            if not inherited then break end
            cls=cls:GetSuperStruct()
        end
        return result
    end
    local function reflection()
        local errors,observed={},{}
        for name,contract in pairs(spec.classes) do
            local path='/Script/SkiResortSimulator.'..name
            local cls=StaticFindObject(path)
            if not valid(cls) then errors[#errors+1]='missing class '..path
            else
                local fields=properties(cls,true)
                observed[name]={fields=fields,functions={}}
                for field,kind in pairs(contract.fields) do
                    if fields[field]~=kind then errors[#errors+1]=path..'.'..field..': expected '..kind..', found '..tostring(fields[field]) end
                end
                for _,method in ipairs(contract.functions) do
                    local fn=StaticFindObject(path..':'..method)
                    if not valid(fn) then errors[#errors+1]='missing function '..path..':'..method
                    else
                        local params=properties(fn,false)
                        observed[name].functions[method]=params
                        local expected=contract.function_parameters and contract.function_parameters[method]
                        if expected then
                            for key,kind in pairs(expected) do
                                if params[key]~=kind then errors[#errors+1]=name..':'..method..' parameter '..key..' changed' end
                            end
                            for key in pairs(params) do
                                if not expected[key] then errors[#errors+1]=name..':'..method..' unexpected parameter '..key end
                            end
                        end
                    end
                end
            end
        end
        write('reflection.json',{observed=observed,errors=errors})
        add('live.reflection',#errors==0,'native classes, property types and function parameters',{errors=errors})
        return #errors==0
    end
    local function isolation()
        local library=StaticFindObject('/Script/SkiResortSimulator.Default__SaveDumpLibrary')
        assert(valid(library),'save directory inspector unavailable')
        local directory=string_value(library:GetSaveGamesDir()):gsub('\\','/'):lower()
        local expected=(spec.root..'userdata/'):gsub('\\','/'):lower()
        local pass=directory:sub(1,#expected)==expected
        if spec.save_isolation then
            expected=spec.save_isolation.directory:gsub('\\','/'):lower():gsub('/+$','')
            directory=directory:gsub('/+$','')
            pass=false
            if directory==expected then
                local marker=io.open(directory..'/'..spec.save_isolation.marker,'rb')
                if marker then
                    local ok,proof=pcall(Json.decode,marker:read('*a'));marker:close()
                    pass=ok and type(proof)=='table' and proof.run_id==spec.run_id
                end
            end
        end
        add('live.isolation',pass,'actual save directory must belong to this test session',{directory=directory,expected=expected})
        return pass
    end
    local function screenshot(label)
        Helpers.GetKismetSystemLibrary():ExecuteConsoleCommand(Helpers.GetWorld(),
            'HighResShot 1280x720 filename="'..spec.root..label..'.png"',Helpers.GetPlayerController())
    end
    local function snapshot()
        local world=Helpers.GetWorld()
        local result={world=world:GetFullName(),world_address=world:GetAddress(),buildings=0,decorations=0,
            lifts=#actors('LiftActor'),hubs=#actors('HubActor'),trails=0,staff=0,trees=0,variants={},saved_variants={},
            invalid_marker_variants=0,buried_buildings=0,mesh_mismatches=0,placeables={}}
        local function remember(a,variant)
            local id=a:GetPlaceableId()
            local key=string.format('%08x%08x%08x%08x',id.A&0xffffffff,id.B&0xffffffff,id.C&0xffffffff,id.D&0xffffffff)
            local p=a:K2_GetActorLocation()
            assert(not result.placeables[key],'duplicate native placeable identity')
            result.placeables[key]={class=a:GetClass():GetFullName(),name=string_value(a:GetInstanceName()),
                variant=variant,position={X=p.X,Y=p.Y,Z=p.Z}}
        end
        for _,a in ipairs(actors('BuildingActor')) do
            local class=a:GetClass():GetFullName()
            if class:find('/Blueprints/Decorations/',1,true) then
                result.decorations=result.decorations+1
                local variant=a.VariantId:ToString()
                remember(a,variant)
                result.variants[variant]=(result.variants[variant] or 0)+1
                if class:find('BP_TrailMarkers',1,true) then
                    local color=({Beginner='Green',Intermediate='Blue',Expert='Black'})[variant]
                    local mesh=a.MeshComponent.StaticMesh:GetFullName()
                    if not color or not mesh:find('sm_prop_TrailMarker_'..color..'.',1,true) then
                        result.mesh_mismatches=result.mesh_mismatches+1
                    end
                    if variant~='Beginner' and variant~='Intermediate' and variant~='Expert' then
                        result.invalid_marker_variants=result.invalid_marker_variants+1
                    end
                    -- This inspects native serialization only. It is not a
                    -- substitute for saving to disk and restoring the world.
                    for k,v in pairs(a:GetSaveData().CustomData) do
                        if string_value(k)=='Variant' then
                            local saved=string_value(v)
                            result.saved_variants[saved]=(result.saved_variants[saved] or 0)+1
                            if saved~=variant then result.invalid_marker_variants=result.invalid_marker_variants+1 end
                        end
                    end
                end
            else
                remember(a)
                result.buildings=result.buildings+1
                if a.bIsBuried then result.buried_buildings=result.buried_buildings+1 end
            end
        end
        for _,a in ipairs(actors('LiftActor')) do remember(a) end
        local staff=assert(subsystem('StaffSubsystem'),'staff subsystem missing')
        result.staff=#staff:GetRoster()
        local trails=assert(subsystem('TrailMapSubsystem'),'trail map subsystem missing')
        trails.RegisteredTrails:ForEach(function() result.trails=result.trails+1 end)
        for _,component in ipairs(require('vegetation').components or {}) do
            assert(current(component),'forest component belongs to another world')
            result.trees=result.trees+component:GetInstanceCount()
        end
        local environment=assert(subsystem('LevelEnvironmentSettings'),'level environment missing')
        result.heightmap=environment.HeightmapReference:GetFullName()
        assert(result.heightmap:find('Texture',1,true),'native heightmap missing')
        result.loading=not not require('loading').active
        return result
    end
    local function compare(expected,actual)
        local differences={}
        for key,value in pairs(expected) do
            if actual[key]~=value then differences[#differences+1]=key..': expected '..tostring(value)..', found '..tostring(actual[key]) end
        end
        return differences
    end
    local function finish()
        Q.phase='done';Q.finish_time=os.time()
    end
    local function next_map()
        Q.index=Q.index+1
        local definition=spec.maps[Q.index]
        if not definition then finish();return end
        local map,message=require('catalog').load(definition.archive)
        assert(map,message)
        assert(map.id==definition.id and map.metadata.version==definition.version,'test archive identity differs from its contract')
        assert(runtime.start(map),'runtime rejected test map')
        Q.phase='loading';Q.started=os.time()
        print('[Compatibility] loading '..definition.id..'\n')
    end
    Q.step=function()
        Q.ticks=Q.ticks+1
        local stop=io.open(spec.root..'stop-request.json','rb')
        if stop then
            local ok,request=pcall(Json.decode,stop:read('*a'));stop:close()
            if ok and request.run_id==spec.run_id then Q.phase='exit' end
        end
        if Q.phase=='done' then
            if os.time()-Q.finish_time<3 then return end
            add('live.heartbeat',Q.ticks>=5,'game-thread polling stayed alive',{ticks=Q.ticks})
            Q.result.complete=true;write('live-result.json',Q.result)
            Q.phase=spec.interactive and Q.result.maps_enabled and 'review' or 'exit'
            return
        end
        if Q.phase=='review' then return end
        if Q.phase=='exit' then
            Helpers.GetKismetSystemLibrary():QuitGame(Helpers.GetWorld(),Helpers.GetPlayerController(),0,false)
            return
        end
        local world=Helpers.GetWorld()
        if not valid(world) or not valid(Helpers.GetPlayerController()) then return end
        write('heartbeat.json',{run_id=spec.run_id,phase=Q.phase,ticks=Q.ticks,updated=os.time()})
        if Q.phase=='boot' then
            if Q.ticks<5 then return end
            local isolated=isolation()
            local reflected=reflection()
            Q.result.maps_enabled=spec.allow_maps and isolated and reflected
            if Q.result.maps_enabled then next_map() else finish() end
            return
        end
        local definition=spec.maps[Q.index]
        local prefix='live.'..definition.id..'.'
        local api=runtime.active_api
        if Q.phase=='loading' then
            if api and api._loading_finished and api._loading_success==false then
                add(prefix..'counts',false,'map loading failed');finish();return
            end
            if os.time()-Q.started>spec.map_timeout then
                add(prefix..'counts',false,'map loading deadline exceeded');finish();return
            end
            if api and api._loading_success and not require('loading').active then
                Q.phase='settle';Q.started=os.time()
            end
        elseif Q.phase=='settle' and os.time()-Q.started>=spec.settle_seconds then
            Q.before=snapshot()
            write(definition.id..'-before-gc.json',Q.before)
            local differences=compare(definition.expected,Q.before)
            if Q.before.loading or Q.before.buried_buildings>0 then differences[#differences+1]='loading overlay or buried core building' end
            add(prefix..'counts',#differences==0,'ready world and station counts',{differences=differences})
            local variants=compare(definition.expected_variants,Q.before.variants)
            local saved=0;for _,n in pairs(Q.before.saved_variants) do saved=saved+n end
            local expected_markers=definition.expected_markers
            local pass=#variants==0 and Q.before.invalid_marker_variants==0
                and Q.before.mesh_mismatches==0 and saved==expected_markers
            add(prefix..'variants',pass,'native variant meshes and serialized marker variants',
                {variants=Q.before.variants,saved=Q.before.saved_variants,differences=variants})
            screenshot(definition.id..'-before-gc')
            Helpers.GetKismetSystemLibrary():CollectGarbage()
            Q.phase='postgc';Q.started=os.time()
        elseif Q.phase=='postgc' and os.time()-Q.started>=spec.settle_seconds then
            local after=snapshot()
            write(definition.id..'-after-gc.json',after)
            local keys={}
            for key in pairs(definition.expected) do keys[key]=Q.before[key] end
            keys.world_address,keys.heightmap=Q.before.world_address,Q.before.heightmap
            local differences=compare(keys,after)
            for _,field in ipairs({'variants','saved_variants'}) do
                for key,value in pairs(Q.before[field]) do
                    if after[field][key]~=value then differences[#differences+1]=field..': '..key..' changed after GC' end
                end
                for key in pairs(after[field]) do
                    if Q.before[field][key]==nil then differences[#differences+1]=field..': unexpected '..key end
                end
            end
            for id,first in pairs(Q.before.placeables) do
                local second=after.placeables[id]
                if not second then differences[#differences+1]='placeable identity lost: '..id
                else
                    for _,field in ipairs({'class','name','variant'}) do
                        if first[field]~=second[field] then differences[#differences+1]='placeable '..id..': '..field..' changed' end
                    end
                    for _,axis in ipairs({'X','Y','Z'}) do
                        if math.abs(first.position[axis]-second.position[axis])>1 then
                            differences[#differences+1]='placeable '..id..': position changed'
                        end
                    end
                end
            end
            for id in pairs(after.placeables) do
                if not Q.before.placeables[id] then differences[#differences+1]='unexpected placeable identity: '..id end
            end
            local pass=#differences==0 and not after.loading and api and api._loading_success==true
            add(prefix..'gc',pass,'world, terrain, objects and forest retained after forced GC',{differences=differences})
            screenshot(definition.id..'-after-gc')
            next_map()
        end
    end
    Q.callback=function()
        local ok,message=xpcall(Q.step,debug.traceback)
        if not ok then
            Q.result.error=tostring(message);Q.result.complete=true
            write('live-result.json',Q.result)
            print('[Compatibility] failure: '..tostring(message)..'\n')
            return true
        end
        return false
    end
    Q.handle=LoopInGameThreadWithDelay(1000,Q.callback)
    RegisterConsoleCommandHandler('compatibility_map',function(_,parameters)
        if Q.phase~='review' then return true end
        local wanted=parameters[1]
        for _,definition in ipairs(spec.maps) do
            if definition.id==wanted then
                ExecuteInGameThread(function()
                    local map,message=require('catalog').load(definition.archive)
                    assert(map,message);assert(runtime.start(map))
                end)
                break
            end
        end
        return true
    end)
    RegisterConsoleCommandHandler('compatibility_snapshot',function(_,parameters)
        if Q.phase~='review' then return true end
        local label=parameters[1]
        assert(type(label)=='string' and #label<=48 and label:match('^[%w_-]+$'),'invalid checkpoint label')
        ExecuteInGameThread(function()
            local ok,message=xpcall(function()
                local report=require('scenario_qa').capture(runtime,label)
                report.compatibility_world=snapshot()
                write('review/'..label..'.json',report)
                screenshot('review/'..label)
            end,debug.traceback)
            if not ok then print('[Compatibility] checkpoint failed: '..tostring(message)..'\n') end
        end)
        return true
    end)
end
