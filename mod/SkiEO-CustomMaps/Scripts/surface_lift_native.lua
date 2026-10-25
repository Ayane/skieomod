-- Reviewed on the exact 26143813 executable. The three floats are the cached
-- loop length and boarding/alighting distances in ULiftCableComponent. Updating
-- only CableSpline leaves these native markers stale and unloads riders early.
-- Disassembly: LiftActor::GetUphillCableLength delegates through CableComp;
-- native getter wraps (spline length + [0x138] - [0x134]) by spline length.
-- RebuildChairMeshes reads [0x130] for dispatch count, and [0x134] for phase.
local Bridge={}
local registered=false
local reviewed={['26143813']=true,['26178224']=true}
local names={'SkiEOTowLength','SkiEOTowBoard','SkiEOTowExit'}
function Bridge.prepare(lift)
    local version=require('game_version').poll()
    assert(version.supported and reviewed[version.build],
        'Surface lifts need a reviewed Ski-E-O executable')
    if not registered then
        local ok,detail=require('compatibility').check('surface_lifts.private_layout',{classes={
            ['/Script/SkiResortSimulator.LiftActor']={CableComp={type='ObjectProperty',offset=0x428},
                CableSpline={type='ObjectProperty',offset=0x3d8}},
            ['/Script/SkiResortSimulator.LiftCableComponent']={
                CableMeshSegments={type='ArrayProperty',offset=0xc0},CarrierActors={type='ArrayProperty',offset=0xd0}},
        }})
        assert(ok,detail)
        for i,name in ipairs(names) do RegisterCustomProperty({Name=name,Type=PropertyTypes.FloatProperty,
            BelongsToClass='/Script/SkiResortSimulator.LiftCableComponent',OffsetInternal=0x12c+i*4}) end
        registered=true
    end
    local c=lift.CableComp;local original={c.SkiEOTowLength,c.SkiEOTowBoard,c.SkiEOTowExit}
    local length=lift:GetCableLength()
    assert(length>1000 and math.abs(original[1]-length)<20,'Surface lift cable cache differs from its spline')
    for _,v in ipairs(original) do assert(v==v and v>=0 and v<=length+20,'Invalid native cable marker') end
    local up=(length+original[3]-original[2])%length
    assert(math.abs(up-lift:GetUphillCableLength())<1,'Native lift boarding layout changed')
    local phase=0;local t={}
    if lift.ChairISM:GetInstanceCount()>0 and lift.ChairISM:GetInstanceTransform(0,t,true) then
        local key=lift.CableSpline:FindInputKeyClosestToWorldLocation(t.Translation)
        phase=(lift.CableSpline:GetDistanceAlongSplineAtSplineInputKey(key)-original[2])%length
    end
    return original,phase
end
function Bridge.set(lift,board,exit)
    assert(exit>board,'Surface towing exit must follow boarding')
    return Bridge.set_loop(lift,board,exit)
end
function Bridge.set_loop(lift,board,exit)
    local c=lift.CableComp;local length=lift.CableSpline:GetSplineLength()
    assert(length>1000 and board>=0 and board<length and exit>=0 and exit<length and math.abs(exit-board)>1,
        string.format('Invalid towing markers: length=%s, board=%s, exit=%s',length,board,exit))
    c.SkiEOTowLength=length;c.SkiEOTowBoard=board;c.SkiEOTowExit=exit
end
function Bridge.restore(lift,original)
    local c=lift.CableComp
    for i,name in ipairs(names) do c[name]=original[i] end
end
local visuals_loader,visuals_reviewed
function Bridge.visuals(items,posed)
    local version=require('game_version').poll()
    assert(version.supported and reviewed[version.build],'Unreviewed surface lift visual bridge')
    if not visuals_reviewed then
    for path,fields in pairs({GuestSimulationSubsystem={Guests=0x58,GuestsHot=0x68},GuestState={GuestId=0,QueueLiftId=0xa30,Discipline=0x1d},GuestHotState={ActivityState=0x68,ColorIndex=0x50,WorldPosition=0,Velocity=0x18}}) do
        local found={}
        local cls=assert(StaticFindObject('/Script/SkiResortSimulator.'..path))
        cls:ForEachProperty(function(p)
            local name=p:GetFName():ToString()
            if fields[name] then assert(p:GetOffset_Internal()==fields[name],'Changed native guest field: '..name);local expected=({Guests='ArrayProperty',GuestsHot='ArrayProperty',GuestId='StructProperty',QueueLiftId='StructProperty',Discipline='EnumProperty',ActivityState='EnumProperty',ColorIndex='IntProperty',WorldPosition='StructProperty',Velocity='StructProperty'})[name];assert(p:GetClass():GetFName():ToString()==expected,'Changed native guest field type: '..name);found[name]=true end
        end)
        for name in pairs(fields) do assert(found[name],'Missing native guest field: '..name) end
    end
    visuals_reviewed=true
    end
    local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
    if not visuals_loader then visuals_loader=assert(package.loadlib(directory..'skieo_surface_lifts.dll','skieo_surface_lifts')) end
    local rows={}
    for _,item in ipairs(items or {}) do
        if not item.disposed and item.definition.kind~='fixed_chair' then
            local g=item.lift:GetLiftId()
            rows[#rows+1]=string.pack('<I4I4I4I4f',g.A&0xffffffff,g.B&0xffffffff,g.C&0xffffffff,g.D&0xffffffff,item.definition.speed_mps*100)
        end
    end
    assert(#rows<=16,'Too many native surface lifts')
    local bodies={}
    for _,g in ipairs(posed or {})do bodies[#bodies+1]=string.pack('<I4I4I4I4',g.A&0xffffffff,g.B&0xffffffff,g.C&0xffffffff,g.D&0xffffffff)end
    assert(#bodies<=64,'Too many posed surface lift passengers')
    local data=string.pack('<c4I4I4I4','SKTL',2,#rows,#bodies)..table.concat(rows)..string.rep('\0',(16-#rows)*20)
        ..table.concat(bodies)..string.rep('\0',(64-#bodies)*16)
    local f=assert(io.open(directory..'surface-lifts.job','wb'));f:write(data);f:close();visuals_loader()
    f=assert(io.open(directory..'surface-lifts.status','rb'));local status=f:read('*a');f:close()
    assert(status:sub(1,3)=='ok:',status)
    return status
end
local riders_loader
local riders_directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
function Bridge.riders(state,guests)
    assert(visuals_reviewed,'Guest snapshot requires the reviewed visual bridge')
    riders_loader=riders_loader or assert(package.loadlib(riders_directory..'skieo_surface_lifts.dll','skieo_surface_riders'))
    state.rider_nonce=((state.rider_nonce or 0)+1)&0xffffffff
    local f=assert(io.open(riders_directory..'surface-riders.job','wb'))
    f:write(string.pack('<c4I4I8I8I4I4','SKRD',1,guests:GetAddress(),guests:GetClass():GetAddress(),state.rider_nonce,0));f:close()
    os.remove(riders_directory..'surface-riders.bin');riders_loader()
    f=assert(io.open(riders_directory..'surface-riders.bin','rb'));local bytes=f:read('*a');f:close()
    assert(#bytes>=16,'Incomplete native rider snapshot')
    local magic,version,nonce,count=string.unpack('<c4I4I4I4',bytes)
    assert(magic=='SKRD'and version==1 and nonce==state.rider_nonce and count<=20000 and #bytes==16+count*72,'Invalid native rider snapshot')
    local groups=state.native_rider_groups or{};state.native_rider_groups=groups
    for _,rows in pairs(groups)do for i=#rows,1,-1 do rows[i]=nil end end
    local cache=state.native_rider_cache or{};state.native_rider_cache=cache
    for i=1,count do
        local index,discipline,color,_,a,b,c,d,la,lb,lc,ld,x,y,z=string.unpack('<I4I4i4I4i4i4i4i4i4i4i4i4ddd',bytes,17+(i-1)*72)
        local key=string.format('%08x-%08x-%08x-%08x',a,b,c,d)
        local id=string.format('%08x-%08x-%08x-%08x',la,lb,lc,ld)
        local row=cache[key]
        if not row then row={key=key,guest={A=a,B=b,C=c,D=d}};cache[key]=row end
        row.index,row.discipline,row.color,row.X,row.Y,row.Z=index,discipline,color,x,y,z
        row.stamp=nonce
        groups[id]=groups[id]or{};groups[id][#groups[id]+1]=row
    end
    for key,row in pairs(cache)do if row.stamp~=nonce then cache[key]=nil end end
    for id,rows in pairs(groups)do if #rows==0 then groups[id]=nil end end
    return groups
end
return Bridge
