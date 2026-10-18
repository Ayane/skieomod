package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Json=require('json')
local start=assert(loadfile('compatibility/ue4ss_probe.lua'))()
local oldopen,oldremove,oldrename,oldtime=io.open,os.remove,os.rename,os.time
local function exercise(allow_maps,isolated,missing_class,prefix_proof)
    local tick,callback,started=0,nil,0
    local written={}
    local world={IsValid=function() return true end}
    local spec={run_id='this-run',root='test-evidence/',allow_maps=allow_maps,classes=missing_class and {Missing={fields={},functions={}}} or {},maps={}}
    if prefix_proof then spec.save_isolation={directory='C:/test-prefix/SaveGames',marker='proof.json'} end
    io.open=function(path,mode)
        if path=='spec.json' then return {read=function() return Json.encode(spec) end,close=function() end} end
        if path=='test-evidence/stop-request.json' then return nil end
        if path=='c:/test-prefix/savegames/proof.json' then
            if prefix_proof=='missing' then return nil end
            return {read=function() return Json.encode({run_id=prefix_proof=='valid' and 'this-run' or 'old-run'}) end,close=function() end}
        end
        assert(mode=='wb')
        return {write=function(_,s) written[path]=s;return true end,close=function() return true end}
    end
    os.remove=function() end
    os.rename=function(a,b) written[b]=written[a];written[a]=nil;return true end
    os.time=function() return tick end
    StaticFindObject=function(path)
        if path:find('SaveDumpLibrary',1,true) then
            return {IsValid=function() return true end,GetSaveGamesDir=function()
                return isolated and (prefix_proof and 'C:/test-prefix/SaveGames/' or 'test-evidence/userdata/Saved/SaveGames') or 'user-saves/SaveGames'
            end}
        end
    end
    package.loaded.UEHelpers={GetWorld=function() return world end,GetPlayerController=function() return world end,
        GetKismetSystemLibrary=function() return {QuitGame=function() end} end}
    LoopInGameThreadWithDelay=function(ms,fn) assert(ms==1000);callback=fn;return 1 end
    RegisterConsoleCommandHandler=function(name,fn) assert((name=='compatibility_map' or name=='compatibility_snapshot') and type(fn)=='function') end
    start({start=function() started=started+1 end},'spec.json')
    collectgarbage('collect')
    for n=1,10 do tick=n;callback() end
    assert(started==0,'unsafe map load before successful preflight, reflection and isolation')
    local result=Json.decode(assert(written['test-evidence/live-result.json']))
    assert(result.complete and result.run_id=='this-run' and result.maps_enabled==false)
    local status={};for _,c in ipairs(result.checks) do status[c.id]=c.status end
    assert(status['live.heartbeat']=='pass')
    assert(status['live.isolation']==(isolated and (not prefix_proof or prefix_proof=='valid') and 'pass' or 'fail'))
    assert(status['live.reflection']==(missing_class and 'fail' or 'pass'))
end
exercise(false,true,false)
exercise(true,false,false)
exercise(true,true,true)
exercise(false,true,false,'valid')
exercise(true,true,false,'stale')
exercise(true,true,false,'missing')

local function map_cycle(lose_building,wrong_mesh,swap_ids,deleted_shell)
    local tick,callback,lost,captures,after_gc=0,nil,false,0,false
    local written={}
    local world={IsValid=function() return true end,GetAddress=function() return 77 end,GetFullName=function() return 'World /Engine/Maps/Entry.Entry' end}
    local function object(label)
        local id=0;for i=1,#label do id=id*33+label:byte(i) end
        return {IsValid=function() return true end,GetWorld=function() return world end,
            GetFullName=function() return label end,IsActorBeingDestroyed=function() return false end,
            GetClass=function() return {GetFullName=function() return label end} end,
            GetPlaceableId=function() return {A=0,B=0,C=0,D=id+(swap_ids and after_gc and 1 or 0)} end,
            GetInstanceName=function() return label end,K2_GetActorLocation=function() return {X=0,Y=0,Z=0} end}
    end
    local building=object('Building station')
    building.GetClass=function() return {GetFullName=function() return '/Game/Blueprints/Buildings/BP_TicketOffice.BP_TicketOffice_C' end} end
    local marker=object('Building marker')
    marker.GetClass=function() return {GetFullName=function() return '/Game/Blueprints/Decorations/BP_TrailMarkers.BP_TrailMarkers_C' end} end
    marker.VariantId={ToString=function() return 'Expert' end}
    marker.MeshComponent={StaticMesh={GetFullName=function()
        return 'StaticMesh /Game/Meshes/Props/sm_prop_TrailMarker_'..(wrong_mesh and 'Green' or 'Black')..'.mesh'
    end}}
    marker.GetSaveData=function() return {CustomData={
        [{get=function() return 'Variant' end}]={get=function() return 'Expert' end}}} end
    local staff=object('staff');staff.GetRoster=function() return {1,2} end
    local trails=object('trails');trails.RegisteredTrails={ForEach=function(_,fn) fn() end}
    local environment=object('environment');environment.HeightmapReference={GetFullName=function() return 'Texture2D source' end}
    FindAllOf=function(kind)
        if kind=='BuildingActor' and deleted_shell then
            return {building,marker,object('destroyed but still a valid UObject')}
        end
        return ({StaffSubsystem={staff},TrailMapSubsystem={trails},LevelEnvironmentSettings={environment}})[kind] or {}
    end
    package.loaded.vegetation={components={}}
    package.loaded.loading={active=false}
    package.loaded.catalog={load=function() return {id='test.map',metadata={version='1.0.0'}} end}
    local runtime={start=function(self) end}
    runtime.start=function(map)
        assert(map.id=='test.map');runtime.active_api={_loading_finished=true,_loading_success=true};return true
    end
    local spec={run_id='map-run',root='test-evidence/',allow_maps=true,classes={},settle_seconds=1,map_timeout=30,
        maps={{id='test.map',version='1.0.0',archive='archive',expected_markers=1,expected_variants={Expert=1},
            expected={buildings=1,decorations=1,lifts=1,hubs=1,trails=1,staff=2,trees=0}}}}
    io.open=function(path,mode)
        if path=='spec.json' then return {read=function() return Json.encode(spec) end,close=function() end} end
        if path=='test-evidence/stop-request.json' then return nil end
        assert(mode=='wb')
        return {write=function(_,data) written[path]=data;return true end,close=function() return true end}
    end
    os.remove=function() end
    os.rename=function(a,b) written[b]=written[a];return true end
    os.time=function() return tick end
    StaticFindObject=function(path)
        if path:find('/Script/SkiResortSimulator.',1,true) and not path:find('SaveDumpLibrary',1,true) then return path end
        assert(path:find('SaveDumpLibrary',1,true))
        return {IsValid=function() return true end,GetSaveGamesDir=function() return 'test-evidence/userdata/Saved/SaveGames' end}
    end
    package.loaded.UEHelpers={GetWorld=function() return world end,GetPlayerController=function() return world end,
        GetGameplayStatics=function() return {GetAllActorsOfClass=function(_,owner,class,entries)
            assert(owner==world)
            local kind=class:match('%.([^%.]+)$')
            local found=({BuildingActor=lost and {marker} or {building,marker},LiftActor={object('lift')},HubActor={object('hub')}})[kind] or {}
            for _,actor in ipairs(found) do entries[#entries+1]={get=function() return actor end} end
        end} end,
        GetKismetSystemLibrary=function() return {QuitGame=function() end,CollectGarbage=function() lost=lose_building;after_gc=true end,
            ExecuteConsoleCommand=function() captures=captures+1 end} end}
    LoopInGameThreadWithDelay=function(_,fn) callback=fn;return 1 end
    start(runtime,'spec.json')
    for n=1,15 do tick=n;callback() end
    local result=Json.decode(assert(written['test-evidence/live-result.json']))
    assert(result.complete and result.maps_enabled)
    local status={};for _,c in ipairs(result.checks) do status[c.id]=c.status end
    assert(not result.error,tostring(result.error))
    assert(status['live.test.map.counts']=='pass' and captures==2)
    assert(status['live.test.map.gc']==((lose_building or swap_ids) and 'fail' or 'pass'))
    assert(status['live.test.map.variants']==(wrong_mesh and 'fail' or 'pass'))
end
map_cycle(false,false)
map_cycle(true,false)
map_cycle(false,true)
map_cycle(false,false,true)
map_cycle(false,false,false,true)
io.open,os.remove,os.rename,os.time=oldopen,oldremove,oldrename,oldtime
print('Compatibility probe: isolation, retained callbacks, map loading, counts, GC loss and wrong variant meshes detected')
