-- Generic, map-scoped scenario operations. Rules and historical data live in maps.
local UEHelpers = require('UEHelpers')
local Terrain, Scene, Native = require('terrain'), require('scene_objects'), require('native_terrain')
local Host = {}
local function valid(o) return o and o:IsValid() end
local function current(o)
    if not valid(o) or o:GetFullName():find('Default__',1,true) then return false end
    local w=UEHelpers.GetWorld();local ow=o:GetWorld()
    return valid(w) and valid(ow) and w:GetAddress()==ow:GetAddress()
end
local function subsystem(name)
    for _,o in ipairs(FindAllOf(name) or {}) do if current(o) then return o end end
    error(name .. ' is unavailable', 2)
end
local function finite(v) return type(v)=='number' and v==v and math.abs(v)<2147483647 end
function Host.id(actor)
    local g=actor:GetPlaceableId()
    return string.format('%08x%08x%08x%08x',g.A,g.B,g.C,g.D)
end
function Host.describe(actor)
    local p=actor:K2_GetActorLocation()
    return {id=Host.id(actor),name=actor:GetInstanceName():ToString(),
        class=actor:GetClass():GetFullName():match('^[^ ]+ (.*)$'),
        lift=actor:IsA('/Script/SkiResortSimulator.LiftActor'),
        preview=actor.bIsPreview,position={p.X,p.Y,p.Z}}
end
function Host.snapshot(api)
    local t,e=subsystem('TimeSubsystem'),subsystem('EconomySubsystem')
    local f=tonumber(t:GetCurrentMonth())
    local options=api._game_options or {}
    local fiscal_year=tonumber(t:GetYearNumber())
    local year=(options.start_year or 2025)+fiscal_year-(options.initial_fiscal_year or 1)+(f>=6 and 1 or 0)
    local function counter(names)
        for _,name in ipairs(names) do
            local fn=StaticFindObject('/Script/SkiResortSimulator.EconomySubsystem:'..name)
            if valid(fn) then return e[name](e) end
        end
        error('native financial counter unavailable: '..names[1])
    end
    local revenue=counter({'GetYearTotalRevenue','GetSeasonTotalRevenue'})
    local expenses=counter({'GetYearTotalExpenses','GetSeasonTotalExpenses'})
    local month=(f+6)%12+1
    local days=({31,28,31,30,31,30,31,31,30,31,30,31})[month]
    if month==2 and year%4==0 and (year%100~=0 or year%400==0) then days=29 end
    local rides={}
    if options.track_lift_rides then
        for _,actor in ipairs(FindAllOf('LiftActor') or {}) do
            if current(actor) and not actor.bIsPreview then rides[Host.id(actor)]=actor:GetTotalGuestRidersAllTime() end
        end
    end
    return {year=year,month=month,day=math.min(days,math.floor(t:GetMonthProgress()*days)+1),
        fiscal_year=fiscal_year,fiscal_month=f,month_progress=t:GetMonthProgress(),
        months=fiscal_year*12+f+t:GetMonthProgress(),balance=e:GetBalance(),
        revenue=revenue,expenses=expenses,
        days_per_month=t:GetDaysPerMonth(),paused=t:IsTimePaused(),lift_rides=rides}
end
local function charge(amount,category,mandatory)
    assert(finite(amount) and amount>=0 and amount%1==0,'charge must be a nonnegative integer')
    local e=subsystem('EconomySubsystem')
    local balance=e:GetBalance()
    if not mandatory and balance<amount then return false end
    -- RecordExpense debits the balance on current game builds. Set the
    -- resulting balance explicitly so mandatory charges also allow a deficit.
    e:RecordExpense(amount,category or 1)
    e:SetBalance(balance-amount)
    return true
end
local function configure(api,options)
    assert(type(options)=='table','invalid game configuration')
    assert(not api._game_options,'game may be configured once per session')
    if options.trail_rating_system~=nil then require('trail_ratings').validate(options.trail_rating_system) end
    local t,e=subsystem('TimeSubsystem'),subsystem('EconomySubsystem')
    assert(not options.currency or options.currency:match('^[A-Z][A-Z][A-Z]$'),'currency must be an ISO code')
    assert(not options.start_year or finite(options.start_year) and options.start_year%1==0,'invalid start year')
    options.initial_fiscal_year=options.initial_fiscal_year or 1
    api._game_options=options
    if options.trail_rating_system~=nil then require('trail_ratings').set(api,options.trail_rating_system) end
    if not api._restoring then
        if options.starting_balance then assert(finite(options.starting_balance));e:SetBalance(options.starting_balance) end
        if options.ticket_price then e:SetTicketPrice(options.ticket_price) end
    end
    if options.loans and not api._sandbox then
        local settings=e:GetSettings()
        assert(valid(settings) and valid(settings.LoanTiersTable),'loan settings unavailable')
        local loans,sizing={},{}
        for name,loan in pairs(options.loans) do
            assert(type(name)=='string' and finite(loan.income_days) and loan.income_days>0 and loan.income_days<=365,'invalid loan income multiplier')
            assert(finite(loan.annual_rate) and loan.annual_rate>=0 and loan.annual_rate<=1,'invalid annual loan rate')
            assert(finite(loan.months) and loan.months>=1 and loan.months<=600 and loan.months%1==0,'invalid loan term')
        end
        settings.LoanTiersTable:ForEachRow(function(name,row)
            local loan=options.loans[name]
            if loan then
                loans[#loans+1]={row=row,interest=row.MonthlyInterestRate,months=row.PaybackMonths,label=row.DisplayName:ToString()}
                row.MonthlyInterestRate=loan.annual_rate/12;row.PaybackMonths=loan.months
                if loan.name then row.DisplayName=FText(loan.name) end
            end
        end)
        assert(#loans>0,'no matching loan tiers')
        -- Native credit is sized against recent daily income, not the row's
        -- Principal. Removing a sizing key disables that offer. Keep native
        -- underwriting and repayment; never advertise the ignored base amount.
        local tiers={'Small','Medium','Large'}
        settings.LoanDaysOfIncome:ForEach(function(key,value)
            local tier=key:get();local loan=options.loans[tiers[tier+1]]
            if loan then sizing[#sizing+1]={key=tier,value=value:get()};value:set(loan.income_days) end
        end)
        api:on('map.unloading',function()
            if not valid(settings) then return end
            for _,saved in ipairs(loans) do
                saved.row.MonthlyInterestRate=saved.interest
                saved.row.PaybackMonths=saved.months;saved.row.DisplayName=FText(saved.label)
            end
            for _,saved in ipairs(sizing) do settings.LoanDaysOfIncome:Find(saved.key):set(saved.value) end
        end)
    end
    -- DataTable rows drive purchase previews, affordability, construction and
    -- recurring costs. Restore shared rows before another map uses them.
    if options.costs and not api._sandbox then
        local table_asset=subsystem('SkiResortGameMode'):GetBuildingEconomyTable()
        assert(valid(table_asset),'building economy table unavailable')
        local restores={}
        table_asset:ForEachRow(function(name,row)
            local cost=options.costs[name] or options.costs['*']
            if cost then
                restores[#restores+1]={row=row,build=row.BuildCost,operating=row.DailyOperatingCost}
                if cost.build then row.BuildCost=cost.build end
                if cost.multiplier then row.BuildCost=math.floor(row.BuildCost*cost.multiplier) end
                if cost.operating then row.DailyOperatingCost=cost.operating end
                if cost.operating_multiplier then row.DailyOperatingCost=math.floor(row.DailyOperatingCost*cost.operating_multiplier) end
            end
        end)
        api:on('map.unloading',function()
            if valid(table_asset) then
                for _,saved in ipairs(restores) do saved.row.BuildCost=saved.build;saved.row.DailyOperatingCost=saved.operating end
            end
        end)
    end
    if options.class_costs and not api._sandbox then
        local function apply()
            for _,actor in ipairs(FindAllOf('PlaceableActor') or {}) do
                if current(actor) then
                    local class=actor:GetClass():GetFName():ToString()
                    local cost=options.class_costs[class]
                    if cost then actor.BaseCost=cost end
                end
            end
        end
        apply();api:every(100,apply)
    end
end
local function installation(id,properties)
    assert(type(id)=='string' and type(properties)=='table','invalid installation update')
    for _,actor in ipairs(FindAllOf('PlaceableActor') or {}) do
        if current(actor) and not actor.bIsPreview and Host.id(actor)==id then
            if properties.operating_cost then
                assert(finite(properties.operating_cost) and properties.operating_cost>=0)
                if actor:IsA('/Script/SkiResortSimulator.LiftActor') then actor.CatalogDailyOperatingCost=math.floor(properties.operating_cost)
                else actor.DailyOperatingCost=math.floor(properties.operating_cost) end
            end
            if properties.disabled~=nil then
                if actor:IsA('/Script/SkiResortSimulator.LiftActor') then actor:SetManualRepairActive(properties.disabled)
                else actor:SetOpen(not properties.disabled) end
            end
            if properties.no_refund then
                local locks=actor.PlaceableComponent.DesignLocks
                locks.bNoRefund=true;locks.bNoMove=true;locks.bNoDemolish=true
            end
            return true
        end
    end
    return false
end
local function hub_names(api,anchors)
    assert(type(anchors)=='table' and #anchors>0 and #anchors<=64,'invalid hub name anchors')
    for _,anchor in ipairs(anchors) do
        assert(type(anchor.name)=='string' and #anchor.name>0 and utf8.len(anchor.name) and utf8.len(anchor.name)<=32,'invalid geographic name')
        assert(finite(anchor.x) and finite(anchor.y),'invalid hub name position')
    end
    api._named_hubs=api._named_hubs or {}
    local names={}
    for _,actor in ipairs(FindAllOf('HubActor') or {}) do
        if current(actor) and valid(actor.NameLabel) then
            local id=actor.HubId
            local key=string.format('%08x%08x%08x%08x',id.A&0xffffffff,id.B&0xffffffff,id.C&0xffffffff,id.D&0xffffffff)
            if not api._named_hubs[key] then
                local p=actor:K2_GetActorLocation();local nearest,distance=nil,math.huge
                for _,anchor in ipairs(anchors) do local d=(p.X-anchor.x)^2+(p.Y-anchor.y)^2
                    if d<distance then nearest,distance=anchor,d end
                end
                names[#names+1]={id={A=id.A,B=id.B,C=id.C,D=id.D},name=nearest.name,actor=actor,key=key}
            end
        end
    end
    local ok,message=Native.name_hubs(names)
    if not ok then error('could not name hubs: '..tostring(message)) end
    for _,name in ipairs(names) do
        name.actor.NameLabel:K2_SetText(FText(name.name));api._named_hubs[name.key]=name.name
    end
    return #names
end
local function place_resort(api,definitions,trails)
    if api._restoring then return end
    local actors=Scene.place(api,definitions)
    local lifts,buildings={},{}
    for _,actor in ipairs(actors) do
        if actor:IsA('/Script/SkiResortSimulator.LiftActor') then
            lifts[#lifts+1]=actor;actor:SetOperatingHours(8,17)
        else buildings[#buildings+1]=actor;actor:SetOpen(true);actor:SetOperatingHours(8,18) end
    end
    local ok,message=Native.register_placeable_hubs(lifts,buildings)
    assert(ok,'could not register resort hubs: '..tostring(message))
    local map=subsystem('TrailMapSubsystem')
    local function point(p)
        return {X=p[1],Y=p[2],Z=assert(Terrain.surface_height_at(p[1],p[2]))+10}
    end
    for _,trail in ipairs(trails or {}) do
        local id
        for i=1,#trail.points-1 do
            local a,b=point(trail.points[i]),point(trail.points[i+1])
            local curve={StartPoint=a,ControlPoint={X=(a.X+b.X)/2,Y=(a.Y+b.Y)/2,Z=(a.Z+b.Z)/2},Endpoint=b,CorridorWidth=trail.width or 2200}
            if not id then id=map:RegisterTrailFromCurve(curve)
            else assert(map:ExtendTrailWithCurve(id,curve),'trail segment rejected: '..trail.name) end
        end
        assert(id and id>=0,'trail rejected: '..trail.name)
        map:SetTrailDisplayName(id,FText(trail.name));map:SetTrailDifficulty(id,trail.difficulty or 1)
        map:SetTrailGroomed(id,true);map:RegisterOrUpdateTrail(id)
        local hubs=subsystem('HubConnectivitySubsystem')
        hubs:HandleTrailUnregistered(id);hubs:HandleTrailRegistered(id)
    end
    map:DetectIntersections();map:NotifyPaintComplete()
    local staff=subsystem('StaffSubsystem')
    require('resort_staff').assign(staff,lifts,buildings,function() Native.refresh_staff_pool(staff) end,function(message) api:log(message) end)
    local guests=subsystem('GuestSimulationSubsystem');guests:HandlePlaceableRegistered()
    guests:GetSpawner():SetSpawningEnabled(true)
    return actors
end
function Host.action(api,name,...)
    if name=='configure' then return configure(api,...) end
    if name=='snapshot' then return Host.snapshot(api) end
    if name=='charge' then
        local amount=...
        assert(finite(amount) and amount>=0 and amount%1==0,'charge must be a nonnegative integer')
        if api._sandbox then return true end
        return charge(...)
    end
    if name=='revenue' then
        local amount=...
        assert(finite(amount) and amount>=0 and amount%1==0,'invalid revenue')
        local e=subsystem('EconomySubsystem');e:RecordRevenue(amount,0)
        return true
    end
    if name=='weather' then
        local weather,temp=...
        assert(type(weather)=='number' and weather>=0 and weather<=3 and weather%1==0,'invalid weather')
        assert(finite(temp) and temp>=-80 and temp<=60,'invalid temperature')
        local w=subsystem('WeatherSubsystem');w:ForceTemperature(temp);w:ForceWeather(weather)
        return true
    end
    if name=='placeables' then
        local list={}
        for _,actor in ipairs(FindAllOf('PlaceableActor') or {}) do
            if current(actor) and not actor.bIsPreview then list[#list+1]=Host.describe(actor) end
        end
        return list
    end
    if name=='installation' then
        -- A scenario's maintenance model must not close lifts, lock demolition
        -- or reapply operating costs in a sandbox game.
        if api._sandbox then return true end
        return installation(...)
    end
    if name=='place_resort' then return place_resort(api,...) end
    if name=='hub_names' then return hub_names(api,...) end
    if name=='trail_rating_system' then return require('trail_ratings').set(api,...) end
    if name=='get_trail_rating_system' then return require('trail_ratings').get(api) end
    if name=='get_trail_rating_capabilities' then return require('trail_ratings').capabilities() end
    error('unknown scenario action: '..tostring(name))
end
Host.subsystem,Host.current= subsystem,current
return Host
