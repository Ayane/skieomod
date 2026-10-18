package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function object(o)o.IsValid=function()return true end;return o end
local world=object({GetAddress=function()return 1 end})
local paused,clock_paused,callback,post,unload=false,false,nil,nil,nil
local gameplay={SetGamePaused=function(_,w,value)assert(w==world);paused=value;return true end,
    IsGamePaused=function()return paused end}
package.preload.UEHelpers=function()return {GetWorld=function()return world end,GetGameplayStatics=function()return gameplay end}end
local time={PauseTime=function()clock_paused=true end,ResumeTime=function()clock_paused=false end,
    GetTimeOfDayHours=function()return 8 end,GetTimeRate=function()return clock_paused and 0 or 5 end,
    GetTargetTimeMultiplier=function()return 1 end,SetTimeRate=function(_,rate)assert(rate==5)end}
local contract={Tier=1,OriginalPrincipal=40000,RemainingBalance=39000,MonthlyInterestRate=.05/12,PaybackMonths=60}
local economy={GetActiveLoans=function()return {{get=function()return contract end}}end,
    GetTotalLoanBalance=function()return 39000 end,GetSeasonPrincipalBorrowed=function()return 40000 end,
    GetSeasonPrincipalPaid=function()return 1000 end,GetTicketPrice=function()return 38 end}
local weather={GetWeatherType=function()return 2 end,GetBaseTemperature=function()return -6 end}
local snow={CoarseMipReadbackFp16RT=object({SizeX=64,SizeY=64})}
local Host={snapshot=function()return {balance=250000,months=16.3}end,current=function()return true end,id=function()return 'lift' end,
    subsystem=function(n)return ({TimeSubsystem=time,EconomySubsystem=economy,WeatherSubsystem=weather,SnowSimulationSubsystem=snow})[n]end}
package.preload.scenario_host=function()return Host end
LoopInGameThreadWithDelay=function(ms,f)assert(ms==100);callback=f;return 17 end
CancelDelayedAction=function(id)assert(id==17);callback=nil end
RegisterHook=function(name,pre,p)assert(name:find('OnConfirmClicked',1,true));post=p;return 1,2 end
local render={ReadRenderTargetRawPixel=function(_,w,target,x,y,normal)
    assert(w==world and target==snow.CoarseMipReadbackFp16RT and x>=0 and x<64 and y>=0 and y<64 and not normal)
    return {R=100,G=20}
end}
StaticFindObject=function(n)
    if n:find('Principal',1,true) then return {IsValid=function()return false end} end
    return n:find('Rendering',1,true) and render or {GetSaveGamesDir=function()return {ToString=function()return '/tmp' end}end}
end
local position={X=0,Y=0,Z=190000}
local lift={GetInstanceName=function()return {ToString=function()return 'Menouve' end}end,
    IsLiftRunning=function()return true end,IsLiftAvailableForSkiing=function()return true end,
    GetStatusLabelText=function()return {ToString=function()return 'Operating' end}end,
    GetTotalGuestRidersAllTime=function()return 2 end,GetAssignedLiftieCount=function()return 2 end,
    K2_GetActorLocation=function()return position end,GetTopTerminalLocation=function()return position end}
FindAllOf=function()return {lift}end
local api={_loading_finished=true,_persistent={effort=2},on=function(_,event,f)assert(event=='map.unloading');unload=f end}
local runtime={active_api=api,active_map={id='qa.unit',metadata={version='0.2.1'},terrain={source={},origin_centimeters={-100,-100,0},size_meters={2,2}}},log=function()end}
local QA,J=require('scenario_qa'),require('json')
assert(not pcall(QA.capture,runtime,'../unsafe') and not paused,'invalid label affected the world')
local report,path=QA.capture(runtime,'unit');assert(paused and clock_paused and report.engine_paused)
assert(report.lifts[1].top_snow.total_cm==120 and report.loans[1].months==60 and report.debt.outstanding==39000)
local f=assert(io.open(path,'rb'));local saved=J.decode(f:read('*a'));f:close();os.remove(path)
assert(saved.calendar.balance==250000 and saved.script_state.effort==2 and saved.lifts[1].rides==2)
economy.GetYearPrincipalBorrowed=function()return 80000 end;economy.GetYearPrincipalPaid=function()return 2000 end
local find_legacy=StaticFindObject
StaticFindObject=function(n)return n:find('Principal',1,true) and {IsValid=function()return true end} or find_legacy(n)end
local current,path_current=QA.capture(runtime,'unit_current');os.remove(path_current)
assert(current.debt.borrowed==80000 and current.debt.repaid==2000,'current-build debt counters were not selected')
paused=false;clock_paused=false;post();assert(paused and clock_paused,'save UI escaped the full pause guard')
paused=false;callback();assert(paused,'pause did not survive a native menu refresh')
QA.resume();assert(not paused and not clock_paused);post();assert(not paused,'ordinary saves were paused outside explicit QA')
QA.pause(runtime);unload();assert(not paused and not callback and not QA.active,'world stayed paused after leaving the map')
print('Scenario QA: explicit full pause, save confirmation guard, snapshot finances/snow/rides, resume and unload cleanup OK')
