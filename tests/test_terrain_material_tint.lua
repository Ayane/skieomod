-- A tinted terrain with portable textures must keep its albedo: the tint is
-- applied to the dynamic instance that carries the textures, not to a second
-- instance parented to it (which rendered without the baked ground cover).
package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local callbacks,instances={},{}
local function valid(self)return not self.dead end
local function object(o)o=o or {};o.IsValid=valid;return o end
local world=object({GetAddress=function()return 1 end})
local assigned
local mesh=object({SetCollisionEnabled=function()end,CreateMeshSection=function()end,
    GetNumSections=function()return 1 end,SetMaterial=function(_,_,m)assigned=m end})
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
local albedo=object({name='baked ground cover'})
package.preload.textures=function()return {load=function()return {albedo=albedo}end}end
local parent=object()
local library=object({CreateDynamicMaterialInstance=function(_,_,p)
    local m=object({parent=p,textures={},vectors={}})
    function m:SetTextureParameterValue(name,texture)self.textures[name]=texture end
    function m:SetVectorParameterValue(name,value)self.vectors[name]=value end
    instances[#instances+1]=m;return m
end})
StaticFindObject=function(path)
    if path:find('KismetMaterialLibrary',1,true) then return library end
    if path:find('TintTest',1,true) then return parent end
    return object()
end
FindAllOf=function()return {}end;FName=function(n)return n end
ExecuteInGameThread=function(cb)callbacks[#callbacks+1]=cb end
ExecuteInGameThreadWithDelay=function(_,cb)callbacks[#callbacks+1]=cb end
local map={terrain={size_meters={1,1},origin_centimeters={0,0,0},
    source={file='test.r16',format='r16le',vertices={2,2},spacing_meters=1,
        height_scale_meters=1,height_offset_meters=0},
    -- Written by the ground-cover bake: explicit material, white tint, albedo.
    runtime={skirt_enabled=false,sample_step=1,material='/Game/TintTest',
        material_color={1,1,1,1},texture_parameters={albedo='Albedo'}},
    textures={albedo={file='Terrain/Generated/albedo.png',mips={},color_space='srgb'}}},
    __read=function()return string.rep('\0',8)end}
local completed=false;local Terrain=require('terrain')
Terrain.load(map,function(ok,message)assert(ok,message);completed=true end)
local cursor=1
while callbacks[cursor] do local cb=callbacks[cursor];cursor=cursor+1;cb() end
assert(completed and assigned,'terrain material was not assigned')
assert(#instances==1,'tint created a second instance over the textured material: '..#instances)
assert(assigned==instances[1] and assigned.parent==parent,'terrain must use the textured instance')
assert(assigned.textures.Albedo==albedo,'baked albedo is missing on the terrain material')
local tint=assigned.vectors.Color
assert(tint and tint.R==1 and tint.G==1 and tint.B==1 and tint.A==1,'material_color tint was not applied')
Terrain.unload()
print('Terrain materials: tint keeps the baked albedo on the textured instance OK')
