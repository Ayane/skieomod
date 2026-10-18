package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local H,M,S=require('heightmap'),require('terrain_mesh'),require('scenery')
local function grid(width,spacing,origin)
    local pieces={}
    for y=0,width-1 do for x=0,width-1 do pieces[#pieces+1]=string.pack('<I2',1000+x*3+y*2) end end
    return H.load({terrain={size_meters={(width-1)*spacing,(width-1)*spacing},origin_centimeters={origin,origin,0},
        source={file='terrain.r16',format='r16le',vertices={width,width},spacing_meters=spacing,height_scale_meters=1,height_offset_meters=0},
        runtime={sample_step=2}},__read=function()return table.concat(pieces)end})
end
local background,playable=grid(31,100,-150000),grid(21,10,-10000)
background.sample_step=1
playable.mesh_plan=M.plan(playable,2)
local hole=S.hole(background,playable)
assert(hole[1]==-20000 and hole[4]==20000,'background cutout did not follow the playable perimeter')
local v,t,n,u=S.tile(background,hole,M.sampled_indices(31,1),M.sampled_indices(31,1),1,1)
assert(#v==#n and #v==#u and #t>0)
for i=1,#t,3 do
    local a,b,c=v[t[i]+1],v[t[i+1]+1],v[t[i+2]+1]
    local x,y=(a.X+b.X+c.X)/3,(a.Y+b.Y+c.Y)/3
    assert(x<hole[1] or x>hole[3] or y<hole[2] or y>hole[4],'scenery covered the playable map')
end
local seam,indices=S.seam(background,playable,hole)
for i=1,#seam,2 do
    local a,b=seam[i],seam[i+1]
    assert(math.abs(a.Z-M.height_at(playable,a.X,a.Y))<1e-7,'inner seam does not match rendered terrain')
    assert(math.abs(b.Z-H.height_at(background,b.X,b.Y))<1e-7,'outer seam does not match regional terrain')
end
for i=1,#indices,3 do
    local a,b,c=seam[indices[i]+1],seam[indices[i+1]+1],seam[indices[i+2]+1]
    assert((b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X)<0,'scenery seam winding differs from native terrain')
end
assert(not pcall(S.hole,playable,background),'a scenery grid smaller than the playable map was accepted')
assert(S.load({extensions={}})==nil)
print('Scenery: playable cutout, exact inner/outer heights, stitched edges and upward winding OK')
