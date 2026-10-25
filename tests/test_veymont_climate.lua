package.path='mod/SkiEO-Veymont/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={IsValid=function()return true end,GetAddress=function()return 1 end}
package.preload.UEHelpers=function()return{GetWorld=function()return world end,FindOrAddFName=function(n)return n end}end
local original={GetClass=function()return{}end,IsValid=function()return true end}
local clone={IsValid=function()return true end,MonthlyClimate={ForEach=function(_,fn)for i=1,12 do fn(i,{get=function()return{RealTimeMinutes=50,GuestDemandMultiplier=.7,SnowfallRateMultiplier=1,StormModifier=1}end})end end}}
local months_source=clone.MonthlyClimate
local function valid()return true end
local function getworld()return world end
local env={IsValid=valid,GetWorld=getworld,BiomeSettings=original}
local snow={IsValid=valid,GetWorld=getworld,CachedBiomeSettings=original}
local releases,rebuilt=0,0
local weather={IsValid=valid,GetWorld=getworld,CachedBiomeSettings=original,
 ReleaseForcedTemperature=function()releases=releases+1 end,ReleaseForcedWeather=function()releases=releases+1 end,
 OnMonthChanged=function(_,m)assert(m==5);rebuilt=rebuilt+1 end,ComputeDailyMeanTemperatureC=function()return 2 end,GetWeatherType=function()return 0 end}
FindAllOf=function(name)return name=='SnowSimulationSubsystem'and{snow}or name=='WeatherSubsystem'and{weather}or name=='LevelEnvironmentSettings'and{env}or name=='TimeSubsystem'and{{IsValid=valid,GetWorld=getworld,GetCurrentMonth=function()return 5 end}}or{}end
StaticConstructObject=function(_,outer,_,_,_,_,_,template)assert(outer==env and template==original);return clone end
local saved={};local cleanup
local api={state=function()return saved end,read_asset=function(_,name)local f=assert(io.open('mod/SkiEO-Veymont/'..name));local bytes=f:read('*a');f:close();return bytes end,on=function(_,event,fn)assert(event=='map.unloading');cleanup=fn end,log=function()end}
local C=require('climate');C.apply(api,true)
assert(env.BiomeSettings==clone and weather.CachedBiomeSettings==clone,'Per-map climate must be pinned natively')
assert(original.MonthlyClimate==nil,'Shared native biome was modified')
assert(clone.MonthlyClimate[6].BaseTemperatureC<1 and clone.MonthlyClimate[1].BaseTemperatureC>15,'Fiscal July/December mapping is wrong')
assert(clone.AverageAnnualSnowfallInches>120 and clone.AverageAnnualSnowfallInches<130)
for i=1,4 do local sum=0;for j=1,4 do sum=sum+clone.WeatherProfile.TransitionMatrix.Probabilities[(i-1)*4+j]end;assert(math.abs(sum-1)<1e-7)end
assert(releases==2 and rebuilt==1)
cleanup()
clone.MonthlyClimate=months_source
C.apply(api,true);assert(releases==2 and rebuilt==1,'Saved forecasts or player weather overrides were reset')
cleanup();assert(env.BiomeSettings==original and weather.CachedBiomeSettings==original)
print('Veymont climate: native per-map copy, seasonal month mapping, forecast preservation and cleanup OK')
