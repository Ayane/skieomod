package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function object(value)
    value.IsValid=function() return true end
    value.GetFullName=function() return 'Live object' end
    return value
end
local world=object({GetAddress=function() return 1 end})
local foreign=object({GetAddress=function() return 2 end})
local e=object({balance=100,revenue=0,expenses=0})
function e:GetBalance() return self.balance end
function e:SetBalance(value) self.balance=value end
function e:RecordExpense(amount) self.balance=self.balance-amount;self.expenses=self.expenses+amount end
function e:RecordRevenue(amount) self.balance=self.balance+amount;self.revenue=self.revenue+amount end
function e:GetYearTotalRevenue() return self.revenue end
function e:GetYearTotalExpenses() return self.expenses end
local t=object({month=6,year=2,phase=.5})
function t:GetCurrentMonth() return self.month end
function t:GetYearNumber() return self.year end
function t:GetMonthProgress() return self.phase end
function t:GetDaysPerMonth() return 1 end
function t:IsTimePaused() return true end
e.GetWorld=function() return world end;t.GetWorld=e.GetWorld
local wrong=object({GetWorld=function() return foreign end})
FindAllOf=function(name) return name=='EconomySubsystem' and {wrong,e} or {t} end
StaticFindObject=function() return object({}) end
package.preload.UEHelpers=function() return {GetWorld=function() return world end} end
for _,name in ipairs({'terrain','scene_objects','native_terrain'}) do package.preload[name]=function() return {} end end
local H=require('scenario_host')
local api={_game_options={start_year=2003}}
assert(not H.current(wrong),'a subsystem in another world was used')
assert(H.action(api,'charge',20,1,false))
assert(e.balance==80 and e.expenses==20,'a recorded expense was deducted twice')
assert(not H.action(api,'charge',90,1,false) and e.balance==80 and e.expenses==20,'an unfunded purchase was charged')
assert(H.action(api,'charge',100,1,true) and e.balance==-20 and e.expenses==120,'mandatory upkeep did not allow a deficit')
H.action(api,'revenue',50)
assert(e.balance==30 and e.revenue==50,'recorded revenue was credited twice')
for _,value in ipairs({-1,1.2,math.huge}) do assert(not pcall(H.action,api,'charge',value,1,true)) end
local now=H.snapshot(api)
assert(now.year==2005 and now.month==1 and now.months==30.5 and now.revenue==50 and now.expenses==120)
-- Older supported game builds use season counters; UFunctions are callable userdata.
StaticFindObject=function(path) return {IsValid=function() return not path:find('GetYearTotal',1,true) end} end
e.GetSeasonTotalRevenue=e.GetYearTotalRevenue;e.GetSeasonTotalExpenses=e.GetYearTotalExpenses
assert(H.snapshot(api).revenue==50,'legacy financial counters were not supported')
-- The visual configuration uses the same host operation as handwritten Lua.
function e:SetBalance(value) self.balance=value end
function e:SetTicketPrice(value) self.ticket_price=value end
H.action({},'configure',{currency='CHF',start_year=2003,starting_balance=250000,ticket_price=38})
assert(e.balance==250000 and e.ticket_price==38,'fresh scenario settings were not applied')
e.balance,e.ticket_price=12345,42
H.action({_restoring=true},'configure',{currency='CHF',start_year=2003,starting_balance=250000,ticket_price=38})
assert(e.balance==12345 and e.ticket_price==42,'scenario configuration overwrote a saved balance or ticket price')
print('Scenario host: world isolation, single financial entry, unfunded purchases, deficits and game counter compatibility OK')
