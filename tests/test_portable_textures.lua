package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {GetWorld=function() return {} end} end
local retained,installed,updated={},nil,nil
package.preload.native_terrain=function() return {
 retain_texture=function(texture) retained[#retained+1]=texture end,
 install_portable_texture_mips=function(sources) installed=sources;return true,'ok: mips' end,
} end
local function u32(n) return string.char(math.floor(n/16777216)%256,math.floor(n/65536)%256,math.floor(n/256)%256,n%256) end
local function png(side,color,bits) return '\137PNG\13\10\26\10'..u32(13)..'IHDR'..u32(side)..u32(side)..string.char(bits or 8,color or 6,0,0,0)..u32(0) end
local bytes=nil
local saved_open=io.open
io.open=function(path,mode) assert(path:match('portable_texture%.png$') and mode=='wb');return {write=function(_,b) bytes=b end,close=function() end} end
local saved_remove=os.remove;os.remove=function() return true end
local texture_count=0
local rendering={IsValid=function() return true end,ImportFileAsTexture2D=function()
 texture_count=texture_count+1
 local size=bytes:byte(20)
 return {IsValid=function() return true end,Blueprint_GetSizeX=function() return size end,Blueprint_GetSizeY=function() return size end}
end}
local update=setmetatable({IsValid=function() return true end},{__call=function(_,texture) updated=texture end})
StaticFindObject=function(path) return path:find('KismetRenderingLibrary',1,true) and rendering or update end
local Textures=require('textures')
assert(Textures.png_size(png(512))==512)
assert(Textures.png_size(png(1,2))==1)
for _,bad in ipairs({'bad',png(513),png(3),png(4,0),png(4,6,16)}) do assert(not pcall(Textures.png_size,bad)) end
local images={['rock.png']=png(4),['m1.png']=png(2),['m2.png']=png(1)}
local map={terrain={textures={albedo={file='rock.png',mips={'m1.png','m2.png'},color_space='linear'}}},__read=function(path) return images[path] end}
local textures=Textures.load(map)
assert(#installed==3 and #retained==3 and updated==textures.albedo and textures.albedo==installed[1])
assert(textures.albedo.SRGB==false and textures.albedo.NeverStream==true and textures.albedo.AddressX==0)
map.terrain.textures.albedo.mips={'m1.png'}
assert(not pcall(Textures.load,map),'incomplete mip chain accepted')
map.terrain.textures.albedo.mips={'m2.png','m1.png'}
assert(not pcall(Textures.load,map),'incorrect mip dimensions accepted')
io.open=saved_open;os.remove=saved_remove
print('Portable textures: bounded PNGs, archive reads, complete mip chain, color space and UObject retention OK')
