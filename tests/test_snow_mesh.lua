package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local H,M,S=require('heightmap'),require('terrain_mesh'),require('snow_mesh')
local bytes={}
for y=0,8 do for x=0,10 do bytes[#bytes+1]=string.pack('<I2',2000+x*50+y*20+(x==5 and y==5 and 900 or 0))end end
local state=H.load({terrain={size_meters={100,80},origin_centimeters={-5000,-4000,0},
 source={vertices={11,9},format='r16le',spacing_meters=10,height_scale_meters=.01,height_offset_meters=700},
 runtime={sample_step=2}},__read=function()return table.concat(bytes)end})
M.prepare(state)
local plan=S.plan(state)
assert(plan.fine_step==.25,'snow displacement does not resolve the native grid')
local changed=S.add_regions(state,plan,{{0,0,500}})
assert(#changed>0 and #S.add_regions(state,plan,{{0,0,500}})==0,'repeated owners grew the mesh')
assert(state.mesh_plan~=plan,'snow refinement modified authoritative terrain')
local vertices,triangles=M.build_tile(state,plan.columns,plan.rows,1,1,8,30,false,plan,
 function(x,y)return S.sample(state,x,y)end)
local seen={}
for _,v in ipairs(vertices)do
 local key=string.format('%.8f:%.8f',v.X,v.Y)
 assert(not seen[key],'fractional snow vertices were duplicated');seen[key]=true
 assert(math.abs(v.Z-30-M.height_at(state,v.X,v.Y))<1e-7,'snow density resurrected omitted source detail')
end
local shortest,area=math.huge,0
for i=1,#triangles,3 do
 local a,b,c=vertices[triangles[i]+1],vertices[triangles[i+1]+1],vertices[triangles[i+2]+1]
 local cross=(b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X)
 assert(cross<0,'snow triangle was inverted or degenerate');area=area-cross/2
 for _,pair in ipairs({{a,b},{a,c},{b,c}})do local p,q=pair[1],pair[2];shortest=math.min(shortest,math.sqrt((p.X-q.X)^2+(p.Y-q.Y)^2))end
end
assert(shortest==250,'fractional tessellation skipped samples')
assert(math.abs(area-10000*8000)<.001,'snow tessellation lost or duplicated area')
local base=state.mesh_plan.refined_count
S.add_regions(state,plan,{{0,0,10000000}})
assert(plan.added<=plan.maximum_added and plan.refined_count==base+plan.added)
assert(plan.refined_count*math.ceil(state.sample_step/plan.fine_step)^2<=524288)
print('Snow mesh: native-scale displacement, fractional vertices, exact base surface, bounded density, seams and idempotence OK')
