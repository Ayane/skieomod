package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Options=require('game_options')
local function widget(value) return {GetText=function() return {ToString=function() return value end} end} end
local owner={SeedInput=widget('4294967295'),DayLengthValueText=widget('0.5x'),DaysPerMonthValueText=widget('3'),SandboxStateText=widget('On')}
local options=Options.capture(owner)
assert(options.seed==-1 and options.day_length==0.5 and options.days_per_month==3 and options.sandbox)
owner.SandboxStateText=widget('Off');assert(not Options.capture(owner).sandbox)
owner.DayLengthValueText=widget('2,5x');assert(Options.capture(owner).day_length==2.5)
for key,value in pairs({SeedInput='bad',DayLengthValueText='0x',DaysPerMonthValueText='32',SandboxStateText='unknown'}) do
    local previous=owner[key];owner[key]=widget(value)
    assert(not pcall(Options.capture,owner),'invalid native option accepted: '..key)
    owner[key]=previous
end
assert(not Options.validate().sandbox and Options.validate().days_per_month==1)
local copy=Options.validate(options);options.sandbox=false
assert(copy.sandbox,'download handoff retained mutable options')
local Api=require('api')
local api=Api.new({}, {id='test.sandbox',permissions={'gameplay'}})
api._gameplay_allowed=true;api._sandbox=true
assert(api:scenario({title='Disabled scenario',objectives={{}}})==false and not api._scenario)
api._sandbox=false;api:scenario({title='Normal scenario',objectives={{}}})
assert(api._scenario.title=='Normal scenario')
print('Game options: native controls, sandbox and calendar, copied download handoff, invalid values and disabled sandbox objectives OK')
