package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {} end
local Heightmap=require('heightmap')
local Terrain=require('terrain')
local bytes={}
for _,value in ipairs({0,10,20,30,999,50,60,70,80}) do
    bytes[#bytes+1]=string.char(value%256,math.floor(value/256))
end
local state=Heightmap.load({terrain={size_meters={2000,2000},
    origin_centimeters={-100000,-100000,5000},
    source={file='test.r16',format='r16le',vertices={3,3},spacing_meters=1000,
        height_scale_meters=1,height_offset_meters=800},runtime={sample_step=1}},
    __read=function() return table.concat(bytes) end})
local vertices,triangles,normals,uvs,bottom=Terrain.build_skirt(state)
assert(#vertices==32 and #triangles==96 and #normals==32 and #uvs==32)
assert(bottom==75000,'automatic skirt did not follow the actual edge height and datum')
for i=1,#vertices,4 do
    local a,b,c,d=vertices[i],vertices[i+1],vertices[i+2],vertices[i+3]
    assert(a.Z==Heightmap.height_at(state,a.X,a.Y) and c.Z==Heightmap.height_at(state,c.X,c.Y))
    assert(b.Z==bottom and d.Z==bottom and b.X==a.X and b.Y==a.Y)
    assert(normals[i].Z==0 and math.abs(normals[i].X^2+normals[i].Y^2-1)<1e-8)
    assert(uvs[i].Y>0 and uvs[i+1].Y==0,'wall UVs do not cover the vertical edge')
end
assert(vertices[#vertices-1].X==vertices[1].X and vertices[#vertices-1].Y==vertices[1].Y,
    'source perimeter was not closed')
state.runtime.skirt_depth_meters=350
local _,_,_,_,manual=Terrain.build_skirt(state)
assert(manual==50000,'manual depth override was ignored')
state.row_order='south_to_north'
local flipped=Terrain.build_skirt(state)
assert(flipped[1].Z==91000,'skirt ignored source row order')
state.runtime.skirt_depth_meters=nil
state.spacing_cm=2000000
local _,_,_,_,large=Terrain.build_skirt(state)
assert(large==85000-160000,'automatic skirt depth ignored map size')
print('Terrain skirt: source datum, perimeter, UVs, automatic depth and override OK')
