package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Heightmap=require('heightmap')
local Mesh=require('terrain_mesh')

local function state(width,height,step,sample,reversed)
    local bytes={}
    for row=0,height-1 do
        local y=reversed and height-1-row or row
        for x=0,width-1 do bytes[#bytes+1]=string.pack('<I2',sample(x,y)) end
    end
    local s=Heightmap.load({terrain={size_meters={(width-1)*2,(height-1)*2},
        origin_centimeters={-400,-800,123},
        source={file='test.r16',format='r16le',vertices={width,height},
            spacing_meters=2,height_scale_meters=0.1,height_offset_meters=800,
            row_order=reversed and 'south_to_north' or 'north_to_south'},
        runtime={sample_step=step}},__read=function() return table.concat(bytes) end})
    s.sample_step=step
    return s
end

local function verify(s,plan)
    s.mesh_plan=plan
    local columns=plan and plan.columns or Mesh.sampled_indices(s.width,s.sample_step)
    local rows=plan and plan.rows or Mesh.sampled_indices(s.height,s.sample_step)
    local checks=0
    -- Use rendered triangles as an independent oracle, including boundaries
    -- between sections, coarse cells, cliff subdivisions and stitched fans.
    for y=1,#rows-1 do
        for x=1,#columns-1 do
            local vertices,triangles=Mesh.build_tile(s,columns,rows,x,y,1,0,true,plan)
            for i=1,#triangles,3 do
                local a,b,c=vertices[triangles[i]+1],vertices[triangles[i+1]+1],vertices[triangles[i+2]+1]
                for _,weights in ipairs({{1,0,0},{0,1,0},{0,0,1},{0.5,0.5,0},
                    {0,0.5,0.5},{0.5,0,0.5},{1/3,1/3,1/3},{0.15,0.25,0.6}}) do
                    local u,v,w=table.unpack(weights)
                    local px,py=a.X*u+b.X*v+c.X*w,a.Y*u+b.Y*v+c.Y*w
                    local expected=a.Z*u+b.Z*v+c.Z*w
                    local actual=Mesh.height_at(s,px,py)
                    assert(actual and math.abs(actual-expected)<1e-7,
                        ('root %.9f differs from rendered triangle %.9f at %.3f,%.3f')
                            :format(actual or -1,expected,px,py))
                    checks=checks+1
                end
            end
        end
    end
    assert(Mesh.height_at(s,s.origin_x-0.01,s.origin_y)==nil)
    assert(Mesh.height_at(s,s.origin_x,s.origin_y+s.height*s.spacing_cm)==nil)
    assert(Mesh.height_at(s,0/0,s.origin_y)==nil)
    assert(Mesh.height_at(s,math.huge,s.origin_y)==nil)
    return checks
end

-- The old bilinear API floats on even a fully sampled saddle: its height
-- does not describe the two rendered triangles.
local saddle=state(2,2,1,function(x,y) return x*y*100 end)
local x,y=saddle.origin_x+100,saddle.origin_y+100
assert(Heightmap.height_at(saddle,x,y)-Mesh.height_at(saddle,x,y)==250)
verify(saddle)

-- Detailed peaks absent from the coarse visible mesh must not raise roots.
local peak=state(5,5,4,function(x,y) return x==2 and y==2 and 1000 or 0 end)
peak.mesh_plan=Mesh.plan(peak,4)
assert(peak.mesh_plan.refined_count==0)
x,y=peak.origin_x+400,peak.origin_y+400
assert(Heightmap.height_at(peak,x,y)-Mesh.height_at(peak,x,y)==10000)
verify(peak,peak.mesh_plan)

local checks=0
for _,step in ipairs({1,3,4,7,16}) do
    for _,reversed in ipairs({false,true}) do
        local s=state(18,11,step,function(xx,yy)
            return math.max(0,math.min(4,xx-4))*70+yy*3+(xx==6 and 20 or 0)
        end,reversed)
        checks=checks+verify(s,Mesh.plan(s,step))
        checks=checks+verify(s,Mesh.plan(s,step,1))
        checks=checks+verify(s,nil)
    end
end
print(('Tree grounding: %d checks against rendered triangles, decimation, cliffs, seams, rectangular edges and row order OK'):format(checks))
