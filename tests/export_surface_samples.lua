-- Export actual rendered triangles as the independent native-sampler oracle.
package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local H,M,J=require('heightmap'),require('terrain_mesh'),require('json')
local cases={}
for _,step in ipairs({1,3,4,7,16,64}) do
 for _,reversed in ipairs({false,true}) do
  for _,budget in ipairs({1,16384}) do
   local bytes,values={},{}
   local width,height=18,11
   for row=0,height-1 do for x=0,width-1 do
    local y=reversed and height-1-row or row
    local value=math.max(0,math.min(4,x-4))*700+y*30+((x*11+y*7)%19)*13
    values[#values+1]=value
    bytes[#bytes+1]=string.pack(reversed and '>I2' or '<I2',value)
   end end
   local state=H.load({terrain={size_meters={(width-1)*2,(height-1)*2},origin_centimeters={-400,-800,123},
    source={file='x',vertices={width,height},format=reversed and 'r16be' or 'r16le',spacing_meters=2,
     height_scale_meters=.1,height_offset_meters=800,row_order=reversed and 'south_to_north' or 'north_to_south'},
    runtime={sample_step=step}},__read=function()return table.concat(bytes)end})
   state.sample_step=step;local plan=M.plan(state,step,budget);state.mesh_plan=plan
   local case={width=width,height=height,step=step,fine=plan.fine_step,flags=reversed and 2 or 1,
    values=values,refined={},points={}}
   for key in pairs(plan.refined)do case.refined[#case.refined+1]=key end
   for y=1,#plan.rows-1 do for x=1,#plan.columns-1 do
    local vertices,triangles=M.build_tile(state,plan.columns,plan.rows,x,y,1,0,true,plan)
    for i=1,#triangles,3 do
     local a,b,c=vertices[triangles[i]+1],vertices[triangles[i+1]+1],vertices[triangles[i+2]+1]
     for _,weights in ipairs({{1,0,0},{0,1,0},{0,0,1},{.5,.5,0},{0,.5,.5},{.5,0,.5},{1/3,1/3,1/3},{.15,.25,.6}})do
      local u,v,w=table.unpack(weights)
      case.points[#case.points+1]={(a.X*u+b.X*v+c.X*w-state.origin_x)/state.spacing_cm,
       (a.Y*u+b.Y*v+c.Y*w-state.origin_y)/state.spacing_cm,
       (a.Z*u+b.Z*v+c.Z*w-state.origin_z-state.height_offset_cm)/state.height_scale_cm}
     end
    end
   end end
   cases[#cases+1]=case
  end
 end
end
local f=assert(io.open(assert(arg[1]),'wb'));f:write(J.encode(cases));f:close()
