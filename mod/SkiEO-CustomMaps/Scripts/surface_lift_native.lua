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
local visuals_loader
function Bridge.visuals(items,posed)
    local version=require('game_version').poll()
    assert(version.supported and reviewed[version.build],'Unreviewed surface lift visual bridge')
    for path,fields in pairs({GuestState={GuestId=0,QueueLiftId=0xa30,Discipline=0x1d},GuestHotState={ActivityState=0x68,WorldPosition=0,Velocity=0x18}}) do
        local found={}
        local cls=assert(StaticFindObject('/Script/SkiResortSimulator.'..path))
        cls:ForEachProperty(function(p)
            local name=p:GetFName():ToString()
            if fields[name] then assert(p:GetOffset_Internal()==fields[name],'Changed native guest field: '..name);found[name]=true end
        end)
        for name in pairs(fields) do assert(found[name],'Missing native guest field: '..name) end
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
return Bridge
