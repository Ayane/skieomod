package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Heightmap=require('heightmap')
local Mesh=require('terrain_mesh')

local function state(width,height,step)
    local bytes={}
    for y=0,height-1 do
        for x=0,width-1 do
            -- Gentle ground beside a sharp, uneven wall. Include relief that
            -- the coarse grid misses between its four-metre samples.
            local z=math.max(0,math.min(4,x-4))*30+y+(x==6 and 8 or 0)
            bytes[#bytes+1]=string.char(z%256,math.floor(z/256))
        end
    end
    local s=Heightmap.load({terrain={size_meters={width-1,height-1},
        origin_centimeters={-400,-800,100},
        source={file='test.r16',format='r16le',vertices={width,height},
            spacing_meters=1,height_scale_meters=0.1,height_offset_meters=800},
        runtime={sample_step=step,uv_tile_meters=20}},
        __read=function() return table.concat(bytes) end})
    s.sample_step=step
    return s
end

local function point(v,offset)
    return ('%.6f,%.6f,%.6f'):format(v.X,v.Y,v.Z-(offset or 0))
end
local function verify(s,plan)
    local edges,triangles={},0
    -- One coarse cell per section exposes every potential inter-section seam.
    for y=1,plan.height do
        for x=1,plan.width do
            local v,t,n,uv=Mesh.build_tile(s,plan.columns,plan.rows,x,y,1,0,true,plan)
            local snow,st=Mesh.build_tile(s,plan.columns,plan.rows,x,y,1,30,false,plan)
            assert(#t==#st,'ground and snow use different refinement plans')
            assert(#n==#v and #uv==#v)
            for i,p in ipairs(v) do
                assert(math.abs(p.Z-Heightmap.height_at(s,p.X,p.Y))<1e-7,
                    'refinement fabricated elevations')
                assert(math.abs(n[i].X^2+n[i].Y^2+n[i].Z^2-1)<1e-10)
            end
            for i=1,#t,3 do
                local a,b,c=v[t[i]+1],v[t[i+1]+1],v[t[i+2]+1]
                local area=(b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X)
                assert(area<0,'flipped or degenerate adaptive triangle')
                for j=i,i+2 do
                    assert(point(v[t[j]+1])==point(snow[st[j]+1],30),
                        'snow topology/offset differs from ground')
                end
                for _,pair in ipairs({{a,b},{b,c},{c,a}}) do
                    local aa,bb=point(pair[1]),point(pair[2])
                    if aa>bb then aa,bb=bb,aa end
                    local key=aa..'/'..bb
                    local edge=edges[key] or {a=pair[1],b=pair[2],count=0}
                    edge.count=edge.count+1;edges[key]=edge
                end
                triangles=triangles+1
            end
        end
    end
    local x0,y0=s.origin_x,s.origin_y
    local x1,y1=x0+(s.width-1)*s.spacing_cm,y0+(s.height-1)*s.spacing_cm
    for _,edge in pairs(edges) do
        local a,b=edge.a,edge.b
        local boundary=(a.X==x0 and b.X==x0) or (a.X==x1 and b.X==x1)
            or (a.Y==y0 and b.Y==y0) or (a.Y==y1 and b.Y==y1)
        assert(edge.count==(boundary and 1 or 2),
            'open seam, T-junction or overlapping triangles at a coarse/fine edge')
    end
    return triangles
end

local s=state(17,9,4)
local plan=Mesh.plan(s,4)
assert(plan.refined_count==2 and plan.fine_step==1)
local count=verify(s,plan)
assert(count>plan.width*plan.height*2,'cliffs still use only coarse triangles')
local v=Mesh.build_tile(s,plan.columns,plan.rows,2,1,1,0,false,plan)
local detail=false
for _,p in ipairs(v) do if p.X==s.origin_x+600 then detail=true end end
assert(detail,'source cliff details between coarse samples were discarded')
local bounded=Mesh.plan(s,4,1)
assert(bounded.refined_count==1,'refinement exceeded its cell budget')
verify(s,bounded)
-- Unequal last cells and odd steps require half-grid centers on some fans.
local odd=state(17,8,3)
verify(odd,Mesh.plan(odd,3))
local fine=state(9,5,1)
local fine_plan=Mesh.plan(fine,1)
assert(fine_plan.refined_count==0,'already dense source was subdivided')
assert(verify(fine,fine_plan)==64)
-- Large source strides still permit at most four subdivisions per axis.
local large=state(65,65,64)
assert(Mesh.plan(large,64).fine_step==16)
print('Adaptive cliffs: source relief, watertight section seams, winding, snow alignment and budget OK')
