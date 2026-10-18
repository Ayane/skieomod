-- Native people and operating lift corridors, queried only by behaviour.
-- Paw support skips these queries; nearby CPU samples share a bounded cache.
local UE=require('UEHelpers')
local Disturbance={}
local function valid(o)return o and o:IsValid()end
local function unwrap(o)local ok,v=pcall(function()return o:get()end);return ok and v or o end
local function current(o)
    if not valid(o) then return false end
    local world=UE.GetWorld();local w=o:GetWorld()
    return valid(w) and valid(world) and w:GetAddress()==world:GetAddress()
end
local function subsystem(name)
    for _,o in ipairs(FindAllOf(name) or {}) do
        if valid(o) and not o:GetFullName():find('Default__',1,true) and current(o) then return o end
    end
end
local function snapshot(state,seconds)
    if state.disturbance_sources and seconds-state.disturbance_at<1 then return state.disturbance_sources end
    local sources={};state.disturbance_sources=sources;state.disturbance_at=seconds;state.disturbance_cache={}
    for _,lift in ipairs(FindAllOf('LiftActor') or {}) do
        if #sources>=192 then break end
        if current(lift) and not lift.bIsPreview then
            local ok,running,a,b=pcall(function()
                return lift:IsLiftRunning() and lift:GetEffectiveOperatingSpeed()>0,
                    lift:GetBottomTerminalLocation(),lift:GetTopTerminalLocation()
            end)
            if ok and running then
                sources[#sources+1]={x=a.X,y=a.Y,z=a.Z,radius=3000,kind='lift'}
                sources[#sources+1]={x=b.X,y=b.Y,z=b.Z,radius=3000,kind='lift'}
                sources[#sources+1]={x=a.X,y=a.Y,z=a.Z,bx=b.X,by=b.Y,bz=b.Z,radius=1400,kind='lift'}
            end
        end
    end
    if not valid(state.disturbance_staff) then state.disturbance_staff=subsystem('StaffSubsystem') end
    if valid(state.disturbance_staff) then
        -- The roster is small; workers share the same fear radius as visitors.
        pcall(function()
            local count=0
            state.disturbance_staff:GetRoster():ForEach(function(_,row)
                count=count+1;if count>64 then return end
                local member=unwrap(row);local p={}
                if state.disturbance_staff:TryGetStaffWorldPosition(member.ID,p) then
                    sources[#sources+1]={x=p.X,y=p.Y,z=p.Z,radius=1800,kind='person'}
                end
            end)
        end)
    end
    return sources
end
function Disturbance.sample(state,x,y,z,seconds)
    local sources=snapshot(state,seconds)
    local key=math.floor(x/200)..':'..math.floor(y/200)
    local cached=state.disturbance_cache[key]
    if cached and seconds-cached.at<.5 then return cached.value or nil end
    local best,score
    local function consider(px,py,pz,radius,kind)
        if math.abs((pz or z)-z)>800 then return end
        local distance=math.sqrt((x-px)^2+(y-py)^2);local clearance=distance-radius*1.5
        if clearance<0 and (not score or clearance<score) then
            best={x=px,y=py,distance=distance,radius=radius,kind=kind};score=clearance
        end
    end
    for _,source in ipairs(sources) do
        local px,py,pz=source.x,source.y,source.z
        if source.bx then
            local dx,dy=source.bx-px,source.by-py
            local t=math.max(0,math.min(1,((x-px)*dx+(y-py)*dy)/math.max(1,dx*dx+dy*dy)))
            px,py,pz=px+dx*t,py+dy*t,pz+(source.bz-pz)*t
        end
        consider(px,py,pz,source.radius,source.kind)
    end
    if not valid(state.disturbance_selection) then state.disturbance_selection=subsystem('GuestSelectionSubsystem') end
    if not valid(state.disturbance_guests) then state.disturbance_guests=subsystem('GuestSimulationSubsystem') end
    if valid(state.disturbance_selection) and valid(state.disturbance_guests) then
        pcall(function()
            local index=state.disturbance_selection:GetGuestNearPosition({X=x,Y=y,Z=z},2700)
            local hot=state.disturbance_guests.GuestsHot
            if index>=0 and index<hot:GetArrayNum() then
                local guest=unwrap(hot[index+1]);local p=guest.WorldPosition
                consider(p.X,p.Y,p.Z,1800,'person')
            end
        end)
    end
    -- Queries during long excursions cannot grow the cache indefinitely.
    state.disturbance_samples=(state.disturbance_samples or 0)+1
    if state.disturbance_samples>=256 then state.disturbance_cache={};state.disturbance_samples=0 end
    state.disturbance_cache[key]={at=seconds,value=best or false}
    return best
end
return Disturbance
