local UEHelpers = require('UEHelpers')
local json = require('json')
local Saves = {}
local SOURCE_DIRECTORY=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local STATE_PREFIX = 'SkiEO.ScriptState.v1.'
-- Native scenario objective names are serialized in both synchronous and
-- asynchronous saves. Unknown names are ignored by the stock scenario system.
-- Chunked hexadecimal FNames keep state tied to the exact save slot/snapshot.
local function encode_state(map,state)
    local source = json.encode({map_id=map.id,state=state})
    assert(#source <= 32768, 'script save state exceeds 32 KiB')
    local encoded = source:gsub('.', function(c) return string.format('%02x',c:byte()) end)
    local names={}
    for offset=1,#encoded,900 do
        names[#names+1]=UEHelpers.FindOrAddFName(STATE_PREFIX..string.format('%03d.',(offset-1)//900+1)..encoded:sub(offset,offset+899))
    end
    return names,source
end
function Saves.store_state(save, map, state)
    if not state then return end
    local encoded=encode_state(map,state)
    local names={}
    save.ScenarioData.CompletedObjectives:ForEach(function(_,name)
        local ok,value=pcall(function() return name:get() end);if ok then name=value end
        if name:ToString():sub(1,#STATE_PREFIX)~=STATE_PREFIX then names[#names+1]=name end
    end)
    for _,name in ipairs(encoded) do names[#names+1]=name end
    save.ScenarioData.CompletedObjectives=names
end
function Saves.sync_native(api)
    if not api._persistent then return end
    local scenario=api._native_scenario
    -- A dependency can allocate its state before world travel. Do not write
    -- sandbox checkpoints into the previous world's subsystem during loading.
    if not scenario and api._loading_success ~= true then return end
    if scenario then assert(scenario:IsValid(),'script scenario is unavailable for saving') end
    local source = json.encode({map_id=api._map.id,state=api._persistent})
    local definition=api._scenario or {}
    local status=definition.status and definition.status() or 'active'
    local outcome=({active=0,completed=1,failed=2})[status]
    assert(outcome,'invalid script scenario status')
    if api._saved_script_source==source and api._saved_script_outcome==outcome then return end
    local names;names,source=encode_state(api._map,api._persistent)
    local system=require('scenario_host').subsystem('ScenarioSubsystem')
    local pieces={string.pack('<c4I4I8I8I8I4I4','SKIS',scenario and 1 or 2,system:GetAddress(),
        system:GetClass():GetAddress(),scenario and scenario:GetAddress() or 0,#names,outcome)}
    for _,name in ipairs(names) do pieces[#pieces+1]=string.pack('<I8',name:GetComparisonIndex()) end
    local path=assert(SOURCE_DIRECTORY)..'native_scenario.job'
    local file=assert(io.open(path,'wb'));assert(file:write(table.concat(pieces)));assert(file:close())
    local status_path=SOURCE_DIRECTORY..'native_terrain.status';os.remove(status_path)
    if not Saves.sync_callback then
        Saves.sync_callback=assert(package.loadlib(SOURCE_DIRECTORY..'skieo_native_terrain.dll','skieo_sync_scenario_state'))
    end
    local ok,message=pcall(Saves.sync_callback)
    os.remove(path)
    assert(ok,message)
    file=assert(io.open(status_path,'rb'));local result=file:read('*a');file:close()
    assert(result:sub(1,3)=='ok:',result)
    api._saved_script_source,api._saved_script_outcome=source,outcome
end
function Saves.read_state(save, map)
    if not save.ScenarioData then return nil end
    local chunks={}
    save.ScenarioData.CompletedObjectives:ForEach(function(_,name)
        local ok,value=pcall(function() return name:get() end);if ok then name=value end
        local text=name:ToString()
        if text:sub(1,#STATE_PREFIX)==STATE_PREFIX then
            local index,chunk=text:sub(#STATE_PREFIX+1):match('^(%d%d%d)%.([a-f0-9]+)$')
            assert(index and not chunks[tonumber(index)] and #chunk<=900,'invalid script save chunk')
            chunks[tonumber(index)]=chunk
        end
    end)
    if not next(chunks) then return nil end
    local count=0;for _ in pairs(chunks) do count=count+1 end
    local pieces={};for i=1,count do pieces[i]=assert(chunks[i],'missing script save chunk') end
    local encoded=table.concat(pieces)
    assert(#encoded<=65536 and #encoded%2==0,'invalid script save size')
    local source=encoded:gsub('%x%x',function(pair) return string.char(tonumber(pair,16)) end)
    local value=json.decode(source)
    assert(value.map_id==map.id and type(value.state)=='table','script state belongs to another map')
    return value.state
end
local function valid(object) return object and object:IsValid() end
function Saves.prepare_new(map,options)
    -- UE 5.8 GameSessionSubsystem's no-request path resumes the last resort.
    -- Clearing the reflected scenario/initial-save pointers alone still takes
    -- that path. Select native New Game explicitly before world travel.
    if not Saves.request_properties_installed then
        require('compatibility').require('saves.session_layout',require('compatibility_contracts').session)
        for _, field in ipairs({{'SkiEOPendingLoadSlot','StrProperty',0x30},
            {'SkiEOPendingNewGame','ByteProperty',0x41},
            {'SkiEOPendingResortName','StrProperty',0x48}}) do
            RegisterCustomProperty({Name=field[1],Type=PropertyTypes[field[2]],
                BelongsToClass='/Script/SkiResortSimulator.GameSessionSubsystem',OffsetInternal=field[3]})
        end
        Saves.request_properties_installed = true
    end
    local session = FindFirstOf('GameSessionSubsystem')
    assert(valid(session), 'game session is unavailable')
    if options then require('game_options').stage(session,options) end
    session.SkiEOPendingLoadSlot = ''
    session.PendingInitialSave,session.PendingScenario = nil,nil
    session.SkiEOPendingResortName = map.metadata.name
    session.SkiEOPendingNewGame = 1
end
local function guid_string(value)
    local library = StaticFindObject('/Script/Engine.Default__KismetGuidLibrary')
    local result = library:Conv_GuidToString(value):ToString():gsub('[^%x]', ''):lower()
    assert(#result == 32, 'invalid saved playthrough identifier')
    return result
end
local function unwrap(value)
    local ok, nested = pcall(function() return value:get() end)
    return ok and nested or value
end
function Saves.read_placeables(save)
    -- Copy reflected save data while it is alive. Never retain its UObject or
    -- UScriptStruct wrappers across world travel or garbage collection.
    local result = {}
    for _, field in ipairs({'Buildings', 'Lifts'}) do
        save[field]:ForEach(function(_, value)
            local saved = unwrap(value)
            local base = saved.BaseData
            local id = guid_string(base.ID)
            assert(not result[id], 'duplicate saved placeable identifier')
            local entry = {name=base.DisplayName:ToString()}
            if field == 'Buildings' then
                local function remember_variant(key, value)
                    key, value = unwrap(key), unwrap(value)
                    key = type(key)=='string' and key or key:ToString()
                    if key == 'Variant' then
                        value = type(value)=='string' and value or value:ToString()
                        if value~='' and value~='None' then entry.variant=value end
                    end
                end
                local custom = saved.CustomData
                if custom and type(custom.ForEach)=='function' then
                    custom:ForEach(remember_variant)
                else
                    for key, value in pairs(custom or {}) do remember_variant(key, value) end
                end
            end
            if field == 'Lifts' then
                local p = base.Transform.Translation
                entry.position = {X=p.X,Y=p.Y,Z=p.Z}
                for _, coordinate in pairs(entry.position) do
                    assert(coordinate == coordinate and math.abs(coordinate) < math.huge,
                        'invalid saved lift origin')
                end
            end
            result[id] = entry
        end)
    end
    return result
end
function Saves.restore_placeable(actor, entries)
    local entry = entries and entries[guid_string(actor:GetPlaceableId())]
    if not entry then return end
    -- Native LoadFromSaveData replaces an empty label with its type name.
    -- An empty saved label is still intentional and must survive a roundtrip.
    actor:SetInstanceName(FText(entry.name))
    if entry.variant then require('building_variants').apply(actor,entry.variant) end
    if not entry.position then return end
    local location = actor:K2_GetActorLocation()
    if math.abs(location.X-entry.position.X) < 0.001
        and math.abs(location.Y-entry.position.Y) < 0.001
        and math.abs(location.Z-entry.position.Z) < 0.001 then return end
    assert(actor:IsA('/Script/SkiResortSimulator.LiftActor'), 'saved lift class changed')
    -- Lift waypoints/towers are world-space geometry, already grounded by the
    -- terrain finalizer. Native loading also snaps the invisible actor origin
    -- to its quantized heightfield. Restore that origin without moving the
    -- grounded terminals, cables, queues or their attached children.
    local root = actor.RootComponent
    assert(valid(root), 'saved lift root is unavailable')
    local children = {}
    for _, value in ipairs(actor:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.SceneComponent'))) do
        local component = unwrap(value)
        local parent = component:GetAttachParent()
        if valid(parent) and parent:GetAddress() == root:GetAddress() then
            local pose, copy = component:K2_GetComponentToWorld(), {}
            for _, field in ipairs({'Translation','Rotation','Scale3D'}) do
                local vector = pose[field]
                copy[field] = {X=vector.X,Y=vector.Y,Z=vector.Z}
                if field == 'Rotation' then copy[field].W = vector.W end
            end
            children[#children+1] = {component=component,pose=copy,mobility=component.Mobility}
        end
    end
    local mobility = root.Mobility
    local ok, message = pcall(function()
        root:SetMobility(2)
        for _, child in ipairs(children) do child.component:SetMobility(2) end
        actor:K2_SetActorLocation(entry.position,false,{},true)
        for _, child in ipairs(children) do
            child.component:K2_SetWorldTransform(child.pose,false,{},true)
        end
        local restored = actor:K2_GetActorLocation()
        for _, axis in ipairs({'X','Y','Z'}) do
            assert(math.abs(restored[axis]-entry.position[axis]) <= 1, 'saved lift origin was not restored')
        end
    end)
    root:SetMobility(mobility)
    for _, child in ipairs(children) do child.component:SetMobility(child.mobility) end
    assert(ok, message)
end
local function metadata_path(guid)
    local library = StaticFindObject('/Script/SkiResortSimulator.Default__SaveDumpLibrary')
    local directory = library:GetSaveGamesDir():ToString():gsub('\\', '/')
    return directory .. '/SkiEO-CustomMap-' .. guid .. '.json'
end
local function read_map_id(guid)
    local file = io.open(metadata_path(guid), 'rb')
    if not file then return nil end
    local data = file:read('*a');file:close()
    local ok, info = pcall(json.decode, data)
    assert(ok and info.format == 'skieo-save-map' and info.version == 1
        and type(info.map_id) == 'string', 'invalid custom-map save association')
    return info.map_id
end
function Saves.bind(guid, map)
    assert(map.id:match('^[a-z0-9]+[._-][a-z0-9._-]+$'))
    local existing = read_map_id(guid)
    assert(not existing or existing == map.id, 'playthrough belongs to another custom map')
    if existing then return end
    local file = assert(io.open(metadata_path(guid), 'wb'))
    assert(file:write('{"format":"skieo-save-map","version":1,"map_id":"' .. map.id .. '"}\n'))
    assert(file:close())
end
function Saves.start_new(map)
    -- Native New Game assigns a fresh playthrough id. Direct custom travel
    -- must do the same, rather than reusing the previous game's autosave slots.
    if not Saves.properties_installed then
        require('compatibility').require('saves.session_layout',require('compatibility_contracts').session)
        for index = 0,3 do
            RegisterCustomProperty({Name='SkiEOPlaythroughWord' .. index,
                Type=PropertyTypes.UInt32Property,
                BelongsToClass='/Script/SkiResortSimulator.GameSessionSubsystem',
                OffsetInternal=0xA0+index*4})
        end
        Saves.properties_installed = true
    end
    local session = FindFirstOf('GameSessionSubsystem')
    assert(valid(session), 'game session is unavailable')
    local library = StaticFindObject('/Script/Engine.Default__KismetGuidLibrary')
    local guid = guid_string(library:NewGuid())
    Saves.bind(guid, map)
    for index = 0,3 do
        session['SkiEOPlaythroughWord' .. index] = tonumber(guid:sub(index*8+1,index*8+8),16)
    end
    return guid
end
function Saves.install()
    if Saves.creation_callback then return end
    Saves.creation_callback = function(object) Saves.latest_save = object end
    NotifyOnNewObject('/Script/SkiResortSimulator.SkiResortSaveGame', Saves.creation_callback)
end
function Saves.find_restore(maps)
    local result
    -- The load menu can leave thumbnail/autosave objects alive. The save
    -- created by the actual load request is the last one; older objects must
    -- not select another map or turn a stock-map load into a custom load.
    local candidates = Saves.creation_callback and {Saves.latest_save}
        or (FindAllOf('SkiResortSaveGame') or {})
    for _, save in ipairs(candidates) do
        if valid(save) and save.MapPath:ToString() == '/Engine/Maps/Entry'
            and save.SlotName:ToString() ~= '' then
            local guid = guid_string(save.PlaythroughId)
            local id = read_map_id(guid)
            local map
            if id then
                for _, candidate in ipairs(maps) do if candidate.id == id then map=candidate;break end end
                assert(map, 'saved custom map is not installed: ' .. id)
            else
                -- Earlier loader builds saved only Entry. There is no map id
                -- to recover; a single installed custom map is unambiguous.
                assert(#maps == 1, 'legacy save requires exactly one installed custom map')
                map = maps[1]
            end
            assert(not result or result.map == map, 'ambiguous pending custom-map saves')
            result = {map=map,guid=guid,legacy=not id,script_state=Saves.read_state(save,map),
                placeables=Saves.read_placeables(save),sandbox=save.bSandboxMode==true}
        end
    end
    if result then Saves.bind(result.guid, result.map) end
    return result
end
return Saves
