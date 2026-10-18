-- Small reflected UMG double. Unknown methods fail so API mistakes cannot
-- disappear behind a permissive mock. Struct assignment copies like Unreal.
local Mock={objects={},hooks={},next_address=0}
local Methods={}
local function copy(value)
    if type(value)~="table" or value.__object then return value end
    local result={};for key,item in pairs(value) do result[key]=copy(item) end
    return setmetatable(result,getmetatable(value))
end
local STRUCTS={Font=true,WidgetStyle=true,Background=true,Brush=true}
function Mock.object(name,outer)
    Mock.next_address=Mock.next_address+1
    local data={__object=true,class_name=name,outer=outer,address=Mock.next_address,
        children={},visibility=0,enabled=true,Font={Size=16},WidgetStyle={Font={Size=16}},Brush={}}
    if name=="EditableTextBox" then
        data.WidgetStyle=setmetatable({TextStyle={Font={Size=16}}},{__newindex=function(self,key,value)
            assert(key~="Font","EditableTextBoxStyle stores Font in TextStyle")
            rawset(self,key,value)
        end})
    end
    local object=setmetatable({}, {
        __index=function(_,key) if data[key]~=nil then return data[key] end;return Methods[key] end,
        __newindex=function(_,key,value) if (name=="EditableTextBox" or name=="Button") and key=="WidgetStyle" then
                error("whole Slate widget style assignment cannot be marshalled")
            end
            data[key]=STRUCTS[key] and copy(value) or value end,
    })
    for _,event in ipairs({"OnClicked","OnPressed"}) do
        data[event]={bindings={}}
        data[event].Add=function(self,target,method) self.bindings[#self.bindings+1]={target,method} end
    end
    Mock.objects[#Mock.objects+1]=object
    return object
end
function Methods:IsValid() return not self.invalid end
function Methods:GetAddress() return self.address end
function Methods:GetOuter() return self.outer end
function Methods:GetParent() return self.parent end
function Methods:IsA(cls)
    local name=cls.class_name:match("[^.]+$")
    if name==self.class_name then return true end
    return name=="PanelWidget" and ({CanvasPanel=true,VerticalBox=true,HorizontalBox=true,Border=true,ScrollBox=true})[self.class_name] or false
end
function Methods:AddChild(child)
    assert(not child.parent,"UMG child was added without removing its old parent")
    self.children[#self.children+1]=child;child.parent=self
    local kind=self.class_name=="CanvasPanel" and "CanvasPanelSlot" or self.class_name.."Slot"
    child.Slot=Mock.object(kind,self)
    return child.Slot
end
Methods.AddChildToCanvas=Methods.AddChild
function Methods:RemoveFromParent()
    if self.parent then
        for index,child in ipairs(self.parent.children) do if child==self then table.remove(self.parent.children,index);break end end
        self.parent=nil
    end
    self.viewport=false
end
function Methods:ClearChildren() for _,child in ipairs(self.children) do child.parent=nil end;self.children={} end
function Methods:GetChildrenCount() return #self.children end
function Methods:GetChildAt(index) return self.children[index+1] end
function Methods:GetVisibility() return self.visibility end
function Methods:SetVisibility(value) self.visibility=value end
function Methods:SetIsEnabled(value) self.enabled=value end
function Methods:SetText(text) self.text=text end
function Methods:GetText() return {ToString=function() return self.text or "" end} end
function Methods:SetHintText(text) self.hint=text end
function Methods:SetFontSize(size) self.Font.Size=size end
function Methods:SetStyle(style)
    assert(style~=self.WidgetStyle,"SetStyle cannot marshal the button's own reflected style")
    self.WidgetStyle=style
end
function Methods:SetBrush(brush) self.Brush=brush end
function Methods:SetBrushFromTexture(texture,natural) self.Brush={ResourceObject=texture};self.natural=natural end
function Methods:SetPosition(value) self.position=copy(value) end
function Methods:SetSize(value) self.size=copy(value) end
function Methods:SetAnchors(value) self.anchors=copy(value) end
function Methods:SetOffsets(value) self.offsets=copy(value) end
function Methods:SetAlignment(value) self.alignment=copy(value) end
function Methods:SetZOrder(value) self.z_order=value end
function Methods:SetHorizontalAlignment(value) self.horizontal_alignment=value end
function Methods:SetVerticalAlignment(value) self.vertical_alignment=value end
function Methods:SetPadding(value) self.padding=copy(value) end
function Methods:SetBrushColor(value) self.brush_color=copy(value) end
function Methods:SetColorAndOpacity(value) self.color=copy(value) end
function Methods:SetBackgroundColor(value) self.background_color=copy(value) end
function Methods:SetForegroundColor(value) self.foreground_color=copy(value) end
function Methods:SetRenderTransformPivot(value) self.pivot=copy(value) end
function Methods:SetRenderTransformAngle(value) self.angle=value end
function Methods:SetWidthOverride(value) self.width=value end
function Methods:SetHeightOverride(value) self.height=value end
function Methods:SetClipping(value) self.clipping=value end
function Methods:SetStretch(value) self.stretch=value end
function Methods:SetAutoWrapText(value) self.wrap=value end
function Methods:SetTextOverflowPolicy(value) self.overflow=value end
function Methods:SetJustification(value) self.justification=value end
function Methods:SetShadowOffset(value) self.shadow=copy(value) end
function Methods:ScrollToStart() self.scroll_offset=0 end
function Methods:SetPercent(value) self.percent=value end
function Methods:SetIsMarquee(value) self.marquee=value end
function Methods:SetFillColorAndOpacity(value) self.fill_color=copy(value) end
function Methods:IsInViewport() return self.viewport end
function Methods:AddToViewport(z) self.viewport=true;self.viewport_order=z end
function Methods:SetIgnoreMoveInput(value) self.ignore_move=value end
function Methods:SetIgnoreLookInput(value) self.ignore_look=value end
function Mock.emit(object,event)
    for _,binding in ipairs(object[event].bindings) do
        local hook=Mock.hooks["/Script/UMG.Widget:"..binding[2]]
        assert(hook,"no hook for event method "..binding[2])
        hook({get=function() return binding[1] end})
    end
end
function Mock.install()
    FText=function(value) assert(type(value)=="string");return value end
    StaticFindObject=function(path)
        if path=='/Script/UMG.UserWidget:Construct' or path=='/Script/UMG.Widget:SetKeyboardFocus' then
            return dofile('tests/support/reflection.lua').func({})
        end
        return Mock.object(path)
    end
    StaticConstructObject=function(cls,outer) return Mock.object(cls.class_name:match("[^.]+$"),outer) end
    FindAllOf=function(name)
        local result={};for _,object in ipairs(Mock.objects) do if object.class_name==name then result[#result+1]=object end end;return result
    end
    RegisterHook=function(path,pre,post) Mock.hooks[path]=post or pre end
    ExecuteInGameThread=function(callback) callback() end
    LoopInGameThreadWithDelay=function(_,callback) Mock.loop=callback;return 1 end
end
return Mock
