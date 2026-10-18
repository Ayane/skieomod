package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function object(o)
    o.IsValid=function()return true end;o.GetFullName=function()return 'Live object' end;return o
end
local function text(v)return {ToString=function()return v end} end
FText=text
local world=object({GetAddress=function()return 1 end})
local foreign=object({GetAddress=function()return 2 end})
local rows={Small={MonthlyInterestRate=.01,PaybackMonths=24,DisplayName=text('Small')},
    Medium={MonthlyInterestRate=.015,PaybackMonths=24,DisplayName=text('Medium')},
    Large={MonthlyInterestRate=.02,PaybackMonths=24,DisplayName=text('Large')}}
local sizes={[0]=1.5,[1]=4,[2]=8}
local settings=object({LoanTiersTable=object({ForEachRow=function(_,f)for k,v in pairs(rows)do f(k,v)end end}),
    LoanDaysOfIncome={ForEach=function(_,f)for k,v in pairs(sizes)do
        f({get=function()return k end},{get=function()return v end,set=function(_,n)sizes[k]=n end})
    end end,Find=function(_,k)return {set=function(_,n)sizes[k]=n end} end}})
local economy=object({GetSettings=function()return settings end,GetWorld=function()return world end})
local time=object({GetWorld=function()return world end})
local function hub(id,x,owner)
    return object({HubId={A=-1,B=0,C=0,D=id},GetWorld=function()return owner or world end,
        K2_GetActorLocation=function()return {X=x,Y=0,Z=0}end,
        NameLabel=object({K2_SetText=function(self,value)self.text=value:ToString()end})})
end
local hubs={hub(1,2),hub(2,98),hub(3,0,foreign)}
FindAllOf=function(name)return name=='EconomySubsystem' and {economy} or name=='TimeSubsystem' and {time} or hubs end
package.preload.UEHelpers=function()return {GetWorld=function()return world end} end
for _,n in ipairs({'terrain','scene_objects'})do package.preload[n]=function()return {}end end
local batches={}
package.preload.native_terrain=function()return {name_hubs=function(names)
    if #names>0 then batches[#batches+1]=names end;return true
end}end
local H=require('scenario_host');local events={}
local api={on=function(_,name,f)assert(name=='map.unloading');events[#events+1]=f end}
local loans={Small={name='Working capital',income_days=1.5,annual_rate=.06,months=24},
    Medium={name='Safety upgrades',income_days=4,annual_rate=.05,months=60},
    Large={name='Infrastructure loan',income_days=8,annual_rate=.045,months=120}}
H.action(api,'configure',{loans=loans})
assert(rows.Medium.PaybackMonths==60 and math.abs(rows.Medium.MonthlyInterestRate-.05/12)<1e-12)
assert(rows.Large.PaybackMonths==120 and rows.Large.DisplayName:ToString()=='Infrastructure loan')
assert(sizes[0]==1.5 and sizes[2]==8,'native income underwriting was replaced by an ignored principal')
events[1]();assert(rows.Medium.MonthlyInterestRate==.015 and rows.Medium.PaybackMonths==24 and rows.Medium.DisplayName:ToString()=='Medium')
assert(sizes[1]==4,'native loan sizing leaked into the next map')
for _,bad in ipairs({{annual_rate=-.1,months=60,income_days=4},{annual_rate=.05,months=1.5,income_days=4},{annual_rate=.05,months=60,income_days=0}})do
    local denied={on=api.on};assert(not pcall(H.action,denied,'configure',{loans={Medium=bad}}))
    assert(rows.Medium.MonthlyInterestRate==.015,'invalid config mutated a shared loan row')
end
local anchors={{name='Bourg-Saint-Bernard',x=0,y=0},{name='Col de Menouve',x=100,y=0}}
assert(H.action(api,'hub_names',anchors)==2 and #batches==1)
assert(batches[1][1].key=='ffffffff000000000000000000000001','signed FGuid was not normalized')
assert(hubs[1].NameLabel.text=='Bourg-Saint-Bernard' and hubs[2].NameLabel.text=='Col de Menouve' and hubs[3].NameLabel.text==nil)
hubs[1].NameLabel.text='Personal name';assert(H.action(api,'hub_names',anchors)==0 and #batches==1 and hubs[1].NameLabel.text=='Personal name')
hubs[#hubs+1]=hub(4,90);assert(H.action(api,'hub_names',anchors)==1 and #batches==2)
assert(not pcall(H.action,api,'hub_names',{{name=string.rep('x',33),x=0,y=0}}))
print('Scenario finance/hubs: monthly rates, terms, native underwriting, unload restoration, geographic anchors, signed GUIDs and world isolation OK')
