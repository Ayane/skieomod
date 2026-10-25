-- Discover native boardings at 4 Hz, then read only known passengers at frame
-- rate. Positions are never extrapolated or cached across simulation ticks.
local G=require('surface_lift_geometry')
local Cycle=require('surface_lift_cycle')
local Riders={}
local function unwrap(o)local ok,v=pcall(function()return o:get()end);return ok and v or o end
local function guid(g)return string.format('%08x-%08x-%08x-%08x',g.A,g.B,g.C,g.D)end
function Riders.read(state,guests,now)
    if not state.rider_scan or now-state.rider_scan>=.25 then
        state.rider_scan=now;state.rider_indices={}
        local lifts={}
        for _,item in ipairs(state.items)do
            if not item.disposed and item.definition.kind~='fixed_chair'then lifts[item.id]=true end
        end
        local cold_count=guests.Guests:GetArrayNum()
        guests.GuestsHot:ForEach(function(index,ref)
            if index>cold_count then return end
            local h=unwrap(ref)
            if h.ActivityState==3 then
                local cold=guests.Guests[index];local id=guid(cold.QueueLiftId)
                if lifts[id]then state.rider_indices[index]={id=id,key=guid(cold.GuestId)}end
            end
        end)
    end
    local by_lift={}
    local count=math.min(guests.GuestsHot:GetArrayNum(),guests.Guests:GetArrayNum())
    for index,known in pairs(state.rider_indices)do
        local h=index>=1 and index<=count and guests.GuestsHot[index]
        local cold=h and guests.Guests[index]
        -- Native arrays can compact/reorder when a guest leaves the resort.
        if not h or h.ActivityState~=3 or guid(cold.GuestId)~=known.key or guid(cold.QueueLiftId)~=known.id then
            state.rider_indices[index]=nil;state.rider_scan=nil
        else
            local p=h.WorldPosition;local g=cold.GuestId
            by_lift[known.id]=by_lift[known.id] or {}
            by_lift[known.id][#by_lift[known.id]+1]={X=p.X,Y=p.Y,Z=p.Z,index=index-1,
                discipline=cold.Discipline,color=h.ColorIndex,guest={A=g.A,B=g.B,C=g.C,D=g.D},key=known.key}
        end
    end
    return by_lift
end
function Riders.bind(item,passengers)
    local a=item.lift;local spline=a.CableSpline;local count=a.ChairISM:GetInstanceCount()
    item.passengers={}
    if count==0 then return end
    local spacing=item.native_length/count
    local present={};item.rider_slots=item.rider_slots or{}
    for _,r in ipairs(passengers)do
        present[r.key]=true;r.distance=G.nearest(item.route,r.X,r.Y)
    end
    for key in pairs(item.rider_slots)do if not present[key]then item.rider_slots[key]=nil end end
    if item.cycle then
        Cycle.advance(item.cycle,item.rail,item.cable_step or 0)
        for _,pole in ipairs(item.cycle.poles)do if pole.state=='line'then
            if pole.guest and not present[pole.guest]then Cycle.release(item.cycle,pole)end
            local phase=(item.native_phase+pole.index*spacing)%item.native_length
            local crossed=(phase-item.return_entry)%item.native_length
            if (item.cable_step or 0)>0 and crossed<(item.cable_step or 0)then
                Cycle.arrive(item.cycle,pole.index,crossed)
            end
        end end
    end
    for _,r in ipairs(passengers)do
        local pole=item.cycle and Cycle.guest(item.cycle,r.key)
        local index=pole and pole.index or item.rider_slots[r.key]
        if not index or index>=count then
            local key=spline:FindInputKeyClosestToWorldLocation({X=r.X,Y=r.Y,Z=r.Z})
            local distance=spline:GetDistanceAlongSplineAtSplineInputKey(key)
            index=math.floor(((distance-item.native_phase)%item.native_length)/spacing+.5)%count
            item.rider_slots[r.key]=index
        end
        if item.cycle then
            -- A guest first observed well uphill is already on the line. This
            -- also covers delayed discovery after the first map frame.
            local recovered=r.distance>Cycle.boarding(item.definition)+500
            local clearance=math.huge
            if not pole and item.cycle.last_id then for _,p in ipairs(item.cycle.poles)do
                if p.id==item.cycle.last_id and p.state=='line'then
                    clearance=(item.native_phase+p.index*spacing-a.CableComp.SkiEOTowBoard)%item.native_length
                end
            end end
            local bound,why=Cycle.dispatch(item.cycle,item.rail,index,r.key,recovered,clearance)
            item.dispatch_wait=not bound and why or nil
            if bound then item.passengers[bound.index]=r end
        else
            item.passengers[index]=r
        end
    end
end
return Riders
