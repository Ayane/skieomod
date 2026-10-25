local Models=require('surface_lift_models')
-- Native queues, dispatch, passengers, staff, maintenance and save GUIDs remain
-- owned by LiftActor. A private socket mesh gives passengers standing places;
-- its transport spline follows the snow, separately from the visible cable.
local UE=require('UEHelpers')
local Terrain=require('terrain')
local Entities=require('map_entities')
local Mesh=require('portable_mesh')
local G=require('surface_lift_geometry')
local Native=require('surface_lift_native')
local Snow=require('surface_lift_snow')
local Cycle=require('surface_lift_cycle')
local Audio=require('surface_lift_audio')
local Pose=require('surface_lift_pose')
local Station=require('surface_lift_station')
local Contact=require('surface_lift_contact')
local Wheels=require('surface_lift_wheels')
local Chair=require('surface_lift_chair')
local Groom=require('surface_lift_grooming')
local Refresh=require('surface_lift_refresh')
local Riders=require('surface_lift_riders')
local Lifts={}
local adapted={}
local rendered={}
local hide_native
local function persist_cycles(state)
    for _,item in ipairs(state.items)do if item.cycle and not item.disposed then
        state.api:mod_state().detachable_cycles[item.id]=Cycle.encode(item.cycle)
    end end
end
function Lifts.is_adapted(lift) return lift and adapted[lift:GetAddress()]~=nil end
function Lifts.closed_reason(lift)
    local i=lift and adapted[lift:GetAddress()]
    return i and (i.snow_blocked and (i.snow_reason=='excess'and 'Excès de neige sur la ligne de montée — damage nécessaire' or 'Manque de neige sur la ligne de montée')
        or i.requested_speed==0 and 'Arrêt manuel') or nil
end
local function valid(o) return o and o:IsValid() end
local function unwrap(o) local ok,v=pcall(function() return o:get() end);return ok and v or o end
local function guid(g) return string.format('%08x-%08x-%08x-%08x',g.A,g.B,g.C,g.D) end
local function current(o)
    return valid(o) and not o:GetFullName():find('Default__',1,true)
        and not o:IsActorBeingDestroyed()
        and valid(o:GetWorld()) and o:GetWorld():GetAddress()==UE.GetWorld():GetAddress()
end
local function destroy(a) if valid(a) then pcall(function() a:K2_DestroyActor() end) end end
local FIELDS={'Capacity','OperatingSpeed','DispatchIntervalSeconds','bAllowDownloading','MinClearance','HardClearance','ChairMesh','MinOperatingSnowDepthCm'}
local function set_speed(item,speed)
    item.setting_speed=true
    local ok,err=pcall(function() item.lift:SetSpeedSetting(speed) end)
    item.setting_speed=false
    assert(ok,err)
end
local function snow_status(state,item,blocked,reason)
    if item.snow_blocked==blocked and item.snow_reason==reason then return end
    item.snow_blocked=blocked
    item.snow_reason=reason
    -- Native Off winds down while carrying existing riders. A bare towing
    -- line requires an immediate mechanical stop, including those riders.
    item.lift.OperatingSpeed=(blocked or item.requested_speed==0) and 0 or item.definition.speed_mps*100
    if blocked then set_speed(item,0)
    elseif item.requested_speed>0 then set_speed(item,item.requested_speed) end
    state.api:mod_state().speed_requests[item.id]=item.requested_speed
    state.api:log(item.definition.name..': '..(blocked and(reason=='excess'and 'arrêt pour excès de neige' or 'arrêt pour manque de neige')or 'enneigement de la ligne acceptable'))
end
local function hooks()
    local Compat=require('compatibility')
    local function hook(...)
        local ok,detail=Compat.hook(...)
        assert(ok,'Surface lift operating-state hook unavailable: '..tostring(detail))
    end
    hook('surface_lifts.cable_render','/Script/SkiResortSimulator.LiftActor:RebuildCableMeshes','post',function(context)
        local item=rendered[context:get():GetAddress()]
        if item and not item.disposed then hide_native(item)end
    end)
    for _,method in ipairs({'SaveGameToSlot','AsyncSaveGameToSlot'})do
        Compat.hook('surface_lifts.save.'..method,'/Script/Engine.GameplayStatics:'..method,'pre',function(_,object)
            local save=object:get()
            if not valid(save)or not save:GetClass():GetFullName():find('SkiResortSaveGame',1,true)then return end
            for _,item in pairs(adapted)do if not item.disposed then
                local session=item.state.api._session or item.state.api
                persist_cycles(item.state)
                if save.MapPath:ToString()=='/Engine/Maps/Entry'then require('saves').store_state(save,session._map,session._persistent)end
                break
            end end
        end)
    end
    hook('surface_lifts.save.confirm','/Script/SkiResortSimulator.SaveLoadMenuWidget:OnConfirmClicked','pre',function()
        for _,item in pairs(adapted)do if not item.disposed then
            persist_cycles(item.state);item.state.api:_sync_state();break
        end end
    end)
    for _,name in ipairs({'IsLiftRunning','IsLiftAvailableForSkiing','IsLiftAvailableForTransportation','IsLiftAvailableForHomeboundTransport','IsOpenForBusiness'}) do
        hook('surface_lifts.snow.'..name,'/Script/SkiResortSimulator.LiftActor:'..name,'post',function(context)
            if Lifts.closed_reason(context:get()) then return false end
        end)
    end
    for _,name in ipairs({'GetStatusText','GetStatusReasonText','GetStatusLabelText','GetStatusHintText'}) do
        hook('surface_lifts.snow.'..name,'/Script/SkiResortSimulator.LiftActor:'..name,'post',function(context)
            local why=Lifts.closed_reason(context:get());if why then return FText(why) end
        end)
    end
    hook('surface_lifts.speed_intent','/Script/SkiResortSimulator.LiftActor:SetSpeedSetting','post',function(context,setting)
        local item=adapted[context:get():GetAddress()]
        if item and not item.setting_speed then
            item.requested_speed=setting:get()
            item.state.api:mod_state().speed_requests[item.id]=item.requested_speed
            item.lift.OperatingSpeed=(item.snow_blocked or item.requested_speed==0) and 0 or item.definition.speed_mps*100
            if item.snow_blocked and item.requested_speed~=0 then set_speed(item,0) end
        end
    end)
end
local function socket_mesh(lift)
    local name=UE.FindOrAddFName
    local mesh=StaticConstructObject(Mesh.load('/Script/Engine.StaticMesh'),lift,name('SkiEO_SurfaceLiftSockets'),0,0,false,false,nil)
    assert(valid(mesh),'Could not create surface lift sockets')
    local sockets={}
    for _,key in ipairs({'AttachPoint','Standing_0'}) do
        local s=StaticConstructObject(Mesh.load('/Script/Engine.StaticMeshSocket'),mesh,name('SkiEO_'..key),0,0,false,false,nil)
        assert(valid(s),'Could not create standing socket')
        s.SocketName=name(key);s.RelativeLocation={X=0,Y=0,Z=0}
        s.RelativeRotation={Pitch=0,Yaw=0,Roll=0};s.RelativeScale={X=1,Y=1,Z=1}
        sockets[#sockets+1]=s
    end
    mesh.Sockets=sockets
    -- LiftActor.ChairMesh is the strong Unreal reference. Do not edit a cooked
    -- asset or its sockets: ordinary chairlifts in this world keep their CDOs.
    return mesh
end
local function hide(item,c)
    if not valid(c) then return end
    if not item.hidden[c:GetAddress()] then
        item.hidden[c:GetAddress()]={component=c,visible=c:IsVisible()}
    end
    c:SetVisibility(false,false)
end
hide_native=function(item)
    local a=item.lift
    local chair=item.definition.kind=='fixed_chair'
    local preserved={}
    local function preserve(c) if valid(c) then preserved[c:GetAddress()]=true end end
    preserve(a.QueuePostISM);preserve(a.QueueRopeISM)
    if chair then
        preserve(a.ChairISM)
    end
    for _,entry in ipairs(a:K2_GetComponentsByClass(Mesh.load('/Script/Engine.StaticMeshComponent'))) do
        local c=unwrap(entry)
        if not preserved[c:GetAddress()] then hide(item,c) end
    end
end
local function snapshot_spline(s)
    local out={points={},closed=s:IsClosedLoop()}
    for i=0,s:GetNumberOfSplinePoints()-1 do
        local p=s:GetLocationAtSplinePoint(i,1)
        local a,b=s:GetArriveTangentAtSplinePoint(i,1),s:GetLeaveTangentAtSplinePoint(i,1)
        out.points[#out.points+1]={X=p.X,Y=p.Y,Z=p.Z,type=s:GetSplinePointType(i),
            arrive={X=a.X,Y=a.Y,Z=a.Z},leave={X=b.X,Y=b.Y,Z=b.Z}}
    end
    return out
end
local function set_spline(s,points,closed)
    s:ClearSplinePoints(false)
    for _,p in ipairs(points) do s:AddSplinePoint({X=p.X,Y=p.Y,Z=p.Z},1,false) end
    for i,p in ipairs(points) do
        s:SetSplinePointType(i-1,p.type or 0,false) -- linear for the towing surface
        if p.arrive then s:SetTangentsAtSplinePoint(i-1,p.arrive,p.leave,1,false) end
    end
    s:SetClosedLoop(closed,false);s:UpdateSpline()
end
local function surface(api,x,y)
    local e=Entities.environment(api,x,y,true)
    return e.inside and e.z or nil,e.ground
end
local function transport(state,item,rebuild)
    local a=item.lift
    local job=item.snow_pending or Refresh.create(item)
    item.snow_pending=job
    if not Refresh.step(job,function(x,y)return surface(state.api,x,y)end,rebuild and #job.queries or 8)then return end
    for _,group in ipairs(job.groups)do
        local s=a[group.name];local old=item.transport_groups and item.transport_groups[group.name]
        if not old or #old~=#group.points then set_spline(s,group.points,group.closed)
        else
            local changed=false
            for i,p in ipairs(group.points)do if math.abs(p.Z-old[i].Z)>.25 then
                s:SetLocationAtSplinePoint(i-1,p,1,false);changed=true
            else p.Z=old[i].Z end end
            if changed then s:UpdateSpline()end
        end
    end
    item.transport_groups={}
    for _,group in ipairs(job.groups)do item.transport_groups[group.name]=group.points end
    item.snow_profile=job.profile;item.snow_pending=nil
    item.snow_updated=state.clock_seconds;item.snow_refreshes=(item.snow_refreshes or 0)+1
    Native.set(a,Cycle.boarding(item.definition),a.CableSpline:GetDistanceAlongSplineAtSplinePoint(#item.route.points-1))
    local key=a.CableSpline:FindInputKeyClosestToWorldLocation(job.marker)
    item.return_entry=a.CableSpline:GetDistanceAlongSplineAtSplineInputKey(key)
    if rebuild then a:RebuildChairMeshes(item.phase or 0) end
end
local function visual(state,item)
    local a=Mesh.actor();item.visual=a
    local route,supports=item.route,item.supports
    local function part(model,p,scale,bank)
        bank=bank or item.bank
        if scale then scale.Y=scale.Y*(route.mirror or 1)end
        return Mesh.component(a,bank.models[model],bank.material,p,math.deg(p.yaw),scale)
    end
    local bottom,top=supports[1],supports[#supports]
    if item.definition.kind=='fixed_chair' then
        -- Keep the native two-seat carriers, pylons and suspended cable. These
        -- original models replace the station buildings, including roof snow.
        local function terminal(model,loop,p,drive)
            local dx,dy=math.cos(p.yaw),math.sin(p.yaw)
            local xmin,xmax,ymin,ymax,z=math.huge,-math.huge,math.huge,-math.huge,0
            for i=0,47 do
                local v=loop:GetLocationAtDistanceAlongSpline(loop:GetSplineLength()*i/48,1)
                local x,y=(v.X-p.x)*dx+(v.Y-p.y)*dy,-(v.X-p.x)*dy+(v.Y-p.y)*dx
                xmin=math.min(xmin,x);xmax=math.max(xmax,x);ymin=math.min(ymin,y);ymax=math.max(ymax,y);z=z+v.Z
            end
            local x,y=(xmin+xmax)*.5,(ymin+ymax)*.5
            local anchor={x=p.x+dx*x-dy*y,y=p.y+dy*x+dx*y,z=p.z,yaw=p.yaw}
            part(model,anchor,{X=math.max(.5,(xmax-xmin)/600),Y=math.max(.5,(ymax-ymin)/600),Z=math.max(.5,(z/48-p.z)/728)})
            local radius=math.min(xmax-xmin,ymax-ymin)*.5
            local base=Mesh.transform({x=anchor.x,y=anchor.y,z=z/48},math.deg(p.yaw),{X=radius/200,Y=radius/200,Z=1})
            Wheels.add(item,state,base,radius,route.mirror,'inclined_wheel')
            if drive then
                local motor=Mesh.component(a,item.bank.models.motor,item.bank.material)
                local at={X=base.Translation.X,Y=base.Translation.Y,Z=base.Translation.Z+35}
                motor:K2_SetWorldTransform({Translation=at,Rotation=base.Rotation,Scale3D={X=1,Y=1,Z=1}},false,{},true)
            end
        end
        terminal('chair_drive',item.lift.StartLoopSpline,bottom,true)
        terminal('chair_return',item.lift.EndLoopSpline,top)
        Chair.towers(item,state)
        item.cable_component=Mesh.component(a,Chair.cable_mesh(item),item.bank.material,{0,0,0})
        return
    end
    local station=bottom;local station_scale=bottom.height/500
    if item.definition.kind=='detachable_platter'then
        local radius=math.sqrt(160^2+((bottom.return_height-bottom.height)*.5)^2)
        local covered=item.definition.drive=='covered'
        local clearance=math.max(0,radius+80-(covered and 120 or 265))
        station={x=bottom.x+math.cos(bottom.yaw)*clearance,y=bottom.y+math.sin(bottom.yaw)*clearance,z=bottom.z,yaw=bottom.yaw}
        local front=(covered and 1220 or 650)+clearance
        for d=0,front,100 do
            station_scale=math.max(station_scale,(G.cable(route,supports,d,-160).z-bottom.z+40)/(covered and 585 or 535))
        end
    end
    part(item.definition.drive=='covered' and 'covered' or item.definition.drive=='modern' and 'modern' or item.definition.kind=='fixed_platter' and 'fixed' or 'drive',station,{X=1,Y=1,Z=station_scale})
    part(item.definition.return_station=='release' and 'release' or item.definition.return_station=='lattice' and 'lattice' or 'return_station',top,{X=1,Y=1,Z=top.height/500})
    for i=2,#supports-1 do
        local p=supports[i]
        local bank=Models.support(item,i-1)
        part(p.angle and 'angle_tower' or 'tower',p,{X=1,Y=1,Z=p.height/600},bank)
        if p.return_used then
            part(item.definition.kind=='fixed_platter' and 'fixed_return_support' or p.angle and 'return_angle' or 'return_support',p,{X=1,Y=1,Z=p.height/600},bank)
        end
    end
    for terminal,p in ipairs({bottom,top})do
        local base=G.wheel_transform(p)
        Wheels.add(item,state,base,200*base.Scale3D.X,route.mirror,'inclined_wheel')
        if terminal==1 then
            local motor=Mesh.component(a,item.bank.models.motor,item.bank.material)
            motor:K2_SetWorldTransform({Translation=base.Translation,Rotation=base.Rotation,Scale3D={X=1,Y=1,Z=1}},false,{},true)
        end
    end
    for _,group in ipairs(supports.guides or{})do for _,g in pairs(group)do
        Wheels.add(item,state,g.transform,g.radius,(group==supports.guides[1]and 1 or -1)*(g==group[-160]and 1 or -1))
    end end
    supports.wheels=Wheels.supports(route,supports,G,item.definition.kind)
    for _,w in ipairs(supports.wheels)do Wheels.add(item,state,w.base,w.radius,w.sign,nil,Models.support(item,w.support-1))end
    Mesh.component(a,Station.mounts(route,supports,G),item.bank.material,{0,0,0})
    item.cable_component=Mesh.component(a,G.cable_mesh(route,supports,nil,item.definition),item.bank.material,{0,0,0})
end
local function restore(item,removed)
    if item.disposed then return end;item.disposed=true
    adapted[item.address]=nil
    rendered[item.address]=nil
    if item.audio then Audio.dispose(item.audio) end
    Groom.remove(item.state,item)
    destroy(item.visual)
    if removed or not current(item.lift) then return end
    if item.snow_blocked then set_speed(item,item.requested_speed) end
    for key,value in pairs(item.original) do pcall(function() item.lift[key]=value end) end
    pcall(function()
        item.lift.ChairISM:SetStaticMesh(item.original.ChairMesh)
        for key,s in pairs(item.splines) do set_spline(item.lift[key],s.points,s.closed) end
        if item.markers then Native.restore(item.lift,item.markers) end
        item.lift:RebuildChairMeshes(item.phase or 0)
        item.lift:RebuildCableMeshes()
    end)
    for _,h in pairs(item.hidden) do if valid(h.component) then pcall(function() h.component:SetVisibility(h.visible,false) end) end end
end
local function attach(state,a,d)
    local item={state=state,lift=a,address=a:GetAddress(),definition=d,original={},splines={},hidden={},id=guid(a:GetLiftId())}
    local appearance=state.appearances[d]
    item.bank=appearance.bank;item.pylon_banks=appearance.pylons
    state.items[#state.items+1]=item
    rendered[item.address]=item
    for _,key in ipairs(FIELDS) do item.original[key]=a[key] end
    for _,key in ipairs({'CableSpline','StartLoopSpline','EndLoopSpline'}) do item.splines[key]=snapshot_spline(a[key]) end
    item.markers,item.phase=Native.prepare(a)
    item.route=G.route(d,Terrain.surface_height_at)
    item.supports=G.supports(item.route,d.pylons,d.kind,d)
    if d.kind=='fixed_chair' then
        Chair.prepare(item,set_spline,Native)
        hide_native(item);visual(state,item);state.bindings[d.name]=item.id;return item
    end
    a.Capacity=1;a.OperatingSpeed=d.speed_mps*100;a.DispatchIntervalSeconds=3600/d.capacity_per_hour
    a.bAllowDownloading=false;a.MinClearance=0;a.HardClearance=0
    a.MinOperatingSnowDepthCm=3
    item.requested_speed=state.api:mod_state().speed_requests[item.id] or a:GetSpeedSetting()
    if item.requested_speed==0 then a.OperatingSpeed=0 end
    adapted[a:GetAddress()]=item
    a.ChairMesh=socket_mesh(a);a.ChairISM:SetStaticMesh(a.ChairMesh)
    transport(state,item,true)
    if d.kind=='detachable_platter'then
        item.rail=Cycle.rail(item,function(x,y)return surface(state.api,x,y)end)
        item.supports.stock_rail=item.rail
        local saved=state.api:mod_state().detachable_cycles[item.id]
        local minimum=d.speed_mps*100*3600/d.capacity_per_hour
        item.cycle=saved and Cycle.decode(saved,item.rail,minimum)
            or Cycle.create(a.ChairISM:GetInstanceCount(),item.rail,minimum)
        state.api:mod_state().detachable_cycles[item.id]=Cycle.encode(item.cycle)
    end
    hide_native(item);visual(state,item)
    item.audio=Audio.create(item)
    Groom.attach(state,item)
    state.bindings[d.name]=item.id
    return item
end
local pool=Models.perch
local function place_perch(instance,kind,t,length)
    local fixed=kind=='fixed_platter'
    if not instance.visible or instance.kind~=kind then
        instance.component:SetVisibility(fixed,false)
        for _,name in ipairs({'upper','shaft','lower'})do instance[name]:SetVisibility(not fixed,false)end
        instance.visible=true;instance.kind=kind
    end
    if fixed then instance.component:K2_SetWorldTransform(t,false,{},true)
    else
        local parts=G.perch_parts(t,length)
        for _,name in ipairs({'upper','shaft','lower'})do instance[name]:K2_SetWorldTransform(parts[name],false,{},true)end
    end
end
local function riders(state,now)
    local guests=state.guests
    if not valid(guests) then
        for _,g in ipairs(FindAllOf('GuestSimulationSubsystem') or {}) do
            if valid(g) and valid(g:GetWorld()) and g:GetWorld():GetAddress()==UE.GetWorld():GetAddress() then guests=g;state.guests=g;break end
        end
    end
    if not valid(guests) then return {} end
    return Riders.read(state,guests,now)
end
local function towing_surface(item,d,x,y)
    local ground=Terrain.surface_height_at(x,y)
    if not ground then return nil end
    local points=item.route.points;local lo,hi=1,#points
    while hi-lo>1 do local mid=(lo+hi)//2;if points[mid].distance>d then hi=mid else lo=mid end end
    local t=math.max(0,math.min(1,(d-points[lo].distance)/math.max(.001,points[hi].distance-points[lo].distance)))
    local profile=item.snow_profile
    local depth=profile[lo]+(profile[hi]-profile[lo])*t
    -- Feet retain the precise local terrain slope without reading snow tiles
    -- from disk for every sole/IK sample. The transport refresh owns the snow.
    return ground+depth,ground
end
local function update(state)
    if state.stopped then return false end
    local env=Entities.environment(state.api)
    if not env.ready then return true end
    -- Destroyed actors can retain a valid UObject wrapper while their spline
    -- components are already gone. The native registry owns lift lifetime.
    local live={}
    state.registry.Lifts:ForEach(function(_,entry)
        local a=unwrap(entry);if current(a)then live[a:GetAddress()]=true end
    end)
    local removed=false
    for _,item in ipairs(state.items)do
        if not item.disposed and not live[item.address]then restore(item,true);removed=true end
    end
    if removed then Native.visuals(state.items);state.pose_key=nil end
    local camera=env.camera
    local passengers=riders(state,env.seconds)
    state.clock_seconds=env.seconds
    Contact.update(state,camera,passengers,env.seconds,env.paused)
    -- Spread readback over frames. Every uphill sample participates, even far
    -- from the camera. A single bare sample stops boarding immediately; reopening
    -- requires a complete known, snow-covered pass and preserves manual Off.
    if #state.items>0 and (not state.snow_scan_at or env.seconds>=state.snow_scan_at)then
        state.snow_scan_at=env.seconds+.05
        state.snow_cursor=(state.snow_cursor or 0)%#state.items+1
        local item=state.items[state.snow_cursor]
        if not item.disposed and current(item.lift) and item.definition.kind~='fixed_chair' then
            local status,minimum,_,reason,maximum=Snow.scan(item,function(x,y) return Entities.environment(state.api,x,y,true) end,16)
            item.minimum_snow=minimum
            item.maximum_snow=maximum
            if status=='blocked' then snow_status(state,item,true,reason)
            elseif status=='clear' then snow_status(state,item,false) end
        end
    end
    local periodic=not state.refresh or env.seconds-state.refresh>2
    if periodic then
        state.refresh=env.seconds
        local removed=false
        for _,item in ipairs(state.items) do
            if not item.disposed and not current(item.lift) then restore(item,true);removed=true
            elseif not item.disposed then
                hide_native(item)
            end
        end
        if removed then Native.visuals(state.items);state.pose_key=nil end
    end
    -- The CPU snow bridge performs file I/O. Re-reading every point every two
    -- seconds stalls simulation on Wine. Refresh in eight-sample slices, then
    -- update only changed spline heights. Prioritize the oldest due profile.
    local refresh_item,overdue
    for _,item in ipairs(state.items) do
        if not item.disposed and current(item.lift) and item.definition.kind~='fixed_chair'
            and env.seconds-(item.snow_updated or env.seconds)>(item.snow_refreshes<4 and 3 or 30) then
            local age=env.seconds-item.snow_updated
            if item.snow_pending then refresh_item=item;break end
            if not overdue or age>overdue then refresh_item=item;overdue=age end
        end
    end
    if refresh_item then transport(state,refresh_item,false)end
    -- All wheel angles use the native travelled phase, including slow speed,
    -- accelerated time, manual stops and pause. Snow spline rebuilds are filtered.
    for _,item in ipairs(state.items)do if not item.disposed and current(item.lift)then
        local ism=item.lift.ChairISM;local t={}
        if ism:GetInstanceCount()>0 and ism:GetInstanceTransform(0,t,true)then
            local spline=item.lift.CableSpline
            local key=spline:FindInputKeyClosestToWorldLocation(t.Translation)
            item.native_phase=spline:GetDistanceAlongSplineAtSplineInputKey(key)
            item.native_length=spline:GetSplineLength()
            Wheels.update(item,item.native_phase,item.native_length,env.seconds,item.lift:GetEffectiveOperatingSpeed()*math.max(1,env.rate or 1),env.paused,camera)
        end
    end end
    -- Bind real boarding events to retained hangers. The game's uniformly
    -- spaced virtual seats enforce the same configured minimum headway.
    for _,item in ipairs(state.items)do if item.definition.kind~='fixed_chair' and not item.disposed and item.native_phase then
        Riders.bind(item,passengers[item.id]or{})
    end end
    local visible={}
    local stocks={}
    if camera then
        for _,item in ipairs(state.items) do
            if item.definition.kind~='fixed_chair' and not item.disposed and current(item.lift) then
                local d,error=G.nearest(item.route,camera.x,camera.y)
                if error<18000^2 then
                    local ism=item.lift.ChairISM;local count=ism:GetInstanceCount()
                    if count>0 and item.native_phase then
                        local phase=item.native_phase
                        local spacing=item.native_length/count
                        item.stock_phase=(phase%spacing)/spacing
                        Audio.update(item.audio,item,camera,phase,env.seconds,env.paused)
                    end
                    local bottom=item.supports[1]
                    if item.cycle and (bottom.x-camera.x)^2+(bottom.y-camera.y)^2<20000^2 then
                        local pending={}
                        for _,pole in ipairs(item.cycle.poles)do if pole.state~='line'then pending[#pending+1]=pole end end
                        table.sort(pending,function(a,b)return a.s>b.s end)
                        for j,pole in ipairs(pending)do
                            if j<=24 or pole.state=='rail' or pole.order>item.cycle.order-8 then
                                local p=Cycle.at(item.rail,pole.s)
                                local e=(p.x-camera.x)^2+(p.y-camera.y)^2+(p.z-camera.z)^2
                                if e<18000^2 then stocks[#stocks+1]={p=p,distance=e,item=item}end
                            end
                        end
                    end
                    for i=0,count-1 do
                        local t={}
                        local pole=item.cycle and Cycle.carrier(item.cycle,i)
                        if (not item.cycle or pole)and ism:GetInstanceTransform(i,t,true) then
                            local passenger=item.passengers and item.passengers[i]
                            local p=passenger or t.Translation;local e=(p.X-camera.x)^2+(p.Y-camera.y)^2+(p.Z-camera.z)^2
                            if e<18000^2 then visible[#visible+1]={item=item,t=t,distance=e,index=i,pole=pole} end
                        end
                    end
                else Audio.silence(item.audio) end
            end
        end
    end
    table.sort(visible,function(a,b) return a.distance<b.distance end)
    -- LOD bounds both UObject count and CPU cost; the native simulation still
    -- dispatches every carrier even when its small platter cannot be seen.
    local n=math.min(64,#visible)
    local posed,pose_count={},0
    local empty_fixed={}
    for _,item in ipairs(state.items)do if item.definition.kind=='fixed_platter'then item.loads={}end end
    for i=1,n do
        local v=visible[i];local p=v.t.Translation;local item=v.item
        local passenger=item.passengers and item.passengers[v.index]
        local d=passenger and passenger.distance or G.nearest(item.route,p.X,p.Y);local center=G.sample(item.route,d)
        local lane=passenger and -160 or ((p.X-center.x)*center.nx+(p.Y-center.y)*center.ny<0 and -160 or 160)
        local cable=G.cable(item.route,item.supports,d,lane)
        -- In stations follow the native loop horizontally; along the line use
        -- the same lanes as the visible cable and terrain-following transport.
        if d<200 or d>item.route.length-200 then cable.x=p.X;cable.y=p.Y end
        local instance=pool(state,i,item.bank)
        local transform,length
        local fixed=item.definition.kind=='fixed_platter'
        item.perch_springs=item.perch_springs or {}
        local spring=item.perch_springs[v.index]
        if passenger and d>200 and d<item.route.length-600 then
            local body,seat
            if pose_count<16 and v.distance<6000^2 and (passenger.discipline==0 or passenger.discipline==1)then
                body,seat=Pose.place(state,pose_count+1,passenger,center.yaw,function(x,y)
                    local z,grade=Contact.sample(state,x,y)
                    if z then return z,grade end
                    local along=d+(x-passenger.X)*math.cos(center.yaw)+(y-passenger.Y)*math.sin(center.yaw)
                    return towing_surface(item,along,x,y)
                end,item.bank)
            end
            seat=seat or {X=passenger.X-math.cos(center.yaw)*26,Y=passenger.Y-math.sin(center.yaw)*26,Z=passenger.Z+88}
            if fixed then
                cable=assert(G.fixed_clamp(item.route,item.supports,d,lane,seat),'Fixed pole is outside its cable reach')
                if cable.sag then item.loads[#item.loads+1]=cable end
            else
                cable=G.detachable_clamp(item.route,item.supports,d,lane,seat)
                if v.pole then
                    cable=Cycle.anchor(v.pole,cable,item.cycle.travel,seat,center.yaw)
                end
            end
            local yaw=math.atan(cable.y-seat.Y,cable.x-seat.X)
            transform,length=G.towing_parts(cable,seat,yaw,60)
            if fixed then
                -- A TKF tube is rigid. Its clamp position and inclination
                -- accommodate the piste; there is no telescopic scaling.
                assert(math.abs(length-300)<.1,'Fixed pole cannot reach the grounded skier')
                length=300
            end
            if body then
                Pose.grip(body,transform,length,18)
                pose_count=pose_count+1;posed[#posed+1]=passenger
            end
        else
            local q=v.t.Rotation
            local yaw=math.deg(math.atan(2*(q.W*q.Z+q.X*q.Y),1-2*(q.Y*q.Y+q.Z*q.Z)))
            local station=Cycle.position(item,p,d,lane,math.rad(yaw))
            length=fixed and 300 or G.release_length(spring and spring.length,spring and env.seconds-spring.time or 0)
            local anchor=station or cable
            transform=G.empty_perch(anchor,station and station.yaw or math.rad(yaw),length)
            if fixed and not station then empty_fixed[#empty_fixed+1]={instance=instance,item=item,d=d,lane=lane,yaw=math.rad(yaw)}end
        end
        item.perch_springs[v.index]={length=length,time=env.seconds}
        place_perch(instance,item.definition.kind,transform,length)
    end
    for _,v in ipairs(empty_fixed)do
        local anchor=G.flex_cable(v.item.route,v.item.supports,v.d,v.lane,v.item.loads)
        place_perch(v.instance,'fixed_platter',G.empty_perch(anchor,v.yaw),300)
    end
    for _,item in ipairs(state.items)do if not item.disposed and item.loads then
        local key={};for _,p in ipairs(item.loads)do key[#key+1]=math.floor(p.distance)..':'..math.floor(p.sag)end
        key=table.concat(key,';')
        if key~=item.cable_key and (not item.cable_updated or env.seconds-item.cable_updated>.1)then
            local m=G.cable_mesh(item.route,item.supports,item.loads)
            item.cable_component:CreateMeshSection(0,m.vertices,m.triangles,m.normals,m.uv,{},{},false)
            item.cable_key=key;item.cable_updated=env.seconds
        end
    end end
    table.sort(stocks,function(a,b)return a.distance<b.distance end)
    for i=1,math.min(64,#stocks)do local p=stocks[i].p
        n=n+1;local instance=pool(state,n,stocks[i].item.bank)
        place_perch(instance,'detachable_platter',Mesh.transform(p,math.deg(p.yaw)),295)
    end
    for i=n+1,#state.pool do local p=state.pool[i];if p.visible then
        for _,name in ipairs({'component','upper','shaft','lower'})do p[name]:SetVisibility(false,false)end
        p.visible=false
    end end
    Pose.hide_unused(state,pose_count)
    table.sort(posed,function(a,b)return a.key<b.key end)
    local ids,keys={},{}
    for _,r in ipairs(posed)do ids[#ids+1]=r.guest;keys[#keys+1]=r.key end
    local key=table.concat(keys,';')
    if key~=state.pose_key then Native.visuals(state.items,ids);state.pose_key=key end
    return true
end
function Lifts.configure(api,definitions,assets)
    local session=api._session or api
    assert(not session._surface_lifts,'Surface lifts already configured for this map session')
    assert(type(definitions)=='table' and #definitions<=16,'At most sixteen surface lifts are supported')
    assert(type(assets)=='table','Surface lift model assets are required')
    local names={}
    for _,d in ipairs(definitions) do G.validate(d);assert(not names[d.name],'Duplicate lift name');names[d.name]=true end
    local state={api=api,clock_seconds=Entities.environment(api).seconds,items={},models={},pool={},bindings=api:mod_state({bindings={}}).bindings or {}}
    for _,registry in ipairs(FindAllOf('PlaceableRegistrySubsystem') or {})do
        if valid(registry) and valid(registry:GetWorld()) and registry:GetWorld():GetAddress()==UE.GetWorld():GetAddress()then
            state.registry=registry;break
        end
    end
    assert(state.registry,'Native lift registry unavailable')
    api:mod_state().speed_requests=api:mod_state().speed_requests or {}
    api:mod_state().detachable_cycles=api:mod_state().detachable_cycles or {}
    hooks()
    local function cleanup()
        if state.stopped then return end;state.stopped=true
        for _,item in ipairs(state.items) do restore(item) end
        for _,p in ipairs(state.pool) do destroy(p.actor) end
        Pose.dispose(state)
        Contact.dispose(state)
        Groom.dispose(state)
        Native.visuals({})
        if session._surface_lifts==state then session._surface_lifts=nil end
    end
    local ok,message=xpcall(function()
        state.model_library=Models.new(api,assets)
        state.bank=state.model_library.base
        state.models=state.bank.models;state.material=state.bank.material
        state.appearances={}
        for _,d in ipairs(definitions)do state.appearances[d]=state.model_library:definition(d)end
        local world=UE.GetWorld();local found={}
        local actors={};UE.GetGameplayStatics():GetAllActorsOfClass(world,Mesh.load('/Script/SkiResortSimulator.LiftActor'),actors)
        for _,a in ipairs(actors) do
            a=unwrap(a)
            if current(a) and not a.bIsPreview then
                local id=guid(a:GetLiftId())
                for _,d in ipairs(definitions) do
                    local match=state.bindings[d.name] and state.bindings[d.name]==id
                    if not state.bindings[d.name] and a:GetInstanceName():ToString()==d.name then
                        local p=a:GetBottomTerminalLocation();local b=d.route[1]
                        match=(p.X-b[1])^2+(p.Y-b[2])^2<5000^2
                    end
                    if match then
                        assert(not found[d.name],'Ambiguous surface lift binding');found[d.name]=true
                        -- Complete source-terrain placement before taking over
                        -- its splines. Deferred native grounding would otherwise
                        -- rebuild a chairlift over the configured towing route.
                        Terrain.align_lift(a)
                        attach(state,a,d)
                    end
                end
            end
        end
        Native.visuals(state.items)
        api:mod_state().bindings=state.bindings
    end,debug.traceback)
    if not ok then cleanup();error(message,2) end
    session._surface_lifts=state
    session._cleanups=session._cleanups or {};session._cleanups[#session._cleanups+1]=cleanup
    session:on_frame(function() return update(state) end)
    api:every(500,function()
        if state.stopped then return false end
        Groom.update(state,Entities.environment(api));return true
    end)
    api:every(1000,function()
        if state.stopped then return false end
        -- Native C++ rebuilds can bypass ProcessEvent. Their snow-covered
        -- segments must not reappear over the continuous bare rope.
        for _,item in ipairs(state.items)do if not item.disposed and current(item.lift)then
            item.lift.CableComp.CableMeshSegments:ForEach(function(_,c)hide(item,unwrap(c))end)
            for address,h in pairs(item.hidden)do if not valid(h.component)then item.hidden[address]=nil end end
        end end
        persist_cycles(state);return true
    end)
    api:log('Surface lifts: '..#state.items..' native installations adapted')
    local handle={}
    function handle:dispose() cleanup() end
    function handle:snapshot()
        local out={}
        for _,item in ipairs(state.items) do
            if not item.disposed and current(item.lift) then
                local a=item.lift
                out[#out+1]={name=item.definition.name,kind=item.definition.kind,id=item.id,pylons=#item.supports-2,
                    length_cm=item.route.length,capacity_per_hour=item.definition.capacity_per_hour,
                    speed_mps=a:GetEffectiveOperatingSpeed()/100,running=a:IsLiftRunning(),
                    riders=a:GetActiveRiderCount(),riders_total=a:GetTotalGuestRidersAllTime()}
                out[#out].snow_blocked=item.snow_blocked or false
                out[#out].snow_reason=item.snow_reason
                out[#out].minimum_snow_cm=item.minimum_snow
                out[#out].maximum_snow_cm=item.maximum_snow
                out[#out].grooming_trail=item.groom_trail
                out[#out].grooming_requests=item.groom_requests
                out[#out].grooming_stamps=item.groom_stamps
                out[#out].requested_speed=item.requested_speed
                out[#out].ascent_side=item.definition.ascent_side or 'right'
                out[#out].moving_wheels=#(item.wheels or{})
                if item.cycle then
                    local queued,line=0,0
                    for _,p in ipairs(item.cycle.poles)do if p.state=='line'then line=line+1 else queued=queued+1 end end
                    out[#out].stock=queued;out[#out].line_hangers=line
                    out[#out].dispatches=item.cycle.dispatches;out[#out].returns=item.cycle.returns
                    out[#out].minimum_spacing_cm=item.cycle.minimum
                    out[#out].minimum_observed_spacing_cm=item.cycle.minimum_observed
                end
            end
        end
        return out
    end
    return handle
end
return Lifts
