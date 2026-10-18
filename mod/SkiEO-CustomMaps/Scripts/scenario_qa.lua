-- Explicit console QA only. TimeSubsystem pause alone does not stop GPU snow.
local Helpers,Host,Json=require('UEHelpers'),require('scenario_host'),require('json')
local QA={active=false}
local function freeze()
    if not QA.active then return end
    local world=Helpers.GetWorld()
    if not world or not world:IsValid() or world:GetAddress()~=QA.world then QA.active=false;return end
    Host.subsystem('TimeSubsystem'):PauseTime()
    local gameplay=Helpers.GetGameplayStatics()
    if not gameplay:IsGamePaused(world) then assert(gameplay:SetGamePaused(world,true),'engine pause failed') end
end
function QA.pause(runtime)
    local api=assert(runtime.active_api,'no custom map session')
    assert(api._loading_finished and api._loading_success~=false,'map is not ready')
    if not QA.active then
        local time=Host.subsystem('TimeSubsystem')
        QA.rate=time:GetTimeRate()
        if QA.rate<=0 then QA.rate=time:GetTargetTimeMultiplier() end
        if QA.rate<=0 then QA.rate=1 end
    end
    QA.world=Helpers.GetWorld():GetAddress();QA.active=true;freeze()
    if not QA.handle then
        QA.callback=function() freeze();return false end
        QA.handle=LoopInGameThreadWithDelay(100,QA.callback)
        api:on('map.unloading',function()
            if QA.active and Helpers.GetWorld():GetAddress()==QA.world then
                Helpers.GetGameplayStatics():SetGamePaused(Helpers.GetWorld(),false)
            end
            QA.active=false;CancelDelayedAction(QA.handle);QA.handle=nil;QA.callback=nil
        end)
    end
    if not QA.save_hook then
        QA.save_callback=function() freeze() end
        QA.save_hook={RegisterHook('/Script/SkiResortSimulator.SaveLoadMenuWidget:OnConfirmClicked',function() end,QA.save_callback)}
    end
end
function QA.resume()
    if not QA.active then return end
    QA.active=false
    Helpers.GetGameplayStatics():SetGamePaused(Helpers.GetWorld(),false)
    local time=Host.subsystem('TimeSubsystem')
    time:ResumeTime();time:SetTimeRate(QA.rate or 1)
end
function QA.capture(runtime,label)
    assert(type(label)=='string' and #label<=48 and label:match('^[%w_-]+$'),'checkpoint label must contain letters, digits, underscores or hyphens')
    QA.pause(runtime)
    local map,api=runtime.active_map,runtime.active_api
    local report={label=label,captured_utc=os.date('!%Y-%m-%dT%H:%M:%SZ'),map_id=map.id,map_version=map.metadata.version,
        engine_paused=Helpers.GetGameplayStatics():IsGamePaused(Helpers.GetWorld()),calendar=Host.snapshot(api),
        script_state=api._persistent,lifts={},loans={}}
    local economy=Host.subsystem('EconomySubsystem')
    local time,weather=Host.subsystem('TimeSubsystem'),Host.subsystem('WeatherSubsystem')
    report.calendar.hour=time:GetTimeOfDayHours()
    -- The current rate can be zero or still interpolating while paused.
    -- Compare the requested speed, which survives the native save UI.
    report.calendar.time_rate=time:GetTargetTimeMultiplier()
    report.weather={type=weather:GetWeatherType(),base_temperature_c=weather:GetBaseTemperature()}
    local function counter(primary,fallback)
        local fn=StaticFindObject('/Script/SkiResortSimulator.EconomySubsystem:'..primary)
        return fn and fn:IsValid() and economy[primary](economy) or economy[fallback](economy)
    end
    report.debt={outstanding=economy:GetTotalLoanBalance(),borrowed=counter('GetYearPrincipalBorrowed','GetSeasonPrincipalBorrowed'),repaid=counter('GetYearPrincipalPaid','GetSeasonPrincipalPaid')}
    report.ticket_price=economy:GetTicketPrice()
    local snow=Host.subsystem('SnowSimulationSubsystem')
    local target=snow.CoarseMipReadbackFp16RT
    local render=StaticFindObject('/Script/Engine.Default__KismetRenderingLibrary')
    local bounds=map.terrain
    local function snow_at(point)
        if not target or not target:IsValid() or not bounds.source then return nil end
        local origin=bounds.origin_centimeters
        local u=(point.X-origin[1])/(bounds.size_meters[1]*100)
        local v=(point.Y-origin[2])/(bounds.size_meters[2]*100)
        local x=math.max(0,math.min(target.SizeX-1,math.floor(u*target.SizeX)))
        local y=math.max(0,math.min(target.SizeY-1,math.floor(v*target.SizeY)))
        local pixel=render:ReadRenderTargetRawPixel(Helpers.GetWorld(),target,x,y,false)
        return {packed_cm=pixel.R,fresh_cm=pixel.G,total_cm=pixel.R+pixel.G}
    end
    for _,loan in ipairs(economy:GetActiveLoans()) do
        if loan.OriginalPrincipal==nil then loan=loan:get() end
        assert(type(loan.OriginalPrincipal)=='number' and type(loan.MonthlyInterestRate)=='number','unsupported native loan report')
        report.loans[#report.loans+1]={tier=loan.Tier,principal=loan.OriginalPrincipal,remaining=loan.RemainingBalance,
            monthly_rate=loan.MonthlyInterestRate,months=loan.PaybackMonths}
    end
    for _,actor in ipairs(FindAllOf('LiftActor') or {}) do if Host.current(actor) and not actor.bIsPreview then
        report.lifts[#report.lifts+1]={id=Host.id(actor),name=actor:GetInstanceName():ToString(),
            running=actor:IsLiftRunning(),skiing=actor:IsLiftAvailableForSkiing(),
            status=actor:GetStatusLabelText():ToString(),rides=actor:GetTotalGuestRidersAllTime(),staff=actor:GetAssignedLiftieCount(),
            bottom_snow=snow_at(actor:K2_GetActorLocation()),top_snow=snow_at(actor:GetTopTerminalLocation())}
    end end
    local dump=StaticFindObject('/Script/SkiResortSimulator.Default__SaveDumpLibrary')
    local directory=dump:GetSaveGamesDir():ToString():gsub('\\','/')
    local path=directory..'/CustomMap-QA-'..map.id:gsub('[^%w_-]','-')..'-'..label..'.json'
    local file=assert(io.open(path,'wb'));file:write(Json.encode(report));file:close()
    runtime.log('paused QA checkpoint: '..path)
    return report,path
end
return QA
