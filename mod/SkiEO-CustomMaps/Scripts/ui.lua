local WorkshopView = require("workshop_view")
local Presentation = require("map_presentation")
local Theme = require("ui_theme")
local Assets = require("ui_assets")
local GameOptions = require("game_options")
local GameVersion = require("game_version")
local VersionWarning = require("ui_version_warning")
local C = Theme.colors
-- Runtime UMG adapter for the native New Game dialog.  The game builds its
-- widgets in C++, so the loader adds standard UMG children after Construct.
local UI = {
    runtime = nil,
    button_actions = {},
    screens = {},
    failed_screens = {},
    pending_views = {},
    hook_installed = false,
    poll_started = false,
}

local function valid(object)
    return object and object:IsValid()
end

local function class(path)
    local result = StaticFindObject(path)
    if valid(result) then return result end
    return nil
end

local function is_a(object, path)
    if not valid(object) then return false end
    local wanted = class(path)
    return wanted ~= nil and object:IsA(wanted)
end

local function construct(path, outer)
    local widget_class = class(path)
    if not widget_class then error("UMG class is unavailable: " .. path, 0) end
    local result = StaticConstructObject(
        widget_class, outer, 0, 0, 0, false, false, nil, 0, 0, 0)
    if not valid(result) then error("could not construct " .. path, 0) end
    return result
end

local function belongs_to(object, owner, tree)
    local current = object
    for _ = 1, 12 do
        if not valid(current) then return false end
        local address = current:GetAddress()
        if address == owner:GetAddress() or address == tree:GetAddress() then return true end
        current = current:GetOuter()
    end
    return false
end

local function widget_text(widget)
    local ok, value = pcall(function() return widget:GetText():ToString() end)
    return ok and value or nil
end

local function find_label(owner, tree, wanted)
    for _, text in ipairs(FindAllOf("TextBlock") or {}) do
        if valid(text) and belongs_to(text, owner, tree) then
            local value = widget_text(text)
            if value and value:lower() == wanted:lower() then return text end
        end
    end
    return nil
end

local function button_ancestor(widget)
    local current = widget
    for _ = 1, 8 do
        if not valid(current) then return nil end
        if is_a(current, "/Script/UMG.Button") then return current end
        current = current:GetParent()
    end
    return nil
end

local function copy_property(target, source, property)
    pcall(function() target[property] = source[property] end)
end

local function clone_button_style(target, source)
    if not valid(source) then return end
    for _, property in ipairs({
        "ClickMethod", "TouchMethod", "PressMethod", "IsFocusable"
    }) do
        copy_property(target, source, property)
    end
end

local function add_child(panel, child)
    local slot = panel:AddChild(child)
    if not valid(slot) then error("UMG AddChild returned no slot", 0) end
    return slot
end

local function fill_slot(slot)
    if is_a(slot, "/Script/UMG.CanvasPanelSlot") then
        slot:SetAnchors({ Minimum = { X = 0.0, Y = 0.0 }, Maximum = { X = 1.0, Y = 1.0 } })
        slot:SetOffsets({ Left = 0.0, Top = 0.0, Right = 0.0, Bottom = 0.0 })
        -- Native OptionsBackdrop is at 500. Keep both injected layers above
        -- normal content and below the modal so it owns rendering and input.
        pcall(function() slot:SetZOrder(10) end)
    else
        pcall(function() slot:SetHorizontalAlignment(0) end)
        pcall(function() slot:SetVerticalAlignment(0) end)
    end
end


local function find_native_tab(owner, wanted)
    local ok, text, button = pcall(function()
        local texts = owner.TabTexts
        local buttons = owner.TabButtons
        local count = math.min(#texts, #buttons)
        for index = 1, count do
            local candidate = widget_text(texts[index])
            if candidate and candidate:lower() == wanted:lower() then
                return texts[index], buttons[index]
            end
        end
        return nil, nil
    end)
    if ok and valid(text) and valid(button) then return text, button end
    return nil, nil
end

local function find_tab(owner, tree, wanted)
    local text, button = find_native_tab(owner, wanted)
    if valid(text) and valid(button) then return text, button end
    text = find_label(owner, tree, wanted)
    return text, text and button_ancestor(text) or nil
end

local function canvas_child(canvas, child, left, top, right, bottom)
    local slot = canvas:AddChildToCanvas(child)
    slot:SetAnchors({ Minimum = { X = left, Y = top }, Maximum = { X = right, Y = bottom } })
    slot:SetOffsets({ Left = 0.0, Top = 0.0, Right = 0.0, Bottom = 0.0 })
    return slot
end

local function fixed_canvas_child(canvas, child, x, y, width, height)
    local slot = canvas:AddChildToCanvas(child)
    slot:SetPosition({ X = x, Y = y })
    slot:SetSize({ X = width, Y = height })
    return slot
end

local function bind_button(button, callback, event)
    UI.button_actions[button:GetAddress()] = { owner = button, callback = callback }
    local ok, message = pcall(function()
        -- SetKeyboardFocus is a harmless zero-argument UFunction with the same
        -- signature as OnClicked.  Hooking it gives a native UButton a Lua
        -- callback without manufacturing a Blueprint class at runtime.
        button[event or "OnClicked"]:Add(button, "SetKeyboardFocus")
    end)
    if not ok then
        UI.runtime.log("could not bind Custom UI button: " .. tostring(message))
        return false
    end
    return true
end

local function set_visible(widget, visible)
    if valid(widget) then widget:SetVisibility(visible and 0 or 1) end
end

local function item_state(entry)
    return entry and entry.__workshop and UI.runtime.workshop.state(entry.__workshop.published_file_id) or nil
end
local function catalog_busy()
    return UI.runtime.catalog_busy and UI.runtime.catalog_busy() or UI.runtime.workshop.busy
end
local function catalog_message()
    return UI.runtime.catalog_message and UI.runtime.catalog_message() or UI.runtime.workshop.message or ""
end
local function clear_panel(panel)
    if valid(panel) then pcall(function() panel:ClearChildren() end) end
end

local function add_wire_line(screen, first, second, major)
    local line = Theme.border(screen.tree, major and C.wire or Theme.color("529CB9"), 0)
    line:SetVisibility(4)
    pcall(function() line:SetRenderTransformPivot({ X = 0.5, Y = 0.5 }) end)
    local thickness = major and 1.3 or 0.8
    local slot = fixed_canvas_child(screen.wire_canvas, line, 0, 0, 1, thickness)
    screen.wire_lines[#screen.wire_lines + 1] = {
        widget = line,
        slot = slot,
        first = first,
        second = second,
        thickness = thickness,
    }
end

local function build_wireframe(screen, map)
    clear_panel(screen.wire_canvas)
    screen.wire_lines = {}
    screen.wire_vertices = {}
    set_visible(screen.wire_empty, not (map and map.terrain and map.terrain.preview))
    if not map or not map.terrain or not map.terrain.preview then return end
    local samples = map.terrain.preview.samples
    local rows = #samples
    local columns = #samples[1]
    for row = 1, rows do
        screen.wire_vertices[row] = {}
        for column = 1, columns do
            screen.wire_vertices[row][column] = {
                x = (column - 1) / (columns - 1) - 0.5,
                y = (row - 1) / (rows - 1) - 0.5,
                z = samples[row][column] - 0.5,
            }
        end
    end
    for row = 1, rows do
        for column = 1, columns - 1 do
            add_wire_line(screen, screen.wire_vertices[row][column],
                screen.wire_vertices[row][column + 1],
                row == 1 or row == rows or (row - 1) % 4 == 0)
        end
    end
    for column = 1, columns do
        for row = 1, rows - 1 do
            add_wire_line(screen, screen.wire_vertices[row][column],
                screen.wire_vertices[row + 1][column],
                column == 1 or column == columns or (column - 1) % 4 == 0)
        end
    end
end

local function projected(point, angle)
    local cosine = math.cos(angle)
    local sine = math.sin(angle)
    local x = cosine * point.x - sine * point.y
    local depth = sine * point.x + cosine * point.y
    return 200 + x * 280, 112 + depth * 90 - point.z * 105
end

local function update_wireframe(screen)
    screen.wire_angle = (screen.wire_angle or 0) + 0.012
    for _, line in ipairs(screen.wire_lines or {}) do
        if valid(line.widget) and valid(line.slot) then
            local x1, y1 = projected(line.first, screen.wire_angle)
            local x2, y2 = projected(line.second, screen.wire_angle)
            local dx = x2 - x1
            local dy = y2 - y1
            local length = math.sqrt(dx * dx + dy * dy)
            local thickness = line.thickness or 1.15
            line.slot:SetPosition({
                X = (x1 + x2 - length) / 2,
                Y = (y1 + y2) / 2 - thickness / 2,
            })
            line.slot:SetSize({ X = length, Y = thickness })
            line.widget:SetRenderTransformAngle(math.deg(math.atan(dy, dx)))
        end
    end
end

local function update_marker(screen, map)
    local location = map and type(map.location)=="table" and map.location
    local function within(value, minimum, maximum)
        return type(value)=="number" and value>=minimum and value<=maximum
    end
    local position = location and location.world_map_uv
    local x, y
    if type(position)=="table" and within(position[1],0,1) and within(position[2],0,1) then
        x, y = position[1], position[2]
    elseif location and within(location.longitude,-180,180) and within(location.latitude,-90,90) then
        x = (location.longitude + 180) / 360
        y = (90 - location.latitude) / 180
    end
    -- Featured placeholders have a place label before coordinates arrive.
    -- Keep their card usable; only a complete position can display a marker.
    set_visible(screen.marker, x~=nil and y~=nil)
    if x==nil or y==nil or not valid(screen.marker_slot) then return end
    local anchored_x = 0.02 + x * 0.96
    local anchored_y = 0.05 + y * 0.90
    screen.marker_slot:SetAnchors({
        Minimum = { X = anchored_x, Y = anchored_y },
        Maximum = { X = anchored_x, Y = anchored_y },
    })
    screen.marker_slot:SetAlignment({ X = 0.5, Y = 0.5 })
    screen.marker_slot:SetPosition({ X = 0.0, Y = 0.0 })
end

local function show_screen(screen, visible)
    if visible and not screen.visible then
        screen.native_visibility = {}
        for index=0,screen.root:GetChildrenCount()-1 do
            local child=screen.root:GetChildAt(index)
            if valid(child) and child:GetAddress()~=screen.view:GetAddress()
                and (not screen.tab_view or child:GetAddress()~=screen.tab_view:GetAddress()) then
                screen.native_visibility[#screen.native_visibility+1]={widget=child,visibility=child:GetVisibility()}
                child:SetVisibility(1)
            end
        end
    elseif not visible and screen.visible then
        for _,entry in ipairs(screen.native_visibility or {}) do
            if valid(entry.widget) then entry.widget:SetVisibility(entry.visibility) end
        end
        screen.native_visibility=nil
    end
    screen.visible=visible
    if valid(screen.view) then screen.view:SetVisibility(visible and 4 or 1) end
    if screen.custom_button then
        Theme.button_style(screen.custom_button,visible and C.selected or C.row)
        screen.custom_text:SetColorAndOpacity(Theme.slate(visible and C.white or C.navy))
    end
    if visible then
        for _,tab in ipairs(screen.native_tabs or {}) do
            Theme.button_style(tab.button,C.row)
            tab.text:SetColorAndOpacity(Theme.slate(C.navy))
        end
    end
end

local function select_native_tab(screen,selected)
    show_screen(screen,false)
    if valid(screen.owner.MapSizeRow) then screen.owner.MapSizeRow:SetVisibility(0) end
    for _,tab in ipairs(screen.native_tabs) do
        local active=tab.button:GetAddress()==selected:GetAddress()
        Theme.button_style(tab.button,active and C.selected or C.row)
        tab.text:SetColorAndOpacity(Theme.slate(active and C.white or C.navy))
    end
end

local function update_details(screen,map)
    local card=Presentation.card(map,item_state(map))
    screen.detail_title:SetText(FText(card.title))
    screen.detail_subtitle:SetText(FText(card.subtitle))
    screen.detail_credits:SetText(FText(card.credits or ""))
    screen.details:SetText(FText(card.workshop_details or card.description))
    screen.terrain_text:SetText(FText("Terrain: "..card.terrain))
    screen.elevation_text:SetText(FText("Elevation: "..card.elevation))
    screen.trails_text:SetText(FText(card.trails.." trails"))
    screen.lifts_text:SetText(FText(card.lifts.." lifts"))
    clear_panel(screen.difficulties)
    if #card.difficulties==0 then
        screen.difficulties:AddChild(Theme.text(screen.tree,"Not specified",screen.text_style,14,C.muted))
    end
    for _,difficulty in ipairs(card.difficulties) do
        local box=construct("/Script/UMG.SizeBox",screen.tree)
        box:SetHeightOverride(23)
        screen.difficulties:AddChild(box)
        local row=construct("/Script/UMG.CanvasPanel",screen.tree)
        box:AddChild(row)
        Theme.icon(row,screen.tree,difficulty,screen.text_style,0,1,17,C[({beginner="green",intermediate="blue",advanced="red",expert="black"})[difficulty]])
        Theme.label(row,screen.tree,difficulty:sub(1,1):upper()..difficulty:sub(2),screen.text_style,15,C.navy,28,2,140,25)
    end
    local action,enabled=WorkshopView.action(map,item_state(map),catalog_busy())
    screen.start_text:SetText(FText(action))
    screen.start_button:SetIsEnabled(enabled)
    set_visible(screen.start_icon,action=="Play")
    local update=map and map.__update
    set_visible(screen.workshop_button,map and (map.__workshop~=nil or not not update))
    screen.workshop_text:SetText(FText(update and "Update map" or "Workshop page ↗"))
end

local function select_map(screen,index)
    local map=UI.runtime.browse_items()[index]
    if not map then return end
    screen.play_error=nil
    UI.runtime.selected_index=index
    screen.selected_index=index
    screen.selected_key=map.__workshop and map.__workshop.published_file_id or map.id
    for _,row in ipairs(screen.rows or {}) do
        local selected=row.index==index
        Theme.button_style(row.button,selected and C.selected or C.row)
        row.title:SetColorAndOpacity(Theme.slate(selected and C.white or C.navy))
        row.subtitle:SetColorAndOpacity(Theme.slate(selected and C.row or C.muted))
    end
    update_details(screen,map)
    screen.details_scroll:ScrollToStart()
    update_marker(screen,map)
    build_wireframe(screen,map)
    update_wireframe(screen)
end

local function preview_texture(screen,map)
    local key=map.__manifest_path or map.id
    local cached=key and screen.preview_cache[key]
    if cached and valid(cached.texture) then return cached.texture end
    local texture=Assets.preview(map,screen.owner)
    if texture and key then
        -- The hidden image holds a reflected brush reference across Lua/UE GC.
        local holder=construct("/Script/UMG.Image",screen.tree)
        holder:SetBrushFromTexture(texture,true)
        screen.asset_holder:AddChild(holder)
        screen.preview_cache[key]={texture=texture,holder=holder}
    end
    return texture
end

local function rebuild_list(screen)
    for _,row in ipairs(screen.rows or {}) do UI.button_actions[row.button:GetAddress()]=nil end
    clear_panel(screen.list)
    screen.rows={}
    local items=UI.runtime.browse_items()
    local selected
    for index,map in ipairs(items) do
        if Presentation.matches(map,screen.query,screen.source) then
            local box=construct("/Script/UMG.SizeBox",screen.tree)
            box:SetHeightOverride(66)
            local list_slot=screen.list:AddChild(box)
            list_slot:SetPadding({Left=5,Top=3,Right=5,Bottom=3})
            local button=construct("/Script/UMG.Button",screen.tree)
            clone_button_style(button,screen.button_style)
            Theme.button_style(button,C.row)
            box:AddChild(button)
            local row=construct("/Script/UMG.CanvasPanel",screen.tree)
            local row_slot=button:AddChild(row)
            row_slot:SetHorizontalAlignment(0)
            row_slot:SetVerticalAlignment(0)
            row:SetVisibility(4)
            row:SetClipping(1)
            local texture=preview_texture(screen,map)
            if not Assets.picture(row,screen.tree,texture,8,7,72,52) then
                Theme.place(row,Theme.border(screen.tree,C.ice,6),8,7,72,52)
                Theme.icon(row,screen.tree,"mountain",screen.text_style,27,13,33,C.navy)
            end
            local title=Theme.label(row,screen.tree,WorkshopView.title(map),
                screen.heading_style,16,C.navy,94,9,203,23)
            title:SetAutoWrapText(false);title:SetTextOverflowPolicy(1)
            local card=Presentation.card(map,item_state(map))
            local subtitle=Theme.label(row,screen.tree,card.location,screen.text_style,14,C.muted,94,35,203,24)
            subtitle:SetAutoWrapText(false);subtitle:SetTextOverflowPolicy(1)
            local downloaded=map.__read and (map.__web or map.__remote or map.__featured or map.__workshop)
            for _,text in ipairs({title,subtitle}) do
                text.Slot:SetAnchors({Minimum={X=0,Y=0},Maximum={X=1,Y=0}})
                local top=text==title and 9 or 35
                text.Slot:SetOffsets({Left=94,Top=top,Right=downloaded and 68 or 40,Bottom=24})
            end
            local function row_icon(kind,offset,color)
                local icon=Theme.icon(row,screen.tree,kind,screen.text_style,0,0,18,color)
                icon.Slot:SetAnchors({Minimum={X=1,Y=0.5},Maximum={X=1,Y=0.5}})
                icon.Slot:SetAlignment({X=1,Y=0.5})
                icon.Slot:SetPosition({X=-offset,Y=0})
                return icon
            end
            local source_icon=row_icon(map.__featured and "featured" or map.__workshop and "workshop"
                or (map.__web or map.__remote) and "web" or "local",12,C.navy)
            local installed_icon=downloaded and row_icon("downloaded",38,C.green) or nil
            bind_button(button,function() select_map(screen,index) end)
            screen.rows[#screen.rows+1]={button=button,index=index,title=title,subtitle=subtitle,
                source_icon=source_icon,installed_icon=installed_icon}
            local key=map.__workshop and map.__workshop.published_file_id or map.id
            if key==screen.selected_key or (not screen.selected_key and index==UI.runtime.selected_index) then selected=index end
        end
    end
    screen.scroll:ScrollToStart()
    if #screen.rows==0 then
        screen.list:AddChild(Theme.text(screen.tree,"No matching items.\nTry another search or source.",screen.text_style,17,C.muted))
        screen.selected_index,screen.selected_key,UI.runtime.selected_index=nil,nil,nil
        update_details(screen,nil)
        build_wireframe(screen,nil)
        update_marker(screen,nil)
        return
    end
    select_map(screen,selected or screen.rows[1].index)
end

local function update_version_warning(screen)
    VersionWarning.update(screen,GameVersion.poll())
end

local function build_screen(owner,tree,root,scenario_button,scenario_text,screen)
    screen.button_style=scenario_button
    screen.text_style=valid(owner.DescriptionText) and owner.DescriptionText or scenario_text
    screen.heading_style=valid(owner.KeyTitleText) and owner.KeyTitleText or scenario_text
    screen.wire_angle,screen.query,screen.preview_cache,screen.source=-0.55,"",{},"all"
    local view=construct("/Script/UMG.CanvasPanel",tree)
    screen.view=view
    view:SetVisibility(1)
    -- Keep the subtree owned by a live native root while controls are built.
    -- A hidden subtree never covers the native menu during construction.
    UI.pending_views[owner:GetAddress()]=view
    fill_slot(add_child(root,view))
    local canvas=Theme.scaled(view,tree,0.145,0.305,0.86,0.922,1200,590)
    local browser=construct("/Script/UMG.CanvasPanel",tree)
    Theme.place(canvas,browser,0,0,1200,590)
    local body=Theme.card(browser,tree,0,0,1200,590,C.ice)
    screen.browser_body,screen.browser_size=browser,canvas:GetParent()
    VersionWarning.create(screen,canvas,tree)
    update_version_warning(screen)
    Theme.icon(body,tree,"mountain",screen.text_style,28,10,30,C.navy)
    screen.list_title=Theme.label(body,tree,"CUSTOM MAPS",screen.heading_style,22,C.navy,68,16,240,31)
    local kind_button,kind_text=Theme.button(tree,"Mods",scenario_button,screen.text_style,C.row,14,C.navy)
    Theme.place(body,kind_button,285,14,62,30)
    bind_button(kind_button,function()
        UI.runtime.browse_kind=UI.runtime.browse_kind=="mod" and "map" or "mod"
        UI.runtime.selected_index=1
        screen.selected_key=nil
        kind_text:SetText(FText(UI.runtime.browse_kind=="mod" and "Maps" or "Mods"))
        screen.list_title:SetText(FText(UI.runtime.browse_kind=="mod" and "CUSTOM MODS" or "CUSTOM MAPS"))
        screen.search:SetHintText(FText(UI.runtime.browse_kind=="mod" and "Search mods…" or "Search maps…"))
        rebuild_list(screen)
    end)
    Theme.place(body,Theme.border(tree,C.row,8,C.edge),25,54,326,42)
    Theme.icon(body,tree,"search",screen.text_style,39,66,20,C.navy)
    screen.search=construct("/Script/UMG.EditableTextBox",tree)
    -- Keep the freshly constructed native style and change its fields in
    -- place. Copying a whole FEditableTextBoxStyle through UE4SS crashes.
    local search_style=screen.search.WidgetStyle
    search_style.TextStyle.Font=screen.text_style.Font
    search_style.TextStyle.Font.Size=16
    search_style.ForegroundColor=Theme.slate(C.navy)
    search_style.BackgroundImageNormal=Theme.brush(C.row,4)
    search_style.BackgroundImageHovered=Theme.brush(C.row,4)
    search_style.BackgroundImageFocused=Theme.brush(C.row,4)
    screen.search:SetHintText(FText("Search maps…"))
    screen.search:SetForegroundColor(C.navy)
    screen.search:SetJustification(0)
    Theme.place(body,screen.search,67,58,278,34)

    local list_frame=Theme.border(tree,Theme.color("CDDCE6"),10,C.edge)
    screen.source_buttons={}
    for index,definition in ipairs({{"all","All"},{"local","Local"},{"web","Web"},{"workshop","Steam"}}) do
        local source,label=definition[1],definition[2]
        local button=Theme.button(tree,label,scenario_button,screen.text_style,source==screen.source and C.ice or C.row,14,C.navy)
        Theme.place(body,button,25+(index-1)*82,103,77,30)
        screen.source_buttons[source]=button
        bind_button(button,function()
            screen.source=source
            for key,control in pairs(screen.source_buttons) do Theme.button_style(control,key==source and C.ice or C.row) end
            rebuild_list(screen)
        end)
    end
    Theme.place(body,list_frame,18,143,340,343)
    screen.scroll=construct("/Script/UMG.ScrollBox",tree)
    list_frame:AddChild(screen.scroll)
    screen.list=construct("/Script/UMG.VerticalBox",tree)
    screen.scroll:AddChild(screen.list)
    screen.asset_holder=construct("/Script/UMG.VerticalBox",tree)
    view:AddChild(screen.asset_holder)
    screen.asset_holder:SetVisibility(1)

    local map_frame=Theme.card(body,tree,372,24,420,229,C.row)
    screen.map_canvas=map_frame
    local texture_ok,texture=pcall(function() return owner.WorldSheetTexture end)
    if texture_ok and valid(texture) then
        local map_image=construct("/Script/UMG.Image",tree)
        map_image:SetBrushFromTexture(texture,true)
        canvas_child(map_frame,map_image,0.02,0.05,0.98,0.95)
        map_image:SetVisibility(4)
    else Theme.label(map_frame,tree,"Region map unavailable",screen.text_style,18,C.navy,40,100,330,30) end
    screen.marker=Theme.border(tree,Theme.color("ED5666"),1)
    screen.marker:SetRenderTransformPivot({X=0.5,Y=0.5})
    screen.marker:SetRenderTransformAngle(45)
    screen.marker_slot=Theme.place(map_frame,screen.marker,0,0,14,14)
    Theme.badge(map_frame,tree,"Region Map",screen.text_style,12,10,130,30)

    local wire_frame=Theme.card(body,tree,372,263,420,223,C.row)
    Theme.place(wire_frame,Theme.border(tree,C.blueprint,5),7,7,406,209)
    local grid=construct("/Script/UMG.CanvasPanel",tree)
    Theme.place(wire_frame,grid,8,8,404,207)
    grid:SetClipping(1)
    for x=0,404,25 do Theme.line(grid,tree,x,0,x,207,C.grid,0.6) end
    for y=0,207,20 do Theme.line(grid,tree,0,y,404,y,C.grid,0.6) end
    screen.wire_canvas=construct("/Script/UMG.CanvasPanel",tree)
    Theme.place(wire_frame,screen.wire_canvas,8,8,404,207)
    screen.wire_canvas:SetClipping(1)
    screen.wire_empty=Theme.label(wire_frame,tree,"Terrain preview available for installed maps",screen.text_style,16,C.row,42,96,340,55)
    Theme.badge(wire_frame,tree,"Terrain Preview",screen.text_style,12,10,165,30)

    local info=Theme.card(body,tree,806,14,376,472,C.paper)
    screen.detail_title=Theme.label(info,tree,"",screen.heading_style,30,C.navy,28,20,320,44)
    screen.detail_title:SetAutoWrapText(false);screen.detail_title:SetTextOverflowPolicy(1)
    screen.detail_credits=Theme.label(info,tree,"",screen.text_style,14,C.navy,28,67,320,42)
    screen.detail_subtitle=Theme.label(info,tree,"",screen.text_style,14,C.muted,28,111,320,24)
    screen.details_scroll=construct("/Script/UMG.ScrollBox",tree)
    Theme.place(info,screen.details_scroll,28,147,320,108)
    screen.details=Theme.text(tree,"",screen.text_style,16,Theme.color("665F56"))
    screen.details_scroll:AddChild(screen.details)
    Theme.line(info,tree,28,267,348,267,C.edge)
    Theme.icon(info,tree,"mountain",screen.text_style,28,282,22,C.navy)
    screen.terrain_text=Theme.label(info,tree,"",screen.text_style,16,C.navy,64,287,282,28)
    Theme.icon(info,tree,"elevation",screen.text_style,29,317,23,C.navy)
    screen.elevation_text=Theme.label(info,tree,"",screen.text_style,16,C.navy,64,320,282,28)
    Theme.line(info,tree,28,354,348,354,C.edge)
    Theme.label(info,tree,"Map Content",screen.heading_style,16,C.navy,28,369,148,24)
    Theme.label(info,tree,"Difficulty Range",screen.heading_style,16,C.navy,202,369,160,24)
    Theme.line(info,tree,184,372,184,450,C.edge)
    Theme.icon(info,tree,"tree",screen.text_style,28,405,26,C.green)
    screen.trails_text=Theme.label(info,tree,"",screen.text_style,16,C.navy,65,406,113,24)
    Theme.icon(info,tree,"lift",screen.text_style,29,439,24,C.navy)
    screen.lifts_text=Theme.label(info,tree,"",screen.text_style,16,C.navy,65,440,113,24)
    screen.difficulties=construct("/Script/UMG.VerticalBox",tree)
    Theme.place(info,screen.difficulties,202,402,164,66)

    screen.status=Theme.label(body,tree,"",screen.text_style,14,C.muted,26,494,870,28)
    local back=Theme.button(tree,"Back",scenario_button,screen.text_style,C.coral,18,C.navy)
    Theme.place(body,back,24,525,175,51)
    Theme.icon(body,tree,"back",screen.text_style,44,541,21,C.navy)
    bind_button(back,function() show_screen(screen,false);owner:OnCancelClicked() end)
    local options=Theme.button(tree,"Options",scenario_button,screen.text_style,C.row,18,C.navy)
    screen.options_button=options
    Theme.place(body,options,229,525,175,51)
    bind_button(options,function()
        -- Portable terrain keeps its authored dimensions. Native diorama
        -- generation applies to stock maps, so omit that row for Custom Map.
        if valid(owner.MapSizeRow) then owner.MapSizeRow:SetVisibility(1) end
        owner:OnOptionsToggleClicked()
    end)
    local workshop,workshop_text=Theme.button(tree,"Workshop page ↗",scenario_button,screen.text_style,C.row,16,C.navy)
    screen.workshop_button,screen.workshop_text=workshop,workshop_text
    Theme.place(body,workshop,505,525,224,51)
    bind_button(workshop,function()
        local map=screen.selected_index and UI.runtime.selected()
        if map and map.__update then
            screen.play_error=nil
            local accepted,options=pcall(GameOptions.capture,owner)
            if not accepted then screen.play_error=tostring(options);screen.status:SetText(FText(screen.play_error));return end
            UI.runtime.play(map,function(failure)
                UI.refresh()
                screen.play_error=failure
                if failure then screen.status:SetText(FText(failure)) end
            end,true,options)
            return
        end
        if map then UI.runtime.workshop.open(map) end
        screen.status:SetText(FText(UI.runtime.workshop.message))
    end)
    local editor=Theme.button(tree,"Editor",scenario_button,screen.text_style,C.row,18,C.navy)
    screen.editor_button=editor
    Theme.place(body,editor,749,525,157,51)
    bind_button(editor,function()
        local ok,failure=pcall(function()
            if os.getenv("STEAM_COMPAT_DATA_PATH") or os.getenv("WINEPREFIX") then
                -- Dispatch to the Linux desktop directly: Unreal's URL launch
                -- can silently consume custom schemes inside Proton.
                -- The command is fixed and accepts no map/remote input.
                assert(os.execute('start "" C:\\windows\\system32\\winebrowser.exe "skieomod://editor"'),
                    "Could not open Editor; run skieomod setup and try again.")
                return
            end
            local system=require("UEHelpers").GetKismetSystemLibrary()
            assert(system:CanLaunchURL("skieomod://editor"),
                "Install or update skieomod, then run skieomod setup to enable Editor.")
            system:LaunchURL("skieomod://editor")
        end)
        screen.play_error=ok and "Opening the desktop editor…" or tostring(failure)
        screen.status:SetText(FText(screen.play_error))
    end)
    local start,start_text=Theme.button(tree,"Play",scenario_button,screen.heading_style,C.coral,27,C.white)
    screen.start_button,screen.start_text=start,start_text
    Theme.place(body,start,926,521,255,57)
    -- This decorative glyph leaves the whole button available to mouse/gamepad.
    screen.start_icon=Theme.icon(body,tree,"play",screen.text_style,951,536,22,C.white)
    bind_button(start,function()
        local map=screen.selected_index and UI.runtime.selected()
        if not map then return end
        screen.play_error=nil
        local accepted,options=pcall(GameOptions.capture,owner)
        if not accepted then screen.play_error=tostring(options);screen.status:SetText(FText(screen.play_error));return end
        UI.runtime.play(map,function(failure)
            UI.refresh()
            screen.play_error=failure
            if failure then screen.status:SetText(FText(failure)) end
        end,false,options)
        -- Keep Custom Map underneath the loading screen until level travel.
        -- Restoring the native tabs here exposes the classic menu for a frame.
    end)
    show_screen(screen,false)
    rebuild_list(screen)
    UI.pending_views[owner:GetAddress()]=nil
    return screen
end

local function inject(owner)
    if not is_a(owner, "/Script/SkiResortSimulator.NewGameDialogWidget") then
        return
    end
    if UI.screens[owner:GetAddress()] then return end
    local tree = owner.WidgetTree
    if not valid(tree) then return end
    local scenario_text, scenario_button = find_tab(owner, tree, "Scenarios")
    local world_text, world_button = find_tab(owner, tree, "World")
    if not valid(scenario_text) or not valid(scenario_button) then
        UI.runtime.log("New Game dialog found, but the Scenarios tab was not found")
        return
    end
    local tab_panel = scenario_button:GetParent()
    if not valid(tab_panel) then return end
    local root = owner.RootCanvas
    if not valid(root) then root = tree.RootWidget end
    if not is_a(root, "/Script/UMG.PanelWidget") then return end

    local screen = {owner=owner,tree=tree,root=root,visible=false}
    local tabs=construct("/Script/UMG.CanvasPanel",tree)
    screen.tab_view=tabs
    fill_slot(add_child(root,tabs))
    tabs:SetVisibility(4)
    local tab_canvas=Theme.scaled(tabs,tree,0.318,0.256,0.685,0.303,630,44)
    -- Keep the actual native buttons: OnTabClicked relies on their hover state
    -- and TabButtons identity. Moving them preserves mouse/gamepad behaviour.
    for index,tab in ipairs({{button=world_button,text=world_text},{button=scenario_button,text=scenario_text}}) do
        local button=tab.button
        if valid(button) then
            button:RemoveFromParent()
            Theme.place(tab_canvas,button,(index-1)*212,0,204,44)
            Theme.button_style(button,C.row)
        end
        local text=tab.text
        if valid(text) then text:SetColorAndOpacity(Theme.slate(C.navy));text:SetFontSize(18) end
    end
    local custom_button,custom_text=Theme.button(tree,"Custom Map",scenario_button,
        scenario_text,C.row,19,C.navy)
    custom_text:SetAutoWrapText(false)
    Theme.place(tab_canvas,custom_button,424,0,206,44)
    screen.custom_button,screen.custom_text=custom_button,custom_text
    screen.native_tabs={}
    if valid(world_button) then screen.native_tabs[#screen.native_tabs+1]={button=world_button,text=world_text} end
    screen.native_tabs[#screen.native_tabs+1]={button=scenario_button,text=scenario_text}
    UI.screens[owner:GetAddress()] = screen
    bind_button(custom_button, function()
        if not screen.view then
            if screen.build_failed then return end
            local built,failure=pcall(build_screen,owner,tree,root,scenario_button,scenario_text,screen)
            if not built then
                local pending=UI.pending_views[owner:GetAddress()]
                if valid(pending) then pending:RemoveFromParent() end
                UI.pending_views[owner:GetAddress()]=nil
                screen.view,screen.build_failed=nil,true
                custom_button:SetIsEnabled(false)
                UI.runtime.log("Custom UI injection failed: "..tostring(failure))
                return
            end
        else rebuild_list(screen) end
        show_screen(screen, true)
        if UI.runtime.refresh_catalog_if_due then UI.runtime.refresh_catalog_if_due(UI.refresh) end
    end)
    -- Restore the native content on press, before its native click handler
    -- changes World/Scenarios visibility.
    bind_button(scenario_button, function() select_native_tab(screen,scenario_button) end,"OnPressed")
    scenario_button.OnClicked:Add(scenario_button,"SetKeyboardFocus")
    if valid(world_button) then
        bind_button(world_button, function() select_native_tab(screen,world_button) end,"OnPressed")
        world_button.OnClicked:Add(world_button,"SetKeyboardFocus")
    end
    UI.runtime.log("Custom tab added to New Game")
end

local function try_inject(owner)
    if not valid(owner) or UI.failed_screens[owner:GetAddress()] then return end
    local injected,message=pcall(inject,owner)
    if not injected then
        local pending=UI.pending_views[owner:GetAddress()]
        if valid(pending) then pending:RemoveFromParent() end
        UI.pending_views[owner:GetAddress()]=nil
        UI.failed_screens[owner:GetAddress()]=owner
        UI.runtime.log("Custom UI injection failed: "..tostring(message))
    end
end

local function scan_dialogs()
    if not UI.runtime then return false end
    -- Update live state without rebuilding hundreds of widgets while Steam is
    -- downloading. This function already runs on the game thread.
    for _, screen in pairs(UI.screens) do
        if valid(screen.owner) and screen.owner:IsInViewport() then
            update_version_warning(screen)
            local modal=screen.owner.OptionsModalRoot
            local visibility=valid(modal) and modal:GetVisibility() or 1
            local blocked=visibility~=1 and visibility~=2
            if valid(screen.tab_view) then screen.tab_view:SetIsEnabled(not blocked) end
            if valid(screen.view) then screen.view:SetIsEnabled(not blocked) end
        end
        if valid(screen.owner) and valid(screen.start_button) and screen.visible and screen.owner:IsInViewport() then
            if UI.runtime.refresh_catalog_if_due then UI.runtime.refresh_catalog_if_due(UI.refresh) end
            local query=widget_text(screen.search) or ""
            if query~=screen.query then screen.query=query;rebuild_list(screen) end
            local entry=screen.selected_index and UI.runtime.selected()
            local state=item_state(entry)
            local action,enabled=WorkshopView.action(entry,state,catalog_busy())
            screen.start_button:SetIsEnabled(enabled)
            screen.start_text:SetText(FText(action))
            set_visible(screen.start_icon,action=="Play")
            screen.status:SetText(FText(screen.play_error or catalog_message()))
            if entry and entry.__workshop then screen.details:SetText(FText(WorkshopView.details(entry,state))) end
            -- Reuse the retained poll callback; do not allocate a recursive
            -- timer for every wireframe frame or rebuild its UMG children.
            local updated,message=pcall(update_wireframe,screen)
            if not updated then UI.runtime.log("wireframe update failed: "..tostring(message)) end
        end
    end
    local ok, owners = pcall(FindAllOf, "NewGameDialogWidget")
    if ok then
        for _, owner in ipairs(owners or {}) do
            if valid(owner) and not UI.screens[owner:GetAddress()] then
                try_inject(owner)
            end
        end
    elseif owners then
        UI.runtime.log("New Game dialog scan failed: " .. tostring(owners))
    end
    return false
end

function UI.refresh()
    for address, screen in pairs(UI.screens) do
        if valid(screen.owner) and screen.view then
            local ok, message = pcall(rebuild_list, screen)
            if screen.status then screen.status:SetText(FText(catalog_message())) end
            if not ok then UI.runtime.log("Custom panel refresh failed: " .. tostring(message)) end
        elseif not valid(screen.owner) then
            UI.screens[address] = nil
        end
    end
end

function UI.install(runtime)
    UI.runtime = runtime
    GameVersion.poll()
    if UI.hook_installed then return end
    UI.hook_installed = true
    local ok, message = pcall(function()
        require('compatibility').hook('ui.construct',
            "/Script/UMG.UserWidget:Construct",
            'post',
            function(context)
                local owner = context:get()
                UI.runtime.defer(1, function()
                    try_inject(owner)
                end)
            end,{})
        require('compatibility').hook('ui.focus',
            "/Script/UMG.Widget:SetKeyboardFocus",
            'pre',
            function(context)
                local widget = context:get()
                if valid(widget) then
                    local binding = UI.button_actions[widget:GetAddress()]
                    if binding and valid(binding.owner)
                        and binding.owner:GetAddress() == widget:GetAddress() then
                        local action_ok, action_error = pcall(binding.callback)
                        if not action_ok then
                            UI.runtime.log("Custom UI action failed: " .. tostring(action_error))
                        end
                    end
                end
                return nil
            end,{})
    end)
    if not ok then UI.runtime.log("could not install New Game UI hooks: " .. tostring(message)) end

    -- Native UUserWidgets do not consistently dispatch the script Construct
    -- event.  Poll the very small set of New Game dialog instances as the
    -- reliable path, while retaining the hook for Blueprint-derived builds.
    if not UI.poll_started then
        UI.poll_started = true
        -- A recursively rescheduled ExecuteWithDelay creates a fresh Lua
        -- registry reference on every scan. Long sessions eventually leave
        -- UE4SS trying to invoke an invalid reference. Keep one cancellable
        -- delayed action alive for the lifetime of the mod instead.
        UI.poll_callback = scan_dialogs
        if type(LoopInGameThreadWithDelay) == "function" then
            UI.poll_handle = LoopInGameThreadWithDelay(250, UI.poll_callback)
        else
            LoopAsync(250, function()
                ExecuteInGameThread(UI.poll_callback)
                return false
            end)
        end
    end
end

return UI
