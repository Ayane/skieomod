-- Map-owned inspection of decorative animals. Pick the displayed triangles
-- without making an animal a physical obstacle to visitors or terrain tools.
local UE,Ground,Theme=require('UEHelpers'),require('animated_ground'),require('ui_theme')
local Selection={actions={}}
local function valid(o)return o and o:IsValid()end
local function dot(a,b)return a.X*b.X+a.Y*b.Y+a.Z*b.Z end
local function sub(a,b)return {X=a.X-b.X,Y=a.Y-b.Y,Z=a.Z-b.Z}end
local function cross(a,b)return {X=a.Y*b.Z-a.Z*b.Y,Y=a.Z*b.X-a.X*b.Z,Z=a.X*b.Y-a.Y*b.X}end
function Selection.hit(vertices,triangles,origin,direction,limit)
    local nearest=limit or math.huge
    for j=1,#triangles,3 do
        local a,b,c=vertices[triangles[j]+1],vertices[triangles[j+1]+1],vertices[triangles[j+2]+1]
        local e1,e2=sub(b,a),sub(c,a);local p=cross(direction,e2);local det=dot(e1,p)
        if math.abs(det)>1e-8 then
            local s=sub(origin,a);local u=dot(s,p)/det
            if u>=0 and u<=1 then
                local q=cross(s,e1);local v=dot(direction,q)/det
                if v>=0 and u+v<=1 then
                    local t=dot(e2,q)/det
                    if t>=0 and t<nearest then nearest=t end
                end
            end
        end
    end
    return nearest<(limit or math.huge) and nearest or nil
end
local function text(value,maximum)
    assert(type(value)=='string' and #value<=maximum,'Invalid entity inspection text')
    return value
end
function Selection.describe(provider)
    local data=provider();assert(type(data)=='table','Inspection must return a table')
    local result={title=text(data.title,96),subtitle=text(data.subtitle or '',96),note=text(data.note or '',512),properties={}}
    assert(type(data.properties or {})=='table' and #(data.properties or {})<=4,'Inspection has at most four properties')
    for i,p in ipairs(data.properties or {}) do result.properties[i]={label=text(p.label,64),value=text(p.value,128)} end
    return result
end
local function close(state)
    if state.selected then state.selected.highlight(false) end
    state.selected=nil
    if valid(state.widget) then state.widget:SetVisibility(1) end
end
function Selection.install(current_session)
    if Selection.hook then return end
    Selection.hook=function(context)
        local button=context:get();local action=Selection.actions[button:GetAddress()]
        if action then close(action) end
    end
    require('compatibility').hook('entities.focus','/Script/UMG.Widget:SetKeyboardFocus','pre',Selection.hook,{})
    -- Explicit engine-side QA: no desktop focus, cursor movement or simulated
    -- mouse events are needed to inspect a projected animal in a capture.
    if current_session then
        RegisterConsoleCommandHandler('custommap_test_entity',function(_,parameters)
            ExecuteInGameThread(function()
                local api=current_session()
                if not api then return end
                local ok,message=pcall(function()
                    local state=assert(api._entity_selection,'no inspectable entities')
                    if parameters[1]=='focus' then
                        local entry=assert(state.entries[tonumber(parameters[2]) or 1],'unknown entity')
                        local _,_,pose=entry.pose();assert(pose,'entity has no displayed pose')
                        require('map_entities').focus_camera(api,pose.x,pose.y,pose.z+35,500)
                    elseif parameters[1]=='select' then
                        local x,y=tonumber(parameters[2]),tonumber(parameters[3])
                        assert(x and y and x>=0 and y>=0 and x<=32768 and y<=32768,'invalid screen coordinates')
                        Selection.tick(state,true,{x=x,y=y})
                    elseif parameters[1]=='close' then close(state)
                    else error('use focus <index>, select <x> <y>, or close') end
                end)
                api:log(ok and 'entity QA '..tostring(parameters[1])..' complete' or 'entity QA failed: '..tostring(message))
            end)
            return true
        end)
    end
end
local function panel(state)
    if valid(state.widget) then return end
    assert(Selection.hook,'Entity selection was not initialized at loader startup')
    -- Reuse the game's initialized, full-screen HUD layer instead of creating
    -- a separate base UUserWidget through UE4SS. Only our card belongs to the
    -- map and is removed when the map unloads.
    local host
    for _,widget in ipairs(FindAllOf('EventMarkerLayerWidget') or {}) do
        if valid(widget) and widget:IsInViewport() and valid(widget.RootCanvas) and valid(widget.WidgetTree) then host=widget;break end
    end
    assert(host,'Entity inspection HUD layer is unavailable')
    local tree,root=host.WidgetTree,host.RootCanvas
    local card=Theme.border(tree,Theme.color('536473'),9)
    local slot=root:AddChildToCanvas(card)
    -- Adjust initialized native anchors in place, as for native widget styles.
    local anchors=slot.LayoutData.Anchors
    anchors.Minimum.X=1;anchors.Minimum.Y=0
    anchors.Maximum.X=1;anchors.Maximum.Y=0
    slot:SetPosition({X=-362,Y=100});slot:SetSize({X=342,Y=248})
    slot:SetZOrder(100)
    local box=Theme.construct('CanvasPanel',tree);card:AddChild(box)
    local white=Theme.colors.white
    state.title=Theme.label(box,tree,'',nil,22,white,18,14,252,32)
    state.subtitle=Theme.label(box,tree,'',nil,14,Theme.colors.ice,18,49,300,25)
    state.properties={}
    for i=1,4 do state.properties[i]=Theme.label(box,tree,'',nil,15,white,18,81+(i-1)*25,300,25) end
    state.note=Theme.label(box,tree,'',nil,14,Theme.colors.ice,18,186,300,48)
    local button=Theme.button(tree,'X',nil,nil,Theme.color('536473'),16,white)
    Theme.place(box,button,298,12,30,30)
    Selection.actions[button:GetAddress()]=state;state.button=button
    button.OnClicked:Add(button,'SetKeyboardFocus')
    state.widget,state.card=card,card
    card:SetVisibility(0)
end
local function refresh(state)
    if not state.selected then return end
    local data=Selection.describe(state.selected.provider)
    panel(state);state.widget:SetVisibility(0)
    state.title:SetText(FText(data.title));state.subtitle:SetText(FText(data.subtitle));state.note:SetText(FText(data.note))
    for i,widget in ipairs(state.properties) do
        local p=data.properties[i];widget:SetText(FText(p and p.label..' : '..p.value or ''))
    end
end
local function obstructed_ui(controller)
    local ui=controller.UIManager
    if not valid(ui) then return false end
    for _,name in ipairs({'PauseMenuWidget','BuildingManagementWidget','GuestMenuWidget','SnowblowerPanelWidget','TrailEditWidget'}) do
        local widget=ui[name]
        if valid(widget) and widget:IsInViewport() and widget:IsVisible() and widget:IsHovered() then return true end
    end
    return false
end
function Selection.visible(surface,origin,direction,distance)
    -- Query terrain/snow along the view ray using scalar/vector API data.
    -- FHitResult contains new native object-handle structs in this game build;
    -- copying that output through UE4SS can crash its property translator.
    for i=1,12 do
        local t=distance*i/13
        local x,y,z=origin.X+direction.X*t,origin.Y+direction.Y*t,origin.Z+direction.Z*t
        local ground=surface(x,y)
        if ground.inside and z<ground.z-.2 then return false end
    end
    return true
end
function Selection.tick(state,clicked,screen)
    if state.session._loading_success~=true then return end
    local pc=UE.GetPlayerController();if not valid(pc) then return end
    if (pc.CurrentMode or 0)~=0 then close(state);return end
    if state.selected and valid(pc.UIManager) then
        for _,name in ipairs({'GuestMenuWidget','BuildingManagementWidget'}) do
            local widget=pc.UIManager[name]
            if valid(widget) and widget:IsInViewport() and widget:IsVisible() then close(state);return end
        end
    end
    if clicked then
        if (pc.CurrentMode or 0)~=0 or obstructed_ui(pc) or valid(state.card) and state.card:IsHovered() then return end
        local origin,direction={},{}
        local projected
        if screen then projected=pc:DeprojectScreenPositionToWorld(screen.x,screen.y,origin,direction)
        else projected=pc:DeprojectMousePositionToWorld(origin,direction) end
        if not projected then return end
        local nearest,best=math.huge,nil
        for _,entry in ipairs(state.entries) do
            local vertices,triangles,pose=entry.pose()
            if vertices and #vertices>0 and pose then
                local axes=Ground.axes(pose.yaw,pose.pitch)
                local ray=Ground.inverse(axes,{X=origin.X-pose.x,Y=origin.Y-pose.y,Z=origin.Z-pose.z})
                local d=Ground.inverse(axes,direction)
                local t=Selection.hit(vertices,triangles,ray,d,nearest)
                if t then
                    local px,py,pz=origin.X+direction.X*t,origin.Y+direction.Y*t,origin.Z+direction.Z*t
                    local surface=entry.surface(px,py)
                    if surface.inside and pz>=surface.z-1 and Selection.visible(entry.surface,origin,direction,t) then nearest=t;best=entry end
                end
            end
        end
        close(state)
        if best then state.selected=best;best.highlight(true);refresh(state) end
    end
    if state.selected then
        local now=UE.GetGameplayStatics():GetRealTimeSeconds(UE.GetWorld())
        if not state.updated or now-state.updated>.5 then refresh(state);state.updated=now end
    end
end
function Selection.attach(api,entry)
    local session=api._session or api
    local state=session._entity_selection
    if not state then
        state={session=session,entries={}};session._entity_selection=state
        session._cleanups=session._cleanups or {}
        session._cleanups[#session._cleanups+1]=function()
            close(state)
            if valid(state.button) then Selection.actions[state.button:GetAddress()]=nil end
            if valid(state.widget) then state.widget:RemoveFromParent() end
            state.entries={}
        end
        require('map_input').bind_pointer(session,function(action)
            if action=='close' then close(state) else Selection.tick(state,true) end
        end)
        session:every(16,function()Selection.tick(state)end,true)
    end
    state.entries[#state.entries+1]=entry
end
return Selection
