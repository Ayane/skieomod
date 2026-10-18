package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {} end
local Heightmap=require('heightmap')
local Terrain=require('terrain')
local function terrain(values)
    local bytes={}
    for _,h in ipairs(values) do bytes[#bytes+1]=string.char(h%256,math.floor(h/256)) end
    local state=Heightmap.load({terrain={size_meters={10,10},
        origin_centimeters={-100,-200,300},
        source={file='test.r16',format='r16le',vertices={2,2},spacing_meters=10,
            height_scale_meters=1,height_offset_meters=800},
        runtime={sample_step=1,uv_tile_meters=20}},
        __read=function() return table.concat(bytes) end})
    state.sample_step=1
    return state
end
local function check(values,vertical)
    local state=terrain(values)
    local v,t,n,uv=Terrain.build_tile(state,{0,1},{0,1},1,1,1,0,true)
    assert(#t==6 and #n==#v and #uv==#v)
    for _,i in ipairs(t) do
        local p=v[i+1]
        assert(p.Z==Heightmap.height_at(state,p.X,p.Y),'UV projection changed the source surface')
    end
    if vertical then
        local a,c=t[1]+1,t[3]+1
        if v[c].Z==v[a].Z then c=t[2]+1 end
        assert(math.abs(uv[c].Y-uv[a].Y)==math.abs(v[c].Z-v[a].Z)/2000,
            'cliff UVs stretch instead of covering the vertical height')
    else
        assert(#v==4,'flat ground needlessly duplicates vertices')
        assert(uv[1].X==0 and uv[4].X==0.5 and uv[4].Y==0.5)
    end
    local sv,st,sn,suv=Terrain.build_tile(state,{0,1},{0,1},1,1,1,30,false)
    assert(#sv==4 and suv[4].X==0.5 and suv[4].Y==0.5,
        'snow and explicit map materials must retain their planar UVs')
    assert(st[1]==0 and st[2]==2 and st[3]==1,'mesh winding changed')
end
check({0,0,0,0},false)
check({0,100,0,100},true)
check({0,0,100,100},true)
print('Terrain ground UVs: flat ground, both cliff orientations, source heights and snow OK')
