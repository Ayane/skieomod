-- Model Unreal GC between queued frames. Lua tables intentionally do not root
-- materials: parent import/tint and delayed section assignment need ownership.
package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local callbacks,materials={},{}
local function valid(self)return not self.dead end
local function object(o)o=o or {};o.IsValid=valid;return o end
local world=object({GetAddress=function()return 1 end})
local assignments=0
local mesh=object({SetCollisionEnabled=function()end,CreateMeshSection=function()end,
    GetNumSections=function()return 1 end,SetMaterial=function(_,_,m)
        assert(m.rooted and m:IsValid(),'queued material was collected before render-state construction')
        assignments=assignments+1
    end})
local actor=object({SetActorEnableCollision=function()end,AddComponentByClass=function()return mesh end,
    K2_DestroyActor=function()end})
local game=object({BeginDeferredActorSpawnFromClass=function()return actor end,FinishSpawningActor=function()return actor end})
package.preload.UEHelpers=function()return {GetWorld=function()return world end,
    GetGameplayStatics=function()return game end,FindOrAddFName=function(n)return n end}end
package.preload.native_terrain=function()return {
    reset=function()end,
    retain_texture=function(m)m.rooted=true end,
    populate=function(_,done)done(true,{width=2,height=2,spacing_x=100,spacing_y=100,
        landscape={texture_count=0,mip_count=0},derived_textures={count=0},elapsed_seconds=0})end,
}end
package.preload.nanite_terrain=function()return {apply=function(_,_,done)done()end}end
package.preload.scenery=function()return {create=function(_,_,_,done)done(true)end}end
local parent=object();materials[1]=parent
local library=object({CreateDynamicMaterialInstance=function(_,_,p)
    assert(p.rooted,'parent material can be collected during texture import/tint')
    local m=object({SetVectorParameterValue=function()end});materials[#materials+1]=m;return m
end})
StaticFindObject=function(path)
    if path:find('KismetMaterialLibrary',1,true) then return library end
    if path:find('LifetimeTest',1,true) then return parent end
    return object()
end
FindAllOf=function()return {}end;FName=function(n)return n end
ExecuteInGameThread=function(cb)callbacks[#callbacks+1]=cb end
ExecuteInGameThreadWithDelay=function(_,cb)callbacks[#callbacks+1]=cb end
local map={terrain={size_meters={1,1},origin_centimeters={0,0,0},
    source={file='test.r16',format='r16le',vertices={2,2},spacing_meters=1,
        height_scale_meters=1,height_offset_meters=0},
    runtime={skirt_enabled=false,sample_step=1,material='/Game/LifetimeTest',material_color={1,1,1}}},
    __read=function()return string.rep('\0',8)end}
local completed=false;local Terrain=require('terrain')
Terrain.load(map,function(ok,message)assert(ok,message);completed=true end)
local cursor=1
while callbacks[cursor] do
    for _,m in ipairs(materials) do if not m.rooted then m.dead=true end end
    -- The parent begins as a cooked asset until loaded by the first callback.
    if #materials==1 then parent.dead=false end
    local cb=callbacks[cursor];cursor=cursor+1;cb()
end
assert(completed and assignments==1 and #materials==2,'terrain material lifecycle was not exercised')
Terrain.unload()
print('Terrain materials: parent retained before imports/tint and dynamic material survives queued-frame GC OK')
