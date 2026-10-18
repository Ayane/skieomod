package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;tests/?.lua;'..package.path
local Mock=require('support.umg');Mock.install();FName=function(s)return s end
local function array(values)
    values.ForEach=function(self,callback)for i,value in ipairs(self) do callback(i,{get=function()return value end})end end
    return values
end
local function definition()
    local objectives={}
    for i=1,4 do objectives[i]={Conditions=array({{Type=1,Threshold=100,Comparison=0}})} end
    local result=Mock.object('ScenarioDefinition');result.Objectives=array(objectives)
    result.Economy={SeedLoan={Principal=2000000}}
    return result
end
local template=definition();LoadAsset=function()return template end
local construct=StaticConstructObject
StaticConstructObject=function(cls,outer,a,b,c,d,e,donor,...)
    if cls.class_name:find('ScenarioDefinition',1,true) then
        assert(donor==template,'native scenario was built without a struct template')
        return definition()
    end
    return construct(cls,outer,a,b,c,d,e,donor,...)
end
local system=Mock.object('ScenarioSubsystem')
package.preload.scenario_host=function()return {current=function()return true end,
    subsystem=function(name)assert(name=='ScenarioSubsystem');return system end}end
local tracker=Mock.object('MilestoneTrackerWidget');tracker.WidgetTree=Mock.object('WidgetTree')
tracker.RowsBox=Mock.object('VerticalBox');tracker.HeaderText=Mock.object('TextBlock')
tracker.CollapseButton=Mock.object('Button');tracker.CollapseButton:AddChild(tracker.HeaderText)
local native={}
for i=1,5 do native[i]=Mock.object('VerticalBox');tracker.RowsBox:AddChild(native[i]) end
local timer,unload=nil,{}
local objectives={}
for i=1,4 do local n=i;objectives[i]={label='Objectif '..i,progress=function()return {value='Valeur '..n,fraction=n/2}end} end
local api={_restoring=true,_timer_generation=1,_map={id='test.scenario'},
    _scenario={title='Le sursis',tracker_title='Objectifs',objectives=objectives},_sync_state=function()end,
    every=function(_,delay,callback)assert(delay==500);timer=callback end,
    on=function(_,event,callback)assert(event=='map.unloading');unload[#unload+1]=callback end}
require('scenario_view').start(api)
assert(system.ActiveScenario.ScenarioId=='test.scenario' and system.ActiveScenario.Economy.SeedLoan.Principal==0)
assert(tracker.RowsBox:GetChildrenCount()==1,'native cash summary remained visible')
local panel=tracker.RowsBox:GetChildAt(0);assert(panel:GetChildrenCount()==4,'scenario objectives were duplicated')
local header=tracker.CollapseButton:GetChildAt(0)
assert(header~=tracker.HeaderText and header:GetText():ToString()=='Objectifs')
tracker.HeaderText:SetText(FText('GOALS'))
assert(header:GetText():ToString()=='Objectifs','a native refresh caused the visible title to flicker')
local bars=FindAllOf('ProgressBar');assert(#bars==4 and bars[1].percent==.5 and bars[4].percent==1)
-- A native refresh must not bring back its extra synthetic summary.
tracker.RowsBox:AddChild(native[1]);timer()
assert(tracker.RowsBox:GetChildrenCount()==1 and panel:GetChildrenCount()==4)
for _,callback in ipairs(unload) do callback() end
assert(tracker.RowsBox:GetChildrenCount()==5 and not system.ActiveScenario)
assert(tracker.CollapseButton:GetChildAt(0)==tracker.HeaderText,'native tracker header was not restored')
print('Scenario tracker: initialized native template, four custom rows, no synthetic summary, progress and native refresh restoration OK')
