package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;tests/?.lua;'..package.path
local Mock=require('support.umg');Mock.install()
local Host={current=function(o) return not o.foreign end,
    describe=function(o) return {id=o.id} end}
package.preload.scenario_host=function() return Host end
local owner=Mock.object('CostBreakdownWidget');owner.WidgetTree=Mock.object('WidgetTree')
owner.OperationsSectionVBox=Mock.object('VerticalBox');owner.RevenueHeaderLabel=Mock.object('TextBlock')
local building=Mock.object('BuildingManagementWidget');building.WidgetTree=Mock.object('WidgetTree')
building.InfoTabContent=Mock.object('VerticalBox');building.IdentityTypeName=Mock.object('TextBlock')
building.InfoLiftTodayRevenueLabel=Mock.object('TextBlock');building.InfoLiftTodayRevenueLabel.Font={Size=20,TypefaceFontName='Regular'}
building.ManagedTarget=Mock.object('LiftActor');building.ManagedTarget.id='lift'
local foreign=Mock.object('CostBreakdownWidget');foreign.foreign=true
local status=Mock.object('TopStatusBarWidget');status.DateText=Mock.object('TextBlock')
status.DateText:SetText(FText('Nov 11 · Year 1'))
local effort,orders,callbacks,unload=2,0,{},nil
local api={_timer_generation=1,_sync_state=function() end,
    _game_options={currency='CHF',start_year=2003},
    _building_properties=function(actor) assert(actor.id=='lift');return {{label='État',value='67 %',fraction=.67}} end,
    _resort_panel={title='Entretien',properties=function() return {{label='Budget',value=effort*100}} end,
      controls={{label='Effort',options={'Minimum','Préventif','Renforcé'},get=function()return effort end,set=function(n)effort=n end}},
      actions={{label=function()return 'Travaux '..orders end,enabled=function()return orders==0 end,run=function()orders=orders+1 end}}},
    every=function(_,delay,callback) assert(delay==500);callbacks[#callbacks+1]=callback end,
    on=function(_,event,callback) assert(event=='map.unloading');unload=callback end,
    log=function(_,message) error(message) end}
local V=require('scenario_view');V.start(api)
assert(owner.OperationsSectionVBox:GetChildrenCount()==1 and building.InfoTabContent:GetChildrenCount()==1)
local card=owner.OperationsSectionVBox:GetChildAt(0)
assert(card.class_name=='Border' and card.padding.Left==12,'management controls are not inside a padded card')
local buttons=FindAllOf('Button');assert(#buttons==4 and not buttons[2].enabled)
assert(buttons[1].Slot.size.SizeRule==1 and buttons[3].Slot.size.Value==1,'maintenance choices do not share the available width')
assert(buttons[4]:GetChildAt(0).Slot.padding.Top==6,'action buttons have no usable vertical padding')
local price=Mock.object('TextBlock');price:SetText(FText('$120,000'))
callbacks[1]();assert(price:GetText():ToString()=='$120,000','native currency formatting was rewritten after render')
assert(status.DateText:GetText():ToString()=='Nov 11 · Year 1','the scenario rewrote the native calendar display')
status.DateText:SetText(FText('Nov 12 · Year 1'))
Mock.emit(buttons[3],'OnClicked');assert(effort==3)
callbacks[1]();assert(not buttons[3].enabled and buttons[2].enabled)
assert(status.DateText:GetText():ToString()=='Nov 12 · Year 1','a native date update was overwritten by the scenario')
Mock.emit(buttons[4],'OnClicked');callbacks[1]();assert(orders==1 and not buttons[4].enabled)
-- Native tab/selection refresh can remove the extension's child widgets.
owner.OperationsSectionVBox:ClearChildren();building.InfoTabContent:ClearChildren()
callbacks[1]();assert(owner.OperationsSectionVBox:GetChildrenCount()==1 and building.InfoTabContent:GetChildrenCount()==1)
assert(#FindAllOf('Button')==4,'native panel refresh duplicated callbacks')
local bars=FindAllOf('ProgressBar');assert(#bars==1 and bars[1].percent==.67)
local caption=building.InfoTabContent:GetChildAt(0):GetChildAt(0):GetChildAt(0)
assert(caption.Font.Size==20 and caption.Font.TypefaceFontName=='Regular','building properties did not use the native information font')
api._timer_generation=2;Mock.emit(buttons[1],'OnClicked');assert(effort==3,'a stale control modified an unloaded map')
unload();assert(not next(V.actions) and owner.OperationsSectionVBox:GetChildrenCount()==0 and building.InfoTabContent:GetChildrenCount()==0)
assert(price:GetText():ToString()=='$120,000','the scenario currency escaped its session')
local Api=require('api')
local denied=Api.new({}, {id='test.no-permission'})
assert(not pcall(denied.state,denied,{}))
assert(not pcall(denied.building_properties,denied,function()return{}end))
assert(not pcall(denied.resort_panel,denied,{}))
assert(not pcall(denied.scenario,denied,{title='x',objectives={}}))
assert(not pcall(denied.game.snapshot,denied.game))
print('Scenario controls: maintenance callbacks, purchase availability, gauges, native refresh, stale controls and permissions OK')
