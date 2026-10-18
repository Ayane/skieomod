package.path="mod/SkiEO-CustomMaps/Scripts/?.lua;tests/?.lua;"..package.path
local Mock=require("support.umg")
Mock.install()
local world=Mock.object("World")
local controller=Mock.object("PlayerController")
package.preload.UEHelpers=function() return {
    GetWorld=function() return world end,GetPlayerController=function() return controller end,
} end
local widgets,overlays,imports={}, {},0
local slate_only=false
local find=StaticFindObject
StaticFindObject=function(path)
    if path=="/Script/UMG.Default__WidgetBlueprintLibrary" then
        local library=Mock.object("WidgetBlueprintLibrary")
        library.Create=function(_,context,cls)
            if cls.class_name=="/Script/UMG.UserWidget" then
                local overlay=Mock.object("UserWidget")
                overlay.WidgetTree=Mock.object("WidgetTree",overlay)
                overlays[#overlays+1]=overlay
                return overlay
            end
            local widget=Mock.object("LoadingScreenWidget")
            -- Native trees are constructed lazily on AddToViewport.
            widget.AddToViewport=function(self,z)
                self.viewport=true;self.viewport_order=z
                if self.WidgetTree then return end
                self.WidgetTree=Mock.object("WidgetTree",self)
                if slate_only then return end
                self.RootCanvas=Mock.object("CanvasPanel",self.WidgetTree)
                self.CenterStack=Mock.object("VerticalBox",self.WidgetTree)
                self.RootCanvas:AddChild(self.CenterStack)
                for _,name in ipairs({"TitleTextBlock","StageTextBlock","TipBodyBlock","ProgressBar"}) do
                    self[name]=Mock.object(name=="ProgressBar" and "ProgressBar" or "TextBlock",self.WidgetTree)
                    self.CenterStack:AddChild(self[name])
                end
            end
            widgets[#widgets+1]=widget
            return widget
        end
        return library
    elseif path=="/Script/Engine.Default__KismetRenderingLibrary" then
        local rendering=Mock.object("KismetRenderingLibrary")
        rendering.ImportFileAsTexture2D=function(_,context,path)
            assert(context==world)
            local file=assert(io.open(path,"rb"));local bytes=file:read("*a");file:close()
            assert(require("map_presentation").png_header(bytes));imports=imports+1
            return Mock.object("Texture2D")
        end
        return rendering
    end
    return find(path)
end
local map=assert(require("catalog").load("mod/SkiEO-Veymont/custom-map.json"))
local read=map.__read
local reads={}
map.__read=function(path)
    assert(path=="Preview/veymont-loading.png" or path=="Preview/veymont.png","loading card requested unexpected artwork")
    reads[#reads+1]=path
    return read(path)
end
local Loading=require("loading")
Loading.show(map)
assert(Loading.map==map and Loading.title=="Veymont" and Loading.view)
assert(imports==2 and widgets[1].CenterStack:GetVisibility()==1)
assert(reads[1]=='Preview/veymont-loading.png' and reads[2]=='Preview/veymont.png','loading background and card icon reused the same artwork')
local thumbnail_cover=false
for _,box in ipairs(FindAllOf('ScaleBox')) do if box.stretch==5 then
    local image=box:GetChildAt(0)
    local frame=box:GetParent()
    if image and image.class_name=='Image' and frame and frame.Slot
        and frame.Slot.size and frame.Slot.size.X==322 and frame.Slot.size.Y==244 then
        assert(frame.clipping==1 and image.natural,'cover must crop the natural-size image inside its frame')
        thumbnail_cover=true
    end
end end
assert(thumbnail_cover,'the loading thumbnail must fill its frame without letterboxing or distortion')
assert(controller.ignore_move and controller.ignore_look and widgets[1].viewport_order==30000)
Loading.update("Creating forest",0.68)
assert(Loading.view.percent.text=="68%" and Loading.view.stage.text=="Creating forest")
assert(math.abs(Loading.view.fill_slot.size.X-678*0.68)<0.001)
local first_view=Loading.view
Loading.refresh();assert(Loading.view==first_view and imports==2,"progress re-imported the image or rebuilt the card")
local installed={};for key,value in pairs(map) do installed[key]=value end
Loading.show(installed)
assert(#widgets==1 and Loading.widget==widgets[1] and widgets[1].viewport,'download completion recreated the blocking screen')
assert(Loading.map==installed and not first_view.root.parent and imports==4,'verified map artwork did not replace the acquisition card')
Loading.update("Creating forest",0.68)
world=Mock.object("World")
Loading.refresh()
assert(Loading.view~=first_view and imports==6 and not widgets[1].viewport and widgets[2].viewport)
assert(Loading.view.percent.text=="68%","world travel reset actual progress")
Loading.update("Complete",2);assert(Loading.view.percent.text=="100%" and Loading.fraction==1)
Loading.hide();assert(not widgets[2].viewport and not controller.ignore_move and not controller.ignore_look)
assert(Loading.view==nil and Loading.map==nil)
-- Missing/malformed artwork leaves the native background and a usable card.
map.__read=function() return "not a PNG" end
Loading.show(map);assert(Loading.view and imports==6)
Loading.update("Opening",-1);assert(Loading.view.percent.text=="0%")
Loading.hide()
-- CL5545 uses a Slate-only native loading widget, with an empty UMG tree.
-- Build a standard UMG host before showing it, retain progress across travel,
-- and remove both screens when loading ends.
slate_only=true
Loading.show(map)
assert(Loading.overlay==overlays[1] and Loading.view)
assert(Loading.overlay.WidgetTree.RootWidget and Loading.overlay.viewport_order==30001)
local refreshed={};for key,value in pairs(map) do refreshed[key]=value end
Loading.show(refreshed)
assert(Loading.overlay==overlays[1] and #overlays==1,'verified artwork leaked a second Slate host')
Loading.update("Generating station",0.42)
assert(Loading.view.percent.text=="42%")
local old_overlay=Loading.overlay
world=Mock.object("World");Loading.refresh()
assert(not old_overlay.viewport and Loading.overlay==overlays[2])
assert(Loading.view.percent.text=="42%")
local active_overlay=Loading.overlay
Loading.hide()
assert(not active_overlay.viewport and not controller.ignore_move and not controller.ignore_look)
assert(Loading.overlay==nil)
assert(not io.open("mod/SkiEO-CustomMaps/Scripts/ui-preview.tmp.png","rb"),"preview staging file leaked")
print("Loading card: native UMG and Slate-only hosts, portable artwork, real progress, world travel, fallback and input release OK")
