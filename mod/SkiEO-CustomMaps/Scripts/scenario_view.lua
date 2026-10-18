-- Extend the game's Corporate Takeover briefing/tracker and native management UI.
local Theme, Host = require('ui_theme'), require('scenario_host')
local View={actions={}}
local management_colors={card=Theme.color('6B7B88'),text=Theme.color('EEE9E1'),button=Theme.color('536473')}
local function valid(o) return o and o:IsValid() end
local function text(widget,value) if valid(widget) then widget:SetText(FText(tostring(value or ''))) end end
local function label(tree,value,font,size,color) return Theme.text(tree,value,font,size or 15,color or management_colors.text) end
local function padded(parent,child,top,bottom)
    local slot=parent:AddChild(child)
    slot:SetPadding({Left=0,Top=top or 0,Right=0,Bottom=bottom or 0})
    return slot
end
local function row(parent,tree,property,font)
    local box=Theme.construct('VerticalBox',tree);parent:AddChild(box)
    local caption=label(tree,'',font,valid(font) and font.Font.Size or 15);box:AddChild(caption)
    local bar
    if property.fraction~=nil then
        bar=Theme.construct('ProgressBar',tree);box:AddChild(bar)
        bar:SetFillColorAndOpacity(Theme.colors.green)
    end
    return {box=box,text=caption,bar=bar}
end
local function update_rows(parent,tree,cache,properties,font)
    properties=properties or {}
    assert(#properties<=16,'too many script properties')
    local rebuild=#cache~=#properties
    for i,p in ipairs(properties) do
        if cache[i] and (cache[i].bar~=nil)~=(p.fraction~=nil) then rebuild=true end
    end
    if rebuild then
        parent:ClearChildren();for k in pairs(cache) do cache[k]=nil end
        for i,p in ipairs(properties) do cache[i]=row(parent,tree,p,font) end
    end
    for i,p in ipairs(properties) do
        text(cache[i].text,p.label..' : '..tostring(p.value or ''))
        if cache[i].bar then cache[i].bar:SetPercent(math.max(0,math.min(1,p.fraction or 0))) end
    end
end
local function bind(api,button,callback)
    if not View.hook then
        View.hook=function(context)
            local button=context:get();local action=View.actions[button:GetAddress()]
            if action and action.api._timer_generation==action.generation and valid(action.button) then
                local ok,message=pcall(function() action.callback();action.api:_sync_state() end)
                if not ok then action.api:log('scenario control failed: '..tostring(message)) end
            end
        end
        RegisterHook('/Script/UMG.Widget:SetKeyboardFocus',View.hook)
    end
    View.actions[button:GetAddress()]={api=api,generation=api._timer_generation,button=button,callback=callback}
    button.OnClicked:Add(button,'SetKeyboardFocus')
end
local function controls(api,owner,box,font)
    local def=api._resort_panel;local tree=owner.WidgetTree
    local heading=label(tree,def.title or 'Scenario',font,19);padded(box,heading,0,8)
    local properties=Theme.construct('VerticalBox',tree);padded(box,properties,0,8)
    local screen={owner=owner,box=box,properties=properties,rows={},controls={},actions={}}
    for _,setting in ipairs(def.controls or {}) do
        assert(type(setting.options)=='table' and #setting.options>0 and #setting.options<=16,'invalid resort setting')
        local caption=label(tree,setting.label,font);padded(box,caption,4,6)
        local buttons=Theme.construct('HorizontalBox',tree);padded(box,buttons,0,8)
        local views={};screen.controls[#screen.controls+1]={setting=setting,views=views}
        for index,option in ipairs(setting.options) do
            local button,caption=Theme.button(tree,option,nil,font,management_colors.button,14,management_colors.text)
            caption.Slot:SetPadding({Left=8,Top=6,Right=8,Bottom=6})
            local slot=buttons:AddChild(button)
            slot:SetSize({Value=1,SizeRule=1})
            slot:SetPadding({Left=index==1 and 0 or 4,Top=0,Right=index==#setting.options and 0 or 4,Bottom=0})
            bind(api,button,function() setting.set(index) end)
            views[#views+1]={button=button,text=caption,index=index}
        end
    end
    for _,action in ipairs(def.actions or {}) do
        local button,caption=Theme.button(tree,type(action.label)=='function' and action.label() or action.label,nil,font,management_colors.button,15,management_colors.text)
        caption.Slot:SetPadding({Left=10,Top=6,Right=10,Bottom=6})
        padded(box,button,3,3);bind(api,button,action.run)
        screen.actions[#screen.actions+1]={button=button,text=caption,action=action}
    end
    return screen
end
local function tracker_header(panel,tree,definition)
    local owner=panel.owner
    if not panel.header then
        -- Native code rewrites HeaderText to GOALS on each refresh. Keep its
        -- private reference intact, but replace the button's visible content.
        local parent=owner.HeaderText:GetParent()
        if not valid(parent) then return end
        local old_slot=owner.HeaderText.Slot
        local padding=old_slot.Padding
        panel.header_parent=parent
        panel.header_padding=padding and {Left=padding.Left,Top=padding.Top,Right=padding.Right,Bottom=padding.Bottom} or {Left=0,Top=0,Right=0,Bottom=0}
        panel.header_horizontal=old_slot.HorizontalAlignment or 2
        panel.header_vertical=old_slot.VerticalAlignment or 2
        panel.header=label(tree,definition.tracker_title or definition.title,owner.HeaderText,owner.HeaderText.Font.Size)
    end
    if valid(owner.HeaderText:GetParent()) then owner.HeaderText:RemoveFromParent() end
    if not valid(panel.header:GetParent()) then
        local slot=panel.header_parent:AddChild(panel.header)
        slot:SetPadding(panel.header_padding)
        slot:SetHorizontalAlignment(panel.header_horizontal)
        slot:SetVerticalAlignment(panel.header_vertical)
    end
end
local function native_scenario(api)
    local def=api._scenario;if not def then return end
    local system=Host.subsystem('ScenarioSubsystem')
    local cls=StaticFindObject('/Script/SkiResortSimulator.ScenarioDefinition')
    local template=LoadAsset('/Game/Data/Scenarios/DA_Scenario_CorporateTakeover.DA_Scenario_CorporateTakeover')
    assert(valid(template),'native scenario template unavailable')
    -- Clone initialized native structs, then mutate their fields in place.
    -- UE4SS cannot safely construct arrays containing nested struct arrays
    -- from Lua tables on the shipped UE 5.8 build.
    local scenario=StaticConstructObject(cls,system,0,0,0,false,false,template,0,0,0)
    assert(valid(scenario),'could not construct scripted scenario')
    scenario.ScenarioId=FName(api._map.id)
    scenario.DisplayName=FText(def.title);scenario.Tagline=FText(def.goal or '')
    scenario.BriefingBody=FText(def.briefing or '');scenario.BriefingGoalLine=FText(def.goal or '')
    local index=0
    scenario.Objectives:ForEach(function(_,remote)
        local objective=remote:get();index=index+1
        objective.Label=FText(def.objectives[index] and def.objectives[index].label or '')
        objective.bLatches=false
        objective.Conditions:ForEach(function(_,condition)
            local value=condition:get();value.Type=6;value.Threshold=2147483647;value.Comparison=0
        end)
    end)
    assert(index>=#def.objectives,'native scenario template has too few objective rows')
    scenario.DeadlineFiscalYear=1000
    scenario.Economy.StartingBalance=(api._game_options or {}).starting_balance or 250000
    scenario.Economy.TicketPrice=(api._game_options or {}).ticket_price or 38
    scenario.Economy.SeedLoan.Principal=0
    scenario.Economy.bLockTicketPrice=false
    system.ActiveScenario=scenario;api._native_scenario=scenario
    api:on('map.unloading',function() if valid(system) and valid(scenario) then system.ActiveScenario=nil end end)
    if not api._restoring then Host.subsystem('SkiResortPlayerController').UIManager:OnScenarioBriefing() end
end
function View.start(api)
    if not api._scenario and not api._building_properties and not api._resort_panel and not api._game_options then return end
    local panels={}
    local outcome=nil
    native_scenario(api)
    api:_sync_state()
    local function tick()
        for _,owner in ipairs(FindAllOf('BuildingManagementWidget') or {}) do
            if Host.current(owner) and valid(owner.ManagedTarget) and api._building_properties then
                local key=owner:GetAddress();local panel=panels[key]
                if not panel or not valid(panel.owner) then
                    local box=Theme.construct('VerticalBox',owner.WidgetTree);owner.InfoTabContent:AddChild(box)
                    panel={owner=owner,box=box,rows={}};panels[key]=panel
                end
                if not valid(panel.box:GetParent()) then owner.InfoTabContent:AddChild(panel.box) end
                update_rows(panel.box,owner.WidgetTree,panel.rows,
                    api._building_properties(Host.describe(owner.ManagedTarget)),
                    valid(owner.InfoLiftTodayRevenueLabel) and owner.InfoLiftTodayRevenueLabel
                        or valid(owner.InfoAllTimeRidesLabel) and owner.InfoAllTimeRidesLabel
                        or owner.IdentityDescription)
            end
        end
        for _,owner in ipairs(FindAllOf('CostBreakdownWidget') or {}) do
            if Host.current(owner) and valid(owner.OperationsSectionVBox) and api._resort_panel then
                local key=owner:GetAddress();local panel=panels[key]
                if not panel or not valid(panel.owner) then
                    local card=Theme.border(owner.WidgetTree,management_colors.card,6)
                    card:SetPadding({Left=12,Top=12,Right=12,Bottom=12})
                    padded(owner.OperationsSectionVBox,card,8,0)
                    local box=Theme.construct('VerticalBox',owner.WidgetTree);card:AddChild(box)
                    panel=controls(api,owner,box,owner.RevenueHeaderLabel);panel.card=card;panels[key]=panel
                end
                if not valid(panel.card:GetParent()) then padded(owner.OperationsSectionVBox,panel.card,8,0) end
                update_rows(panel.properties,owner.WidgetTree,panel.rows,
                    api._resort_panel.properties and api._resort_panel.properties() or {},owner.RevenueHeaderLabel)
                for _,control in ipairs(panel.controls) do
                    local selected=control.setting.get()
                    for _,option in ipairs(control.views) do
                        option.button:SetIsEnabled(option.index~=selected)
                    end
                end
                for _,action in ipairs(panel.actions) do
                    text(action.text,type(action.action.label)=='function' and action.action.label() or action.action.label)
                    action.button:SetIsEnabled(not action.action.enabled or action.action.enabled())
                end
            end
        end
        if api._scenario then
            local def=api._scenario
            for _,owner in ipairs(FindAllOf('MilestoneTrackerWidget') or {}) do
                if Host.current(owner) and valid(owner.RowsBox) then
                    local key=owner:GetAddress();local panel=panels[key]
                    if not panel or not valid(panel.owner) then
                        panel={owner=owner,box=Theme.construct('VerticalBox',owner.WidgetTree),rows={},native_children={}}
                        panels[key]=panel
                    end
                    tracker_header(panel,owner.WidgetTree,def)
                    -- Native display rows include an overall cash summary in
                    -- addition to the objective rows. Replace their visible
                    -- containers so synthetic engine thresholds never leak.
                    for i=owner.RowsBox:GetChildrenCount()-1,0,-1 do
                        local child=owner.RowsBox:GetChildAt(i)
                        if child:GetAddress()~=panel.box:GetAddress() then
                            panel.native_children[#panel.native_children+1]=child;child:RemoveFromParent()
                        end
                    end
                    if not valid(panel.box:GetParent()) then owner.RowsBox:AddChild(panel.box) end
                    local properties={}
                    for i,objective in ipairs(def.objectives) do
                        local progress=objective.progress()
                        properties[i]={label=objective.label,value=progress.value,fraction=progress.fraction or 0}
                    end
                    update_rows(panel.box,owner.WidgetTree,panel.rows,properties,owner.HeaderText)
                end
            end
            for _,owner in ipairs(FindAllOf('CallToActionWidget') or {}) do
                if Host.current(owner) and valid(owner.BriefingDeadlineText) then text(owner.BriefingDeadlineText,def.deadline or '') end
            end
            local status=def.status and def.status() or 'active'
            if status~='active' and outcome~=status then
                outcome=status
                local manager=Host.subsystem('SkiResortPlayerController').UIManager
                if status=='completed' then manager:OnScenarioCompleted() else manager:OnScenarioFailed() end
            end
        end
    end
    tick();api:every(500,tick)
    api:on('map.unloading',function()
        for _,panel in pairs(panels) do
            if valid(panel.card or panel.box) then (panel.card or panel.box):RemoveFromParent() end
            if valid(panel.header) then panel.header:RemoveFromParent() end
            if valid(panel.header_parent) and valid(panel.owner) and not valid(panel.owner.HeaderText:GetParent()) then
                local slot=panel.header_parent:AddChild(panel.owner.HeaderText)
                slot:SetPadding(panel.header_padding)
                slot:SetHorizontalAlignment(panel.header_horizontal)
                slot:SetVerticalAlignment(panel.header_vertical)
            end
            if valid(panel.owner) and panel.native_children then
                for i=#panel.native_children,1,-1 do
                    local child=panel.native_children[i]
                    if valid(child) and not valid(child:GetParent()) then panel.owner.RowsBox:AddChild(child) end
                end
            end
        end
        for address,action in pairs(View.actions) do if action.api==api then View.actions[address]=nil end end

    end)
end
return View
