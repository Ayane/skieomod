-- A per-world copy: other maps keep their own native biome and forecasts.
local UE=require('UEHelpers')
local Climate={}
local function current(name)
 local world=UE.GetWorld()
 for _,o in ipairs(FindAllOf(name)or{})do if o:IsValid()then
  local ok,w=pcall(function()return o:GetWorld()end)
  if ok and w and w:IsValid()and w:GetAddress()==world:GetAddress()then return o end
 end end
end
function Climate.apply(api,restored)
 local data=require('json').decode(api:read_asset('Data/climate.json'))
 local environment=assert(current('LevelEnvironmentSettings'))
 local weather=assert(current('WeatherSubsystem'))
 local snow=assert(current('SnowSimulationSubsystem'))
 local original=environment.BiomeSettings
 local original_snow=snow.CachedBiomeSettings
 local copy=StaticConstructObject(original:GetClass(),environment,
  UE.FindOrAddFName('SkiEO_VeymontClimate'),0,0,false,false,original)
 assert(copy and copy:IsValid(),'Cannot create the Veymont climate')
 -- Pin the clone through native UPROPERTY references before any GC can run.
 environment.BiomeSettings=copy;weather.CachedBiomeSettings=copy;snow.CachedBiomeSettings=copy
 copy.Latitude=data.latitude
 copy.ClimateReferenceElevationMeters=data.reference_elevation_m
 copy.AverageAnnualSnowfallInches=math.floor(data.annual_fresh_snow_cm/2.54+.5)
 -- Native weather adjusts the reference temperature to its base elevation,
 -- then applies daily weather, seasonal variation and the altitude lapse.
 local rows={}
 copy.MonthlyClimate:ForEach(function(index,value)
  local old=value:get();local observed=data.months[(index+5)%12+1]
  rows[#rows+1]={RealTimeMinutes=old.RealTimeMinutes,
   GuestDemandMultiplier=old.GuestDemandMultiplier,
   BaseTemperatureC=observed.temperature_c,
   SnowfallRateMultiplier=old.SnowfallRateMultiplier*.46,
   StormModifier=old.StormModifier*.6}
 end)
 copy.MonthlyClimate=rows
 -- Clear/cloud/snow/blizzard: fewer long storms, no atmospheric-river bonus.
 copy.WeatherProfile={AtmosphericRiverChance=0,
  TransitionMatrix={Probabilities={.65,.32,.03,0, .35,.55,.095,.005, .15,.60,.24,.01, .1,.65,.20,.05}},
  PhaseDurationScale=1,StormDurationMinHours=1,StormDurationMaxHours=2}
 local saved=api:state()
 if not restored or saved.veymont_climate_version~=1 then
  weather:ReleaseForcedTemperature();weather:ReleaseForcedWeather()
  weather:OnMonthChanged(current('TimeSubsystem'):GetCurrentMonth())
  weather.CurrentBaseTemperature=weather:ComputeDailyMeanTemperatureC(weather:GetWeatherType())
  saved.veymont_climate_version=1
 end
 api:on('map.unloading',function()
  if environment:IsValid()then environment.BiomeSettings=original end
  if weather:IsValid()then weather.CachedBiomeSettings=original end
  if snow:IsValid()then snow.CachedBiomeSettings=original_snow end
 end)
 api:log('Veymont: native seasonal climate, Gresse 1220 m (Meteo-France 1991–2020)')
end
return Climate
