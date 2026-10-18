-- Presentation only. loading.lua remains responsible for world travel,
-- input blocking, real progress and the initialization watchdog.
local Theme=require("ui_theme")
local Assets=require("ui_assets")
local Presentation=require("map_presentation")
local C=Theme.colors
local View={}

function View.build(widget,map,world,title,logo,fonts)
    local tree=widget.WidgetTree
    if not Theme.valid(tree) then return nil end
    local root=widget.RootCanvas
    if not Theme.valid(root) then root=tree.RootWidget end
    if not Theme.valid(root) then
        root=Theme.construct("CanvasPanel",tree)
        tree.RootWidget=root
    end
    local heading=fonts and fonts.heading or widget.TitleTextBlock
    local body=fonts and fonts.body or widget.StageTextBlock
    local view=Theme.construct("CanvasPanel",tree)
    local card=Presentation.card(map)
    if not map then card.title=title end
    local texture=Assets.preview(map,world,"loading")
    local thumbnail=Assets.preview(map,world,"thumbnail") or texture
    if texture then Assets.picture(view,tree,texture) end
    -- The native screen already supplies a background when no portable image
    -- exists. An opaque canvas covers gameplay but leaves that artwork visible.
    local content=Theme.scaled(view,tree,0.032,0.228,0.537,0.909,840,620)
    local panel=Theme.card(content,tree,0,0,840,620,C.ice)
    local info=Theme.card(panel,tree,15,16,810,383,C.paper)
    if not Assets.picture(info,tree,thumbnail,22,20,322,244) then
        Theme.place(info,Theme.border(tree,C.ice,8),22,20,322,244)
        Theme.icon(info,tree,"mountain",body,130,70,96,C.navy)
        Theme.label(info,tree,"Custom Map",body,22,C.navy,86,190,240,38)
    end
    Theme.label(info,tree,card.title,heading,38,C.navy,376,23,410,57)
    Theme.label(info,tree,"Custom Map · "..(card.location or ""),body,19,C.navy,376,85,407,43)
    Theme.line(info,tree,376,132,786,132,C.edge)
    local description=Theme.construct("ScrollBox",tree)
    Theme.place(info,description,376,147,408,121)
    description:AddChild(Theme.text(tree,card.description,body,19,C.navy))
    Theme.line(info,tree,22,284,786,284,C.edge)
    local stats={
        {x=24,width=205,icon="mountain",label="Terrain",value=card.terrain},
        {x=254,width=205,icon="elevation",label="Elevation",value=card.elevation},
        {x=482,width=150,icon="tree",label=card.trails,value="trails",color=C.green},
        {x=664,width=140,icon="lift",label=card.lifts,value="lifts"},
    }
    for index,stat in ipairs(stats) do
        Theme.icon(info,tree,stat.icon,body,stat.x,310,38,stat.color or C.navy)
        Theme.label(info,tree,stat.label,body,18,C.navy,stat.x+58,307,stat.width-52,28)
        Theme.label(info,tree,stat.value,body,18,C.navy,stat.x+58,336,stat.width-52,30)
        if index<4 then Theme.line(info,tree,stat.x+stat.width+8,303,stat.x+stat.width+8,367,C.edge) end
    end
    local tip=Theme.card(panel,tree,15,414,810,92,C.row)
    Theme.icon(tip,tree,"tip",body,28,23,40,C.navy)
    Theme.label(tip,tree,"Tip: Custom maps may use local assets\nand longer first-load times.",body,20,C.navy,105,21,672,66)
    local progress=Theme.card(panel,tree,15,520,810,61,C.paper)
    local track=Theme.border(tree,Theme.color("B9C5CF"),10)
    Theme.place(progress,track,10,7,678,47)
    local bar=Theme.construct("CanvasPanel",tree)
    track:AddChild(bar)
    track:SetClipping(1)
    local fill=Theme.border(tree,C.coral,8)
    local fill_slot=Theme.place(bar,fill,0,0,0,47)
    local stage=Theme.label(bar,tree,"Loading…",body,21,C.white,18,10,638,35)
    stage:SetAutoWrapText(false);stage:SetTextOverflowPolicy(1)
    local percent=Theme.label(progress,tree,"0%",body,24,C.navy,711,13,89,35)
    Theme.icon(panel,tree,"tree",body,190,593,23,C.navy)
    Theme.label(panel,tree,"MOUNTAINS ARE A STATE OF MIND",body,13,C.navy,241,594,436,25)
    Theme.icon(panel,tree,"tree",body,679,593,23,C.navy)
    if Theme.valid(logo) then
        local brand=Theme.scaled(view,tree,0.046,0.055,0.226,0.184,300,120)
        local image=Theme.construct("Image",tree)
        image:SetBrushFromTexture(logo,true)
        local fit=Theme.construct("ScaleBox",tree)
        fit:SetStretch(2)
        Theme.place(brand,fit,0,0,300,120)
        fit:AddChild(image)
    end
    local slot=root:AddChildToCanvas(view)
    slot:SetAnchors({Minimum={X=0,Y=0},Maximum={X=1,Y=1}})
    slot:SetOffsets({Left=0,Top=0,Right=0,Bottom=0})
    slot:SetZOrder(10)
    if Theme.valid(widget.CenterStack) then widget.CenterStack:SetVisibility(1) end
    if texture and Theme.valid(widget.BackgroundOverlay) then widget.BackgroundOverlay:SetVisibility(1) end
    return {root=view,stage=stage,percent=percent,fill_slot=fill_slot}
end

function View.update(view,stage,fraction)
    if not view or not Theme.valid(view.root) then return end
    view.fill_slot:SetSize({X=678*fraction,Y=47})
    view.stage:SetText(FText(stage))
    view.percent:SetText(FText(string.format("%d%%",math.floor(fraction*100))))
end
return View
