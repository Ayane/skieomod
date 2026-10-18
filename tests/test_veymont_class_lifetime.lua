-- Generated classes are weak Lua references until Unreal owns them. Exercise
-- the map event and collect unowned assets during the deferred station build.
package.path='mod/SkiEO-Veymont/Scripts/?.lua;'..package.path
local queued,delayed,classes={},{},{}
local function valid(self)return not self.dead end
local world={IsValid=function()return false end}
package.preload.UEHelpers=function()return {
    GetWorld=function()return world end,GetPlayer=function()end,
    GetGameplayStatics=function()return {IsValid=valid}end,
}end
package.preload.native_terrain=function()return {
    retain_texture=function(resource)resource.rooted=true end,
}end
package.preload.vegetation=function()return {unload=function()end}end
StaticFindObject=function(path)
    if path:find('Default__KismetGuidLibrary',1,true) then return {IsValid=valid} end
    return classes[path]
end
LoadAsset=function(path)
    assert(path:sub(-2)=='_C','station must load generated UClasses')
    local class={IsValid=valid};classes[path]=class;return class
end
ExecuteInGameThread=function(cb)queued[#queued+1]=cb end
ExecuteWithDelay=function(_,cb)delayed[#delayed+1]=cb end
local held,completed=0,0
local api={
    hold_loading=function()held=held+1;return function(message)
        assert(message=='resort classes are unavailable','invalid-world guard was not reached')
        completed=completed+1
    end end,
    every=function()end,after=function()end,read_asset=function()return '' end,
}
local map=assert(loadfile('mod/SkiEO-Veymont/Scripts/main.lua'))()
map.on_event('map.ready',{restored=false},api)
assert(held==2,'new-map station loading was not exercised')
for _,cb in ipairs(queued) do cb() end
local count=0
for _,class in pairs(classes) do
    if not class.rooted then class.dead=true end
    assert(class:IsValid(),'generated station class collected before delayed construction')
    count=count+1
end
assert(count==7 and #delayed==1,'lift, ticket office, shed and four amenities must survive the delay')
queued={};delayed[1]();assert(#queued==1);queued[1]()
assert(completed==1,'world guard did not finish the deferred callback')
print('Veymont generated classes: seven assets survive GC across the delayed station build OK')
