-- Shared UMG primitives for the Custom Map browser and loading card.
-- Colours are authored in sRGB, then converted to Unreal's linear space.
local Theme = {}
local function channel(value)
    value = value / 255
    return value <= 0.04045 and value / 12.92 or ((value + 0.055) / 1.055) ^ 2.4
end
function Theme.color(hex, alpha)
    return {R=channel(tonumber(hex:sub(1,2),16)), G=channel(tonumber(hex:sub(3,4),16)),
        B=channel(tonumber(hex:sub(5,6),16)), A=alpha or 1}
end
Theme.colors = {
    ice=Theme.color("BDD0DF"), paper=Theme.color("F1EDE3"), row=Theme.color("DFE7EE"),
    navy=Theme.color("254B65"), muted=Theme.color("647583"), selected=Theme.color("285A73"),
    coral=Theme.color("C97E6C"), coral_hover=Theme.color("DA927E"), edge=Theme.color("A6BCCB"),
    white=Theme.color("FFFFFF"), wire=Theme.color("76CCE9"), grid=Theme.color("345B70"),
    blueprint=Theme.color("1D3B4D"), green=Theme.color("298A58"), blue=Theme.color("2474B5"),
    red=Theme.color("C75A55"), black=Theme.color("26343D"), shadow=Theme.color("142C3D",0.18),
}
function Theme.valid(object) return object and object:IsValid() end
function Theme.slate(color) return {SpecifiedColor=color, ColorUseRule=0} end
function Theme.construct(name, tree)
    local cls = StaticFindObject("/Script/UMG." .. name)
    assert(Theme.valid(cls), "UMG class is unavailable: " .. name)
    local widget = StaticConstructObject(cls, tree, 0, 0, 0, false, false, nil, 0, 0, 0)
    assert(Theme.valid(widget), "could not construct " .. name)
    return widget
end
function Theme.brush(color, radius, outline)
    return {DrawAs=4, TintColor=Theme.slate(color), ImageSize={X=16,Y=16},
        OutlineSettings={CornerRadii={X=radius or 8,Y=radius or 8,Z=radius or 8,W=radius or 8},
            Color=Theme.slate(outline or color), Width=outline and 1 or 0,
            RoundingType=0, bUseBrushTransparency=not outline}}
end
function Theme.border(tree, color, radius, outline)
    local border = Theme.construct("Border", tree)
    border:SetBrush(Theme.brush(color, radius, outline))
    border:SetBrushColor(Theme.colors.white)
    border:SetPadding({Left=0,Top=0,Right=0,Bottom=0})
    return border
end
function Theme.place(canvas, widget, x, y, width, height)
    local slot = canvas:AddChildToCanvas(widget)
    slot:SetPosition({X=x,Y=y})
    slot:SetSize({X=width,Y=height})
    return slot
end
function Theme.anchor(canvas, widget, left, top, right, bottom)
    local slot = canvas:AddChildToCanvas(widget)
    slot:SetAnchors({Minimum={X=left,Y=top},Maximum={X=right,Y=bottom}})
    slot:SetOffsets({Left=0,Top=0,Right=0,Bottom=0})
    return slot
end
function Theme.text(tree, label, source, size, color)
    local text = Theme.construct("TextBlock", tree)
    if type(source)=="table" and not source.__object and not source.IsValid then
        text.Font=source -- a portable font snapshot retained across level travel
    elseif Theme.valid(source) then text.Font = source.Font end
    text:SetFontSize(size or 16)
    text:SetColorAndOpacity(Theme.slate(color or Theme.colors.navy))
    text:SetJustification(0)
    text:SetAutoWrapText(true)
    text:SetShadowOffset({X=0,Y=0})
    text:SetText(FText(label))
    text:SetVisibility(4) -- decorative children must not intercept button hits
    return text
end
function Theme.label(canvas, tree, label, source, size, color, x, y, width, height)
    local text = Theme.text(tree,label,source,size,color)
    Theme.place(canvas,text,x,y,width,height)
    return text
end
function Theme.button_style(button, color, hover, radius)
    -- Mutate the constructed native style in place.
    local style = button.WidgetStyle
    style.Normal = Theme.brush(color,radius,Theme.colors.edge)
    style.Hovered = Theme.brush(hover or Theme.colors.ice,radius,Theme.colors.navy)
    style.Pressed = Theme.brush(Theme.colors.navy,radius)
    style.Disabled = Theme.brush(Theme.colors.edge,radius)
    style.NormalPadding = {Left=0,Top=0,Right=0,Bottom=0}
    style.PressedPadding = {Left=0,Top=1,Right=0,Bottom=0}
    -- WidgetStyle is a reflected view into the button's own native storage.
    -- Slate already references it. Passing this same view through SetStyle
    -- crashes UE4SS's FButtonStyle parameter copy on the shipped game build.
    -- Update its fields in place, then invalidate paint via the colour setters.
    button:SetBackgroundColor(Theme.colors.white)
    button:SetColorAndOpacity(Theme.colors.white)
end
function Theme.button(tree, label, source_button, source_text, color, size, text_color)
    local button = Theme.construct("Button",tree)
    -- Start with the constructed style rather than copying a native style
    -- containing Slate resource handles through the Lua bridge.
    Theme.button_style(button,color or Theme.colors.row,
        color == Theme.colors.coral and Theme.colors.coral_hover or nil)
    local text = Theme.text(tree,label,source_text,size or 18,text_color)
    text:SetJustification(1)
    local slot = button:AddChild(text)
    slot:SetHorizontalAlignment(2)
    slot:SetVerticalAlignment(2)
    return button,text
end
function Theme.card(canvas,tree,x,y,width,height,color)
    Theme.place(canvas,Theme.border(tree,Theme.colors.shadow,12),x+2,y+3,width,height)
    local border = Theme.border(tree,color or Theme.colors.paper,12,Theme.colors.edge)
    Theme.place(canvas,border,x,y,width,height)
    local content = Theme.construct("CanvasPanel",tree)
    border:AddChild(content)
    return content,border
end
function Theme.scaled(canvas,tree,left,top,right,bottom,width,height)
    local scale = Theme.construct("ScaleBox",tree)
    scale:SetStretch(2) -- EStretch::ScaleToFit preserves proportions.
    Theme.anchor(canvas,scale,left,top,right,bottom)
    local size = Theme.construct("SizeBox",tree)
    size:SetWidthOverride(width); size:SetHeightOverride(height)
    scale:AddChild(size)
    local content = Theme.construct("CanvasPanel",tree)
    size:AddChild(content)
    return content
end
function Theme.line(canvas,tree,x1,y1,x2,y2,color,thickness)
    local line = Theme.border(tree,color,0)
    line:SetVisibility(4)
    local dx,dy=x2-x1,y2-y1
    local length=math.sqrt(dx*dx+dy*dy)
    Theme.place(canvas,line,(x1+x2-length)/2,(y1+y2)/2-(thickness or 1)/2,length,thickness or 1)
    line:SetRenderTransformPivot({X=0.5,Y=0.5})
    line:SetRenderTransformAngle(math.deg(math.atan(dy,dx)))
    return line
end
function Theme.icon(canvas,tree,kind,source,x,y,size,color)
    color=color or Theme.colors.navy
    local icon=Theme.construct("CanvasPanel",tree)
    icon:SetVisibility(4)
    Theme.place(canvas,icon,x,y,size,size)
    local function line(a,b,c,d,t) return Theme.line(icon,tree,a*size,b*size,c*size,d*size,color,t or 2) end
    -- Native fonts omit geometric Unicode glyphs. Draw these icons with
    -- Slate shapes so their appearance does not depend on font coverage.
    local function triangle(cx,top,width,height,fill)
        local rows=math.max(12,math.ceil(height*size))
        for row=0,rows-1 do
            local t=(row+0.5)/rows
            local w=width*size*t
            Theme.place(icon,Theme.border(tree,fill or color,0),cx*size-w/2,
                (top+height*row/rows)*size,w,height*size/rows+0.2)
        end
    end
    if kind=="mountain" then
        triangle(0.35,0.2,0.7,0.74)
        triangle(0.66,0.03,0.72,0.91)
        triangle(0.66,0.03,0.24,0.3,Theme.colors.paper)
    elseif kind=="elevation" then
        line(0.5,0.1,0.5,0.9,3)
        line(0.25,0.33,0.5,0.08,3);line(0.5,0.08,0.75,0.33,3)
        line(0.25,0.67,0.5,0.92,3);line(0.5,0.92,0.75,0.67,3)
    elseif kind=="play" then
        triangle(0.5,0.08,0.84,0.84)
        icon:SetRenderTransformPivot({X=0.5,Y=0.5});icon:SetRenderTransformAngle(90)
    elseif kind=="back" then
        line(0.12,0.5,0.9,0.5,3)
        line(0.12,0.5,0.43,0.19,3);line(0.12,0.5,0.43,0.81,3)
    elseif kind=="expert" then
        local diamond=Theme.border(tree,color,0)
        Theme.place(icon,diamond,size*0.2,size*0.2,size*0.6,size*0.6)
        diamond:SetRenderTransformPivot({X=0.5,Y=0.5});diamond:SetRenderTransformAngle(45)
    elseif kind=="beginner" or kind=="intermediate" or kind=="advanced" then
        Theme.place(icon,Theme.border(tree,color,size/2),size*0.08,size*0.08,size*0.84,size*0.84)
    elseif kind=="search" then
        Theme.place(icon,Theme.border(tree,{R=0,G=0,B=0,A=0},size*0.25,color),0,0,size*0.65,size*0.65)
        line(0.55,0.55,0.88,0.88,2.5)
    elseif kind=="featured" then
        local points={}
        for index=0,9 do
            local angle=-math.pi/2+index*math.pi/5
            local radius=index%2==0 and 0.46 or 0.21
            points[#points+1]={0.5+radius*math.cos(angle),0.5+radius*math.sin(angle)}
        end
        for index,point in ipairs(points) do
            local following=points[index%#points+1]
            line(point[1],point[2],following[1],following[2],2)
        end
    elseif kind=="local" then
        Theme.place(icon,Theme.border(tree,color,2),0,size*0.08,size,size*0.65)
        Theme.place(icon,Theme.border(tree,Theme.colors.row,1),size*0.1,size*0.18,size*0.8,size*0.44)
        line(0.5,0.73,0.5,0.94); line(0.25,0.94,0.75,0.94)
    elseif kind=="tree" then
        triangle(0.5,0.03,0.54,0.38)
        triangle(0.5,0.22,0.72,0.42)
        triangle(0.5,0.44,0.92,0.4)
        line(0.49,0.7,0.49,1,3)
    elseif kind=="lift" then
        line(0.1,0.05,0.9,0.05); line(0.5,0.05,0.5,0.36)
        Theme.place(icon,Theme.border(tree,color,5),size*0.12,size*0.3,size*0.76,size*0.66)
        for i=0,1 do Theme.place(icon,Theme.border(tree,Theme.colors.paper,1),size*(0.24+i*0.3),size*0.44,size*0.2,size*0.28) end
    elseif kind=="workshop" then
        Theme.place(icon,Theme.border(tree,color,size*0.5),0,0,size,size)
        Theme.place(icon,Theme.border(tree,Theme.colors.row,size*0.2),size*0.5,size*0.17,size*0.32,size*0.32)
        line(0.22,0.65,0.6,0.37,3)
        Theme.place(icon,Theme.border(tree,Theme.colors.row,size*0.15),size*0.12,size*0.55,size*0.27,size*0.27)
    elseif kind=="tip" then
        Theme.place(icon,Theme.border(tree,color,size*0.35),size*0.16,0,size*0.7,size*0.72)
        line(0.33,0.83,0.7,0.83,3); line(0.36,0.95,0.66,0.95,3)
    end
    return icon
end
return Theme
