-- Maintenance corridors use native grooming jobs, staff and snowcats. They
-- remain closed to downhill guests. Only a moving native snowcat can grade
-- surplus snow; submitting a job never changes the snow or reopens a lift.
local UE=require('UEHelpers')
local G=require('surface_lift_geometry')
local Routes=require('surface_lift_evacuation_routes')
local Mesh=require('portable_mesh')
local Groom={}
local registered=false
local references
local grade_loader
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local function valid(o)return o and o:IsValid()end
local function current(class)
    for _,o in ipairs(FindAllOf(class)or{})do
        if valid(o)and not o:GetFullName():find('Default__',1,true)and valid(o:GetWorld())
            and o:GetWorld():GetAddress()==UE.GetWorld():GetAddress()then return o end
    end
end
Groom.dimensions=Routes.dimensions
local function point(p,offset)return{X=p.x-p.nx*offset,Y=p.y-p.ny*offset,Z=p.z}end
function Groom.curves(route,definition)
    return Routes.curves(Routes.service(route,definition),Groom.dimensions(definition))
end
local function widget(state)
    if valid(state.groom_widget)then return state.groom_widget end
    -- OnGroomNowClicked is the game's public request path. Its selected trail
    -- is private; the offset was reviewed on 26178224, anchored to the nearby
    -- reflected controls. Never use this layout on another executable.
    local version=require('game_version').poll()
    assert(version.supported and version.build=='26178224','Unreviewed native grooming request layout')
    local ok,detail=require('compatibility').check('surface_lifts.grooming',{classes={
        ['/Script/SkiResortSimulator.TrailEditWidget']={
            GroomNowButton={type='ObjectProperty',offset=0x1178},
            GroomNowReasonLabel={type='ObjectProperty',offset=0x1188}},
    },functions={['/Script/SkiResortSimulator.TrailEditWidget:OnGroomNowClicked']={}}})
    assert(ok,detail)
    if not registered then
        RegisterCustomProperty({Name='SkiEOGroomTrailId',Type=PropertyTypes.IntProperty,
            BelongsToClass='/Script/SkiResortSimulator.TrailEditWidget',OffsetInternal=0x138c})
        registered=true
    end
    local lib=Mesh.load('/Script/UMG.Default__WidgetBlueprintLibrary')
    state.groom_widget=lib:Create(UE.GetWorld(),Mesh.load('/Script/SkiResortSimulator.TrailEditWidget'),UE.GetPlayerController())
    assert(valid(state.groom_widget),'Could not create native grooming request controller')
    if not valid(references)then
        references=StaticConstructObject(Mesh.load('/Script/UMG.VerticalBox'),Mesh.load('/Engine/Transient'),0,0xC0,EInternalObjectFlags.RootSet,false,false,nil)
    end
    references:ClearChildren();references:AddChild(state.groom_widget)
    return state.groom_widget
end
function Groom.attach(state,item)
    local trails=current('TrailMapSubsystem');assert(valid(trails),'Native trail map unavailable for grooming')
    state.groom_trails=trails
    local stored=state.api:mod_state();stored.grooming_trails=stored.grooming_trails or{}
    local id=stored.grooming_trails[item.id]
    local name='Entretien de la montée · '..item.definition.name
    local legacy='Entretien TK · '..item.id
    local curves=Groom.curves(item.route,item.definition)
    local width=Groom.dimensions(item.definition)
    local found,update_geometry
    -- IDs come from the native save. A persisted ID alone is not ownership:
    -- a deleted trail's number may have been reused by a player's new piste.
    trails.RegisteredTrails:ForEach(function(_,v)
        local ok,n=pcall(function()return v:get()end);v=ok and n or v
        local text=v.DisplayName:ToString()
        local start=v.Curve.StartPoint;local expected=curves[1].StartPoint
        -- The old corridor was centred on the towing lane, 1.6 m from the
        -- pylons. Accept that owned geometry when upgrading an existing save.
        local previous=point(item.route.points[#item.route.points],160)
        local same_start=(start.X-expected.X)^2+(start.Y-expected.Y)^2<100^2
            or(start.X-previous.X)^2+(start.Y-previous.Y)^2<100^2
        local same_width=math.abs(v.Curve.CorridorWidth-width)<1 or math.abs(v.Curve.CorridorWidth-2000)<1 or math.abs(v.Curve.CorridorWidth-1000)<1 or math.abs(v.Curve.CorridorWidth-500)<1
        if (id and v.TrailId==id and same_start and same_width and v.bManuallyDisabled)
            or(not id and(text==name or text==legacy))then
            found=v.TrailId
            update_geometry=math.abs(v.Curve.CorridorWidth-width)>=1
                or(start.X-expected.X)^2+(start.Y-expected.Y)^2>=1
            if text==legacy then trails:SetTrailDisplayName(found,FText(name))end
        end
    end)
    if not found then
        found=trails:RegisterTrailFromCurve(curves[1]);assert(found and found>0,'Maintenance corridor rejected')
        local extra={};for i=2,#curves do extra[#extra+1]=curves[i]end
        assert(trails:ReplaceTrailGeometry(found,curves[1],extra),'Maintenance corridor geometry rejected')
        trails:SetTrailDisplayName(found,FText(name))
    elseif update_geometry then
        local extra={};for i=2,#curves do extra[#extra+1]=curves[i]end
        assert(trails:ReplaceTrailGeometry(found,curves[1],extra),'Maintenance corridor upgrade rejected')
    end
    trails:SetTrailGroomed(found,true);trails:SetTrailDisabled(found,true)
    item.groom_trail=found;stored.grooming_trails[item.id]=found
    item.groom_requests=0;item.groom_stamps=0
    -- Maintenance routes belong to snowcat navigation, not the downhill
    -- piste overlay. Keep their native jobs while excluding their ribbons.
    state.groom_hidden=state.groom_hidden or{};state.groom_hidden[found]=true
    local terrain=require('terrain');terrain.trail_visual_exclusions=state.groom_hidden
    terrain.rebuild_trail_visuals(true)
end
function Groom.remove(state,item)
    if item.groom_trail and valid(state.groom_trails)and valid(state.groom_trails:GetWorld())
        and state.groom_trails:GetWorld():GetAddress()==UE.GetWorld():GetAddress()then
        state.groom_trails:UnregisterTrail(item.groom_trail)
        state.api:mod_state().grooming_trails[item.id]=nil
    end
    if state.groom_hidden and item.groom_trail then state.groom_hidden[item.groom_trail]=nil end
    item.groom_trail=nil
end
function Groom.grade(state,stamps)
    if #stamps==0 then return end
    local snow=current('SnowSimulationSubsystem')
    assert(valid(snow),'Native snow simulation unavailable')
    if not grade_loader then grade_loader=assert(package.loadlib(directory..'skieo_surface_lifts.dll','skieo_surface_grade'))end
    local points={}
    local function flush()
        if #points==0 then return end
        local f=assert(io.open(directory..'surface-grade.job','wb'))
        f:write(string.pack('<c4I4I4I4I8I8','SKSG',2,#points,0,snow:GetAddress(),snow:GetClass():GetAddress()),table.concat(points));f:close()
        os.remove(directory..'surface-grade.status')
        grade_loader()
        f=assert(io.open(directory..'surface-grade.status','rb'));local status=f:read('*a');f:close()
        assert(status:sub(1,3)=='ok:',status)
        points={}
    end
    for _,p in ipairs(stamps)do
        -- The previous five 3 m circles cleared a 10 m strip. Bound the blade
        -- to the actual corridor, including its clearance around pylons.
        points[#points+1]=string.pack('<ddff',p.x,p.y,p.radius or 250,500)
        if #points==256 then flush()end
    end
    flush()
end
function Groom.request(state,item)
    if item.disposed or not item.groom_trail or(item.evacuation_waiting or 0)>0 then return false end
    local groom=current('GroomingSubsystem');if not valid(groom)or groom:HasActiveGroomingEvent(item.groom_trail)then return false end
    local controller=widget(state);controller.SkiEOGroomTrailId=item.groom_trail;controller:OnGroomNowClicked()
    local requested=groom:HasActiveGroomingEvent(item.groom_trail)
    if requested then item.groom_requests=item.groom_requests+1 end
    return requested
end
function Groom.update(state,env)
    if env.paused then return end
    local groom=current('GroomingSubsystem');if not valid(groom)then return end
    local time=current('TimeSubsystem');local night=valid(time)and time:IsNightShift()
    for _,item in ipairs(state.items)do if not item.disposed and item.groom_trail and(item.evacuation_waiting or 0)==0 then
        local interval=item.snow_reason=='excess'and .25 or 2
        if (night or item.snow_reason=='excess')and(not item.groom_next or env.hours>=item.groom_next)then
            item.groom_next=env.hours+interval
            Groom.request(state,item)
        end
    end end
    if night then
        for _,item in ipairs(state.items)do if not item.disposed and(item.evacuation_waiting or 0)==0 then
            for _,choice in ipairs(item.evacuation_routes or{})do if choice.index>0
                and(choice.evacuation_waiting or 0)==0 and(not choice.groom_next or env.hours>=choice.groom_next)then
                choice.groom_next=env.hours+2;Groom.request(state,choice)
            end end
        end end
    end
    state.groom_vehicles=state.groom_vehicles or{}
    local stamps={}
    local staff=current('StaffSubsystem')
    for _,member in ipairs(valid(staff)and staff:GetStaffByRole(2)or{})do
        local ok,value=pcall(function()return member:get()end);member=ok and value or member
        -- The staff query follows the native vehicle state even when its
        -- mesh is culled far from the camera. WorldPosition itself is zero
        -- while the groomer is driven by the grooming subsystem.
        local p={}
        if member.bExternallyDriven and staff:TryGetStaffWorldPosition(member.ID,p)then
            local id=member.ID
            local key=string.format('%x:%x:%x:%x',id.A,id.B,id.C,id.D)
            local old=state.groom_vehicles[key]
            local event=member.AssignedEventId
            local task=event and string.format('%x:%x:%x:%x',event.A,event.B,event.C,event.D)or''
            state.groom_vehicles[key]={x=p.X,y=p.Y,z=p.Z,hours=env.hours,seconds=env.seconds,task=task}
            if old then
                local distance=math.sqrt((p.X-old.x)^2+(p.Y-old.y)^2)
                -- A jump on spawn/load is not a physical blade passage.
                local elapsed=valid(time)and time:RealSecondsToGameHours(math.max(0,(env.seconds or 0)-(old.seconds or env.seconds or 0)))
                    or env.hours-(old.hours or env.hours)
                local maximum=math.max(3000,math.max(0,elapsed)*3600*1000)
                if old.task==task and elapsed>=0 and elapsed<1 and distance>=10 and distance<maximum then
                    for _,item in ipairs(state.items)do if not item.disposed and item.groom_trail and(item.evacuation_waiting or 0)==0
                        and groom:HasActiveGroomingEvent(item.groom_trail)then
                        for k=1,math.ceil(distance/100)do
                            local t=k/math.ceil(distance/100);local x,y=old.x+(p.X-old.x)*t,old.y+(p.Y-old.y)*t
                            local d=G.nearest(item.route,x,y);local line=G.sample(item.route,d)
                            local width,offset=Groom.dimensions(item.definition)
                            local lx,ly=line.x-line.nx*offset,line.y-line.ny*offset
                            local lateral=(x-lx)*line.nx+(y-ly)*line.ny
                            local radius=math.min(250,width*.5-math.abs(lateral))
                            if radius>=100 and(x-lx)^2+(y-ly)^2<(width*.5+300)^2 then
                                local e=require('map_entities').environment(state.api,x,y,true)
                                if e.snow_ready and e.snow_cm>80 then
                                    stamps[#stamps+1]={x=x,y=y,radius=radius};item.groom_stamps=item.groom_stamps+1
                                end
                            end
                        end
                    end end
                end
            end
        end
    end
    Groom.grade(state,stamps)
end
function Groom.dispose(state)
    local terrain=require('terrain')
    if terrain.trail_visual_exclusions==state.groom_hidden then terrain.trail_visual_exclusions=nil end
    if valid(state.groom_widget)then state.groom_widget:RemoveFromParent()end
    state.groom_widget=nil;state.groom_vehicles={}
end
return Groom
