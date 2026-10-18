package.path="mod/SkiEO-CustomMaps/Scripts/?.lua;tests/?.lua;"..package.path
local Mock=require("support.umg")
Mock.install()
local function new_dialog()
    local owner=Mock.object("NewGameDialogWidget")
    owner.viewport=true
    local tree=Mock.object("WidgetTree",owner)
    owner.WidgetTree=tree
    owner.RootCanvas=Mock.object("CanvasPanel",tree);tree.RootWidget=owner.RootCanvas
    local native=Mock.object("CanvasPanel",tree);owner.RootCanvas:AddChild(native)
    local band=Mock.object("Border",tree);owner.RootCanvas:AddChild(band)
    local tabs=Mock.object("HorizontalBox",tree);native:AddChild(tabs)
    owner.TabTexts,owner.TabButtons={},{}
    for _,name in ipairs({"World","Scenarios"}) do
        local button=Mock.object("Button",tree);tabs:AddChild(button)
        local text=Mock.object("TextBlock",tree);text:SetText(name);button:AddChild(text)
        owner.TabTexts[#owner.TabTexts+1]=text;owner.TabButtons[#owner.TabButtons+1]=button
    end
    owner.KeyTitleText=Mock.object("TextBlock",tree)
    owner.DescriptionText=Mock.object("TextBlock",tree)
    owner.NameInput=Mock.object("EditableTextBox",tree)
    owner.WorldSheetTexture=Mock.object("Texture2D")
    owner.OnCancelClicked=function(self) self.cancelled=true end
    return owner,native,band,tabs
end
local owner,native,band,tabs=new_dialog()
local maps={
    {id="local.alpine",metadata={name="Alpine Playground",version="1.0.0",authors={"A"},description="A quiet valley",tags={"Alps"}},terrain={size_meters={1000,2000},elevation_meters={400,1200},preview={samples={{0,0,0},{0,1,0},{0,0,0}}}},location={label="Gresse-en-Vercors",latitude=44,longitude=5}},
    {id="local.nordic",metadata={name="Nordic Valley",version="1.0.0",authors={"B"},description="Forests and powder"},terrain={size_meters={2000,2000},elevation_meters={300,800}}},
    {id="workshop.remote",metadata={name="Untrusted local name",description=""},__unavailable=true,__workshop={published_file_id="123",title="Steam Mountain",description="Steam description"}},
}
local runtime={maps=maps,selected_index=1,browse_kind="map",log=function(message)
    assert(not message:find("failed",1,true),message)
end,
    workshop={message="",state=function() return {} end,open=function() end}}
runtime.browse_items=function() return runtime.browse_kind=="mod" and {} or runtime.maps end
runtime.selected=function() return runtime.selected_index and runtime.browse_items()[runtime.selected_index] end
local refreshes=0
runtime.refresh_workshop=function() refreshes=refreshes+1;return false end
runtime.dependency_status=function() return true end
runtime.start=function(map) runtime.started=map;return true end
runtime.play=function(map,callback) runtime.start(map);callback();return true end
local UI=require("ui")
local editor_urls={}
local can_launch=true
package.preload.UEHelpers=function() return {GetKismetSystemLibrary=function() return {
    CanLaunchURL=function(_,url) assert(url=='skieomod://editor');return can_launch end,
    LaunchURL=function(_,url) editor_urls[#editor_urls+1]=url end,
} end} end
UI.install(runtime);Mock.loop()
local screen=assert(UI.screens[owner:GetAddress()])
assert(not screen.visible and not screen.view and screen.custom_button.enabled)
assert(owner.TabButtons[1]:GetParent()~=tabs,"native tabs were not moved into the shared strip")
local tab_objects=#Mock.objects
UI.refresh();assert(#Mock.objects==tab_objects,'hidden Custom Map built its previews before opening')
Mock.emit(screen.custom_button,"OnClicked")
assert(#screen.rows==3 and screen.detail_title.text=="Alpine Playground")
assert(screen.terrain_text.text=="Terrain: 1.00 × 2.00 km")
assert(refreshes==0,'opening Custom Map contacted the network')
assert(screen.visible and native:GetVisibility()==1 and band:GetVisibility()==1)
Mock.emit(screen.editor_button,'OnClicked')
assert(#editor_urls==1 and editor_urls[1]=='skieomod://editor' and not runtime.started)
assert(screen.visible and screen.status.text=='Opening the desktop editor…')
can_launch=false
Mock.emit(screen.editor_button,'OnClicked');Mock.loop()
assert(#editor_urls==1 and screen.status.text:find('skieomod setup',1,true))
local getenv,execute=os.getenv,os.execute
local editor_commands={}
os.getenv=function(key) return key=='STEAM_COMPAT_DATA_PATH' and '/test/proton' or nil end
os.execute=function(command) editor_commands[#editor_commands+1]=command;return true,'exit',0 end
Mock.emit(screen.editor_button,'OnClicked')
assert(#editor_urls==1 and #editor_commands==1)
assert(editor_commands[1]=='start "" C:\\windows\\system32\\winebrowser.exe "skieomod://editor"')
assert(screen.status.text=='Opening the desktop editor…')
os.execute=function() return nil,'exit',1 end
Mock.emit(screen.editor_button,'OnClicked');Mock.loop()
assert(screen.status.text:find('skieomod setup',1,true) and screen.visible and not runtime.started)
os.getenv,os.execute=getenv,execute
screen.play_error=nil;can_launch=true
assert(screen.tab_view:GetVisibility()==4,"the tab strip became hidden with native content")
screen.search:SetText("Nordic");Mock.loop()
assert(#screen.rows==1 and runtime.selected_index==2 and screen.selected_index==2)
assert(screen.detail_title.text=="Nordic Valley" and screen.marker:GetVisibility()==1)
screen.search:SetText("unknown map");Mock.loop()
assert(#screen.rows==0 and not screen.start_button.enabled and runtime.selected_index==nil)
Mock.emit(screen.start_button,"OnClicked")
assert(not runtime.started,"an empty search launched a stale selection")
screen.search:SetText("");Mock.loop()
assert(#screen.rows==3 and runtime.selected_index==1)
local previous=screen.rows[2].button:GetAddress()
screen.search:SetText("powder");Mock.loop()
assert(not UI.button_actions[previous],"a rebuilt list retained old button callbacks")
screen.search:SetText("Steam");Mock.loop()
assert(screen.detail_title.text=="Steam Mountain" and screen.start_text.text=="Subscribe")
assert(screen.wire_empty:GetVisibility()==0 and screen.trails_text.text=="— trails")
assert(#screen.wire_lines==0 and screen.workshop_button:GetVisibility()==0)
Mock.emit(owner.TabButtons[2],"OnPressed")
assert(not screen.visible and native:GetVisibility()==0 and band:GetVisibility()==0)
Mock.emit(screen.custom_button,"OnClicked")
runtime.workshop.busy=true;Mock.loop()
assert(screen.start_button.enabled and screen.rows[1].button.enabled,'refresh locked browsing or Play')
runtime.workshop.busy=false
screen.search:SetText("Alpine");Mock.loop()
Mock.emit(screen.start_button,"OnClicked")
assert(runtime.started==maps[1] and screen.visible and native:GetVisibility()==1,'Play uncovered the classic menu')
Mock.emit(screen.custom_button,"OnClicked")
local back
for _,object in ipairs(Mock.objects) do
    if object.class_name=="TextBlock" and object.text=="Back" then back=object:GetParent() end
end
Mock.emit(assert(back),"OnClicked")
assert(owner.cancelled and not screen.visible,"Back did not close New Game")
local count=#Mock.objects;UI.refresh()
assert(#Mock.objects>count and #screen.rows==1)
-- Featured uses the same loading flow as every other map, without exposing
-- the classic menu during acquisition or after a failed download.
maps[1].__featured=true
local installs=0
runtime.play=function(map,callback)
    installs=installs+1;callback(nil);return true
end
UI.refresh()
assert(screen.rows[1].title.text:find("[Featured]",1,true))
Mock.emit(screen.custom_button,"OnClicked")
runtime.started=nil
Mock.emit(screen.start_button,"OnClicked")
assert(installs==1 and screen.visible)
runtime.play=function(map,callback) installs=installs+1;callback("offline");return true end
Mock.emit(screen.custom_button,"OnClicked")
runtime.started=nil
Mock.emit(screen.start_button,"OnClicked")
assert(installs==2 and not runtime.started and screen.visible,"a failed Featured download launched the map")
Mock.loop();assert(screen.status.text=='offline','catalogue polling erased the download error')
maps[1].__update={}
UI.refresh()
assert(screen.workshop_button:GetVisibility()==0 and screen.workshop_text.text=='Update map')
runtime.play=function(map,callback,update)
    assert(map==maps[1] and update,'Update map used normal Play')
    installs=installs+1;callback();return true
end
Mock.emit(screen.workshop_button,'OnClicked');assert(installs==3)
-- Source filters combine with the live text search without changing row indices.
screen.search:SetText("");Mock.loop()
maps[1].__read=function() return "" end
maps[2].__read=function() return "" end
maps[1].__web=true
Mock.emit(screen.source_buttons["local"],"OnClicked");assert(#screen.rows==2)
Mock.emit(screen.source_buttons.web,"OnClicked");assert(#screen.rows==1 and screen.rows[1].index==1)
screen.search:SetText("Nordic");Mock.loop();assert(#screen.rows==0 and not screen.start_button.enabled)
Mock.emit(screen.source_buttons.all,"OnClicked");assert(#screen.rows==1 and screen.rows[1].index==2)
screen.search:SetText("Alpine");Mock.loop()
-- Closing and reopening native dialogs must not hide content restored above.
Mock.loop();assert(UI.screens[owner:GetAddress()]==screen)
print("Custom Map UMG: native tabs, filtering, selection, Workshop states, empty results, Back and Play OK")
-- A fresh install starts with actual Featured placeholders, whose location
-- contains only a label until the catalogue or map has been downloaded.
local repository=package.loaded.repository
package.loaded.repository={remote={},initialize=function() end,entries=function() return {} end}
local featured=require('featured').merge({})
package.loaded.repository=repository
local previous_maps,previous_index=runtime.maps,runtime.selected_index
runtime.maps,runtime.selected_index=featured,1
local fresh=new_dialog()
Mock.loop()
local cold=assert(UI.screens[fresh:GetAddress()])
assert(cold.custom_button.enabled,'fresh installation lost its Custom Map tab')
Mock.emit(cold.custom_button,'OnClicked')
assert(cold.visible and cold.view and #cold.rows==2 and cold.start_button.enabled)
assert(cold.marker:GetVisibility()==1,'a place label alone must not place a world-map marker')
assert(cold.detail_title.text==featured[1].metadata.name)
Mock.emit(cold.rows[2].button,'OnClicked')
assert(cold.detail_title.text==featured[2].metadata.name and cold.marker:GetVisibility()==1)
-- Coordinates may arrive later. Use complete UV or WGS84 pairs; incomplete
-- or malformed remote data must leave the picker usable and hide the marker.
local entry=runtime.selected()
entry.location={label='Equator',latitude=0,longitude=0}
UI.refresh()
assert(cold.marker:GetVisibility()==0)
assert(cold.marker_slot.anchors.Minimum.X==0.5 and cold.marker_slot.anchors.Minimum.Y==0.5)
entry.location={label='Custom position',world_map_uv={0.75,0.25}}
UI.refresh()
assert(cold.marker:GetVisibility()==0)
assert(math.abs(cold.marker_slot.anchors.Minimum.X-0.74)<1e-9)
assert(math.abs(cold.marker_slot.anchors.Minimum.Y-0.275)<1e-9)
for _,location in ipairs({{label='Only longitude',longitude=5},
    {label='Only latitude',latitude=44},{label='Partial UV',world_map_uv={0.2}},
    {label='Invalid UV',world_map_uv={'east',0.3}},
    {label='Outside UV',world_map_uv={1.1,0.3}},
    {label='Invalid coordinates',latitude='north',longitude=5},
    {label='Outside WGS84',latitude=91,longitude=5}}) do
    entry.location=location;UI.refresh()
    assert(cold.marker:GetVisibility()==1 and cold.custom_button.enabled and cold.start_button.enabled,
        'incomplete location broke map browsing: '..location.label)
end
runtime.maps,runtime.selected_index=previous_maps,previous_index
fresh.invalid=true;UI.refresh()
print('Custom Map UMG: fresh Featured-only installation, label-only locations and later coordinates OK')
-- A failed construction leaves the native root untouched and is logged once.
local second=Mock.object('NewGameDialogWidget')
second.WidgetTree=Mock.object('WidgetTree',second)
second.RootCanvas=Mock.object('CanvasPanel',second.WidgetTree)
second.WidgetTree.RootWidget=second.RootCanvas
local second_tabs=Mock.object('HorizontalBox',second.WidgetTree)
second.RootCanvas:AddChild(second_tabs)
second.TabTexts,second.TabButtons={},{}
for _,name in ipairs({'World','Scenarios'}) do
    local button=Mock.object('Button',second.WidgetTree);second_tabs:AddChild(button)
    local text=Mock.object('TextBlock',second.WidgetTree);text:SetText(name);button:AddChild(text)
    second.TabTexts[#second.TabTexts+1]=text;second.TabButtons[#second.TabButtons+1]=button
end
local lookup=StaticFindObject
StaticFindObject=function(path) if path=='/Script/UMG.Border' then return nil end;return lookup(path) end
local failures=0
runtime.log=function(message) if message:find('injection failed',1,true) then failures=failures+1 end end
Mock.loop();local failed_count=#Mock.objects
Mock.loop()
local shell=assert(UI.screens[second:GetAddress()])
Mock.emit(shell.custom_button,'OnClicked')
failed_count=#Mock.objects
Mock.emit(shell.custom_button,'OnClicked');Mock.loop()
assert(failures==1 and #Mock.objects==failed_count,'failed construction was retried indefinitely')
assert(not shell.view and not shell.visible and not shell.custom_button.enabled)
assert(second.RootCanvas:GetChildrenCount()==2,'an incomplete interface was attached')
assert(second.TabButtons[1]:GetParent() and second_tabs:GetVisibility()==0,'failed construction lost native tabs')
StaticFindObject=lookup
print('Custom Map UMG: failed construction preserves native menu and stops retries OK')
