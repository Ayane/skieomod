package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local sequence,removed,hooks,commands=0,0,{},{}
local session,focused
local function object(extra)
    sequence=sequence+1;local id=sequence;local o=extra or {}
    o.IsValid=function()return true end;o.GetAddress=function()return id end
    o.SetVisibility=function(self,value)self.visibility=value end
    o.SetText=function(self,value)self.text=value end
    o.IsHovered=function(self)return self.hovered or false end
    o.IsInViewport=function(self)return self.viewport or false end
    o.IsVisible=function(self)return self.visibility~=1 end
    o.AddToViewport=function(self)self.viewport=true end
    o.RemoveFromParent=function(self)self.viewport=false;removed=removed+1 end
    o.AddChild=function()return object()end
    o.AddChildToCanvas=function()return {LayoutData={Anchors={Minimum={},Maximum={}}},
        SetAnchors=function()error('unsafe nested native anchors copy')end,
        SetPosition=function()end,SetSize=function()end,SetZOrder=function()end}end
    o.OnClicked={Add=function()end}
    return o
end
local release,escape,ray,covered=false,false,{X=0,Y=0,Z=-1},false
local pc=object({CurrentMode=0,
    WasInputKeyJustPressed=function()return escape end,
    WasInputKeyJustReleased=function()return release end,
    DeprojectMousePositionToWorld=function(_,o,d)o.X,o.Y,o.Z=0,0,10;d.X,d.Y,d.Z=ray.X,ray.Y,ray.Z;return true end,
    GetHitResultUnderCursorByChannel=function()error('unsafe native object-handle output was used')end})
local now=0
pc.DeprojectScreenPositionToWorld=function(self,x,y,o,d)
    assert(x==640 and y==360,'QA screen coordinates changed')
    return self:DeprojectMousePositionToWorld(o,d)
end
local input
package.preload.map_input=function()return {bind_pointer=function(_,callback)input=callback end}end
package.preload.UEHelpers=function()return {GetPlayerController=function()return pc end,GetWorld=function()return object()end,
    FindOrAddFName=function(name)return name end,GetGameplayStatics=function()return {GetRealTimeSeconds=function()return now end}end}end
package.preload.ui_theme=function()return {colors={white={},ice={}},color=function()return {}end,
 construct=function()return object()end,border=function()return object()end,label=function()return object()end,
 place=function()end,button=function()return object()end}end
StaticFindObject=function(path)
 if path=='/Script/UMG.Widget:SetKeyboardFocus' then return dofile('tests/support/reflection.lua').func({}) end
 return object({Create=function()return object({WidgetTree=object()})end})
end
local host=object({viewport=true,WidgetTree=object(),RootCanvas=object()})
FindAllOf=function(class)assert(class=='EventMarkerLayerWidget');return {host}end
RegisterHook=function(name,callback)hooks[name]=callback end
RegisterConsoleCommandHandler=function(name,callback)commands[name]=callback end
ExecuteInGameThread=function(callback)callback()end
package.preload.map_entities=function()return {focus_camera=function(api,x,y,z,distance)
    assert(api==session and x==0 and y==0 and z==35 and distance==500);focused=true
end}end
FText=function(text)return text end
local S=require('entity_selection')
S.install(function()return session end);S.install()
local verts={{X=-2,Y=-2,Z=0},{X=2,Y=-2,Z=0},{X=0,Y=2,Z=0}}
assert(S.hit(verts,{0,1,2},{X=0,Y=0,Z=10},{X=0,Y=0,Z=-1})==10)
assert(not S.hit(verts,{0,1,2},{X=5,Y=0,Z=10},{X=0,Y=0,Z=-1}),'off-mesh click hit the animal box')
assert(not S.hit(verts,{0,1,2},{X=0,Y=0,Z=10},{X=0,Y=0,Z=1}),'mesh behind camera was selectable')
assert(not S.hit(verts,{0,1,2},{X=0,Y=0,Z=10},{X=0,Y=0,Z=-1},5),'occlusion distance ignored')
assert(not pcall(S.describe,function()return {title='Fox',properties={{label='Activity',value={}}}}end),'non-text inspection value accepted')
assert(not pcall(S.describe,function()return {title=string.rep('x',100)}end),'unbounded title accepted')
local ticking;session={_cleanups={},log=function()end,every=function(_,ms,callback,frame)assert(ms==16 and frame);ticking=callback end}
local activity='Listening';local highlighted=false
local function attach(z)
 S.attach({_session=session},{provider=function()return {title='Fox',subtitle='Vulpes vulpes',properties={{label='Activity',value=activity}}}end,
  pose=function()return verts,{0,1,2},{x=0,y=0,z=z,yaw=0,pitch=0}end,
  surface=function()return {inside=true,z=covered and 20 or 0}end,
  highlight=function(value)highlighted=value end})
end
attach(-2);attach(0)
local function click()input('click')end
release=true;click();assert(not session._entity_selection.selected,'selection ran before loading')
session._loading_success=true;click()
local state=session._entity_selection
assert(state.selected==state.entries[2] and highlighted,'did not select the nearest visible mesh')
assert(state.title.text=='Fox' and state.properties[1].text=='Activity : Listening','inspection fields did not render')
release=false;now=1;activity='Running';ticking()
assert(state.properties[1].text=='Activity : Running','selected information did not follow current behaviour')
state.card.hovered=true;release=true;ray.X=5;click();assert(state.selected,'panel click dismissed the inspection through the UI')
state.card.hovered=false;release=true;click();assert(not state.selected and not highlighted,'outside click retained the selected animal')
ray.X=0;covered=true;click();assert(not state.selected,'a fox hidden under snow/terrain was selected')
covered=false;pc.CurrentMode=2;click();assert(not state.selected,'building-tool input selected an animal')
pc.CurrentMode=0;click();assert(state.selected,'visible fox could not be reselected')
S.tick(state,true,{x=640,y=360});assert(state.selected,'engine-side QA pick did not use the same selection path')
commands.custommap_test_entity(nil,{'focus','2'});assert(focused,'QA focus did not target the displayed pose')
commands.custommap_test_entity(nil,{'select','640','360'});assert(state.selected,'QA console selection did not open the panel')
commands.custommap_test_entity(nil,{'close'});assert(not state.selected,'QA console close retained the selection')
click()
input('close');assert(not state.selected,'Escape did not close the animal panel')
click();assert(state.selected)
hooks['/Script/UMG.Widget:SetKeyboardFocus']({get=function()return state.button end})
assert(not state.selected,'close button did not close the inspection')
for _,cleanup in ipairs(session._cleanups) do cleanup() end
assert(removed==1 and next(S.actions)==nil and #state.entries==0,'map unload retained its panel/actions/selection entries')
assert(host.viewport,'map unload removed the native HUD')
print('Entity selection: visible mesh picking, nearest animal, scenery/UI/tool guards, light live information, close/Escape and map-owned cleanup OK')
