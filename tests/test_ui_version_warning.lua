package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Version=require('game_version')
local screen={browser_body={Slot={}},browser_size={height=590}}
local attached,layout_ready=false,false
local function observe()
    local frame=screen.version_warning
    if attached and (frame.visibility==0 or frame.visibility==4) then
        assert(screen.version_warning_title.text~='' and screen.version_warning_detail.text~='',
            'visible empty warning frame')
        assert(layout_ready,'warning exposed before text layout completed')
        assert(screen.browser_body.y==112 and screen.browser_size.height==702,'warning overlaps browser')
    end
end
screen.browser_body.Slot.SetPosition=function(_,position)screen.browser_body.y=position.Y;observe()end
screen.browser_body.y=0
screen.browser_size.SetHeightOverride=function(self,height)self.height=height;layout_ready=false;observe()end
screen.browser_size.ForceLayoutPrepass=function()layout_ready=true;observe()end
package.loaded.ui_theme={
    colors={row={}},
    button=function()return {SetVisibility=function(self,v)self.visibility=v end}end,
    construct=function()
        return {visibility=0,SetVisibility=function(self,value)self.visibility=value;observe()end}
    end,
    place=function(_,frame)if frame==screen.version_warning then assert(frame.visibility==1,'empty card attached while visible');attached=true end;observe()end,
    card=function()assert(screen.version_warning.visibility==1);return {}end,
    color=function(x)return x end,
    label=function(_,_,text)
        assert(text~='','warning initially created without text')
        return {text=text,SetText=function(self,value)self.text=value;layout_ready=false;observe()end}
    end,
}
FText=function(text)return text end
local Warning=require('ui_version_warning')
Warning.create(screen,{},{})
-- Pending native work must leave no empty panel and reserve no blank space.
for _=1,60 do
    Warning.update(screen,{checking=true})
    assert(screen.version_warning.visibility==1 and screen.browser_body.y==0 and screen.browser_size.height==590)
end
Warning.update(screen,Version.classify('ok '..string.rep('0',64)))
assert(screen.version_warning.visibility==4 and screen.version_warning_visible)
assert(screen.version_warning_title.text=='Unsupported game version')
Warning.update(screen,{supported=true})
assert(screen.version_warning.visibility==1 and screen.browser_body.y==0 and screen.browser_size.height==590)
Warning.update(screen,Version.classify('unavailable'))
assert(screen.version_warning_title.text=='Game version could not be verified')
assert(screen.version_warning.visibility==4)
Warning.update(screen,Version.classify('unavailable'),{message='Mod 1.25.0 is ready.',can_restart=true})
assert(screen.version_warning_update.text=='Mod 1.25.0 is ready.' and screen.version_warning_restart.visibility==0)
Warning.update(screen,Version.classify('unavailable'),{message='Downloading… 50%',can_restart=false})
assert(screen.version_warning_update.text=='Downloading… 50%' and screen.version_warning_restart.visibility==1)
Warning.update({},Version.classify('unavailable')) -- lazy browser not constructed
print('Version warning: hidden construction, pending check without empty space, text and layout before first visible frame OK')
