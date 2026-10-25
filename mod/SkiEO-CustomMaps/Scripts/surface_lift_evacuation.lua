local UE=require('UEHelpers')
local G=require('surface_lift_geometry')
local Routes=require('surface_lift_evacuation_routes')
local Evac={}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local exports={}
local reviewed=false
local function valid(o)return o and o:IsValid()end
local function unwrap(o)local ok,v=pcall(function()return o:get()end);return ok and v or o end
local function guid(g)return string.format('%08x-%08x-%08x-%08x',g.A,g.B,g.C,g.D)end
-- Group compact GUID words by native trail ID. Persisting a verbose lift GUID
-- for every skier would exhaust the script save budget on a busy resort.
local function persist(state)
    local groups={}
    for key,record in pairs(state.evacuation_records)do
        local words={};for word in key:gmatch('%x+')do words[#words+1]=string.format('%08x',tonumber(word,16)&0xffffffff)end
        assert(#words==4,'Invalid evacuation identity')
        local id=tostring(record.trail);groups[id]=groups[id]or{};groups[id][#groups[id]+1]=table.concat(words)
    end
    local packed={};for id,guests in pairs(groups)do table.sort(guests);packed[id]=table.concat(guests)end
    local saved=state.api:mod_state();saved.evacuation_guests=packed;saved.evacuations=nil
end
local function restore_guests(state,item)
    local saved=state.api:mod_state().evacuation_guests or{}
    for _,choice in ipairs(item.evacuation_routes)do
        local packed=saved[tostring(choice.trail)]or''
        assert(type(packed)=='string'and #packed%32==0 and not packed:find('[^%x]'),'Invalid saved evacuation guests')
        for i=1,#packed,32 do
            local words={};for n=0,3 do
                local word=tonumber(packed:sub(i+n*8,i+n*8+7),16)
                words[n+1]=word>=0x80000000 and word-0x100000000 or word
            end
            local key=guid({A=words[1],B=words[2],C=words[3],D=words[4]})
            state.evacuation_records[key]={lift=item.id,trail=choice.trail}
        end
    end
end
local function current(class)
    for _,o in ipairs(FindAllOf(class)or{})do
        if valid(o)and not o:GetFullName():find('Default__',1,true)and valid(o:GetWorld())
            and o:GetWorld():GetAddress()==UE.GetWorld():GetAddress()then return o end
    end
end
local function call(name,packet)
    local job=directory..'surface-'..name..'.job';local status=directory..'surface-'..name..'.status'
    local f=assert(io.open(job,'wb'));f:write(packet);f:close();os.remove(status)
    local symbol=name=='wait'and 'skieo_surface_wait'or 'skieo_surface_evacuate'
    exports[symbol]=exports[symbol]or assert(package.loadlib(directory..'skieo_surface_lifts.dll',symbol))
    exports[symbol]()
    f=assert(io.open(status,'rb'),'Native evacuation returned no status');local result=f:read('*a');f:close()
    assert(result:sub(1,3)=='ok:',result)
end
local function packet(state,entries,item)
    local guests=assert(state.guests);local trails=assert(state.groom_trails)
    local lift=item and item.lift
    return string.pack('<c4I4I4I4I8I8I8I8I8I8','SKEV',1,#entries,0,guests:GetAddress(),guests:GetClass():GetAddress(),
        trails:GetAddress(),trails:GetClass():GetAddress(),lift and lift:GetAddress()or 0,lift and lift:GetClass():GetAddress()or 0)..table.concat(entries)
end
local function waiting(state,force)
    local entries={}
    for _,item in ipairs(state.evacuation_disposing and{}or state.items)do if not item.disposed then
        local held=(item.evacuation_waiting or 0)>0
        if item.groom_trail then entries[#entries+1]={item.groom_trail,held and 1 or 0}end
        for _,choice in ipairs(item.evacuation_routes or{})do if choice.index>0 and choice.trail then
            entries[#entries+1]={choice.trail,(held or(choice.evacuation_waiting or 0)>0)and 1 or 0}
        end end
    end end
    table.sort(entries,function(a,b)return a[1]<b[1]end)
    local keys={};for _,entry in ipairs(entries)do keys[#keys+1]=entry[1]..':'..entry[2]end
    local key=table.concat(keys,',')
    if not force and key==state.evacuation_wait_key then return end
    local groom=current('GroomingSubsystem');assert(#entries==0 or valid(groom),'Native grooming unavailable during evacuation')
    local pieces={string.pack('<c4I4I4I4I8I8','SKWT',2,#entries,0,valid(groom)and groom:GetAddress()or 0,valid(groom)and groom:GetClass():GetAddress()or 0)}
    assert(#entries<=272,'Too many evacuation corridors')
    for i=1,272 do local entry=entries[i]or{0,0};pieces[#pieces+1]=string.pack('<i4I4',entry[1],entry[2])end
    call('wait',table.concat(pieces));state.evacuation_wait_key=key
end
local function registered(state,item,choice)
    if choice.index==0 then return item.groom_trail end
    local trails=state.groom_trails;local saved=state.api:mod_state()
    saved.evacuation_trails=saved.evacuation_trails or{}
    local owned=saved.evacuation_trails[item.id]or{};saved.evacuation_trails[item.id]=owned
    local key=tostring(choice.index);local id=owned[key]
    local name='Service escape · '..item.definition.name..' · '..key
    local width=Routes.dimensions(item.definition);local curves=Routes.curves(choice.points,width)
    local found
    trails.RegisteredTrails:ForEach(function(_,v)
        v=unwrap(v);local p,q=v.Curve.StartPoint,curves[1].StartPoint
        if v.bManuallyDisabled and v.DisplayName:ToString()==name and(not id or v.TrailId==id)
            and(p.X-q.X)^2+(p.Y-q.Y)^2<100^2 then found=v.TrailId end
    end)
    if not found then found=trails:RegisterTrailFromCurve(curves[1]);assert(found and found>0,'Emergency route rejected')end
    local extra={};for i=2,#curves do extra[#extra+1]=curves[i]end
    assert(trails:ReplaceTrailGeometry(found,curves[1],extra),'Emergency route geometry rejected')
    trails:SetTrailDisplayName(found,FText(name));trails:SetTrailGroomed(found,true);trails:SetTrailDisabled(found,true)
    owned[key]=found;state.groom_hidden[found]=true
    -- Authored forest exits are existing groomed passages. Use the native
    -- saved clearing zones so their trees stay clear across a save/reload.
    saved.evacuation_clearings=saved.evacuation_clearings or{}
    local signatures=saved.evacuation_clearings[item.id]or{};saved.evacuation_clearings[item.id]=signatures
    local parts={tostring(width)};local path={}
    for _,p in ipairs(choice.points)do
        parts[#parts+1]=string.format('%.1f,%.1f',p.x,p.y);path[#path+1]={X=p.x,Y=p.y,Z=p.z}
    end
    local geometry=table.concat(parts,';');local digest=0xcbf29ce484222325
    for i=1,#geometry do digest=(digest~geometry:byte(i))*0x100000001b3 end
    local signature=string.format('%016x',digest)
    if signatures[key]~=signature then
        local obstacles=current('ObstacleDataManager');assert(valid(obstacles),'Native forest clearing unavailable')
        obstacles:ClearObstaclesAlongCorridor(path,width*.5+250,false,true)
        signatures[key]=signature
    end
    return found
end
function Evac.attach(state,item)
    if not reviewed then
        local ok,detail=require('compatibility').check('surface_lifts.evacuation',{classes={
            ['/Script/SkiResortSimulator.GuestSimulationSubsystem']={Guests={type='ArrayProperty',offset=0x58},GuestsHot={type='ArrayProperty',offset=0x68}},
            ['/Script/SkiResortSimulator.GroomingSubsystem']={ActiveVehicles={type='ArrayProperty',offset=0x78}}},
            functions={['/Script/SkiResortSimulator.GuestSimulationSubsystem:OnLiftDeleted']={
                DeletedLiftId='StructProperty',Reason='EnumProperty'},
                ['/Script/SkiResortSimulator.ObstacleDataManager:ClearObstaclesAlongCorridor']={
                    Path='ArrayProperty',HalfWidth='FloatProperty',bRecordExpense='BoolProperty',bClearTreeCanopies='BoolProperty',ReturnValue='IntProperty'}}})
        assert(ok,detail)
        for name,fields in pairs({GuestState={GuestId=0,LateralBias=0x328,QueueLiftId=0xa30},
            GuestHotState={WorldPosition=0,ActivityState=0x68,CurrentTrailId=0x54},
            GuestRouteStep={Mode=0,TargetPosition=8,TrailId=0x54,TrailPath=0x58}})do
            local found={};local cls=assert(StaticFindObject('/Script/SkiResortSimulator.'..name))
            cls:ForEachProperty(function(p)local field=p:GetFName():ToString();if fields[field]then
                assert(p:GetOffset_Internal()==fields[field],'Changed evacuation field: '..name..'.'..field);found[field]=true
            end end)
            for field in pairs(fields)do assert(found[field],'Missing evacuation field: '..name..'.'..field)end
        end
        reviewed=true
    end
    item.evacuation_routes=Routes.build(item.route,item.definition,require('terrain').surface_height_at)
    for _,choice in ipairs(item.evacuation_routes)do
        choice.trail=registered(state,item,choice);choice.groom_trail=choice.trail;choice.groom_requests=0
    end
    state.guests=state.guests or current('GuestSimulationSubsystem')
    if not state.evacuation_records then
        state.evacuation_records={}
        -- Missing guests during native save restoration do not release a job.
        state.evacuation_restore_until=(require('map_entities').environment(state.api).seconds or 0)+5
        call('evacuation',packet(state,{}))
    end
    restore_guests(state,item)
    item.evacuation_waiting=0
    for _,record in pairs(state.evacuation_records)do if record.lift==item.id then item.evacuation_waiting=item.evacuation_waiting+1 end end
    if item.evacuation_waiting>0 then item.lift.OperatingSpeed=0 end
    waiting(state)
end
function Evac.release(state,item,passengers)
    if #passengers==0 then return end
    local entries={}
    for _,r in ipairs(passengers)do
        local distance=G.nearest(item.route,r.X,r.Y)
        local choice=Routes.choose(item.evacuation_routes,distance);local target=choice.points[#choice.points]
        local id=r.guest
        entries[#entries+1]=string.pack('<I4I4I4I4I4i4ddd',r.index,id.A&0xffffffff,id.B&0xffffffff,id.C&0xffffffff,id.D&0xffffffff,
            choice.trail,target.x,target.y,target.z)
        state.evacuation_records[r.key]={lift=item.id,trail=choice.trail}
    end
    persist(state)
    item.evacuation_waiting=#passengers;waiting(state)
    -- Reuse the public native release path for interactions, seats, queues and
    -- reservations. The bridge also performs normal unboarding accounting.
    -- The actor and its stable save GUID remain in the world.
    state.guests:OnLiftDeleted(item.lift:GetLiftId(),0)
    call('evacuation',packet(state,entries,item))
    item.evacuated=(item.evacuated or 0)+#passengers
    state.rider_scan=nil;state.rider_indices={}
    state.api:log(item.definition.name..': '..#passengers..' skieurs évacués par la voie de service')
end
function Evac.update(state,passengers,env)
    if env.paused or not state.evacuation_records then return end
    for _,item in ipairs(state.items)do
        if not item.disposed and item.evacuation_routes and #(passengers[item.id]or{})>0
            and(item.snow_blocked or item.requested_speed==0 or item.lift:GetEffectiveOperatingSpeed()<=.01)then
            Evac.release(state,item,passengers[item.id]);passengers[item.id]={}
            item.lift.OperatingSpeed=0
        end
    end
    if state.evacuation_scan and env.seconds-state.evacuation_scan<.25 then return end
    state.evacuation_scan=env.seconds
    local records=state.evacuation_records or{};local found={};local held={};local roads={}
    if next(records)then
        local guests=state.guests;local count=math.min(guests.Guests:GetArrayNum(),guests.GuestsHot:GetArrayNum())
        for index=1,count do
            local cold=guests.Guests[index];local key=guid(cold.GuestId);local record=records[key]
            if record then
                found[key]=true;local h=guests.GuestsHot[index];local p=h.WorldPosition;local near=false
                for _,item in ipairs(state.items)do if not item.disposed and item.groom_trail then
                    local width,offset=Routes.dimensions(item.definition)
                    local distance=G.nearest(item.route,p.X,p.Y);local line=G.sample(item.route,distance)
                    local x,y=line.x-line.nx*offset,line.y-line.ny*offset
                    -- Include a snowcat's footprint and both terminal exits.
                    if(p.X-x)^2+(p.Y-y)^2<(width*.5+400)^2 then
                        held[item.id]=(held[item.id]or 0)+1;near=true
                    end
                    for _,choice in ipairs(item.evacuation_routes or{})do if choice.index>0
                        and Routes.near(choice.points,p.X,p.Y,width*.5+400)then
                        roads[choice.trail]=(roads[choice.trail]or 0)+1;near=true
                    end end
                end end
                if not near and(h.ActivityState~=4 or h.CurrentTrailId~=record.trail)then records[key]=nil end
            end
        end
        for key,record in pairs(records)do if not found[key]then
            if env.seconds<(state.evacuation_restore_until or 0)then held[record.lift]=(held[record.lift]or 0)+1
            else records[key]=nil end
        end end
    end
    for _,item in ipairs(state.items)do if not item.disposed and item.evacuation_routes then
        local was=item.evacuation_waiting or 0;item.evacuation_waiting=held[item.id]or 0
        for _,choice in ipairs(item.evacuation_routes)do choice.evacuation_waiting=roads[choice.trail]or 0 end
        if item.evacuation_waiting>0 then item.lift.OperatingSpeed=0
        elseif was>0 then
            item.lift.OperatingSpeed=(item.snow_blocked or item.requested_speed==0)and 0 or item.definition.speed_mps*100
        end
    end end
    persist(state)
    waiting(state)
end
function Evac.remove(state,item)
    for _,choice in ipairs(item.evacuation_routes or{})do if choice.index~=0 and choice.trail then
        if valid(state.groom_trails)and valid(state.groom_trails:GetWorld())and state.groom_trails:GetWorld():GetAddress()==UE.GetWorld():GetAddress()then
            state.groom_trails:UnregisterTrail(choice.trail)
        end
        if state.groom_hidden then state.groom_hidden[choice.trail]=nil end
    end end
    local saved=state.api:mod_state();if saved.evacuation_trails then saved.evacuation_trails[item.id]=nil end
    item.evacuation_routes=nil;item.evacuation_waiting=0
end
function Evac.dispose(state)
    if state.evacuation_records then
        state.evacuation_disposing=true
        waiting(state,true)
    end
end
return Evac
