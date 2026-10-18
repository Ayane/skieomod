package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local H=require('heightmap')
local function bytes(values,big)
 local result={}
 for _,n in ipairs(values) do
  local lo,hi=n%256,math.floor(n/256)
  result[#result+1]=big and string.char(hi,lo) or string.char(lo,hi)
 end
 return table.concat(result)
end
for _,big in ipairs({false,true}) do
 for _,order in ipairs({'north_to_south','south_to_north'}) do
  local state={bytes=bytes({0,10000,40000,65535},big),width=2,height=2,
   little_endian=not big,row_order=order,origin_z=12000,origin_x=0,origin_y=0,
   spacing_cm=400,height_offset_cm=72398.75,height_scale_cm=2.5}
  local before=state.bytes
  local native=H.native_state(state)
  assert(native.height_offset_cm==0 and native.height_scale_cm>state.height_scale_cm)
  assert(state.bytes==before and state.height_scale_cm==2.5)
  assert(H.native_state(state)==native)
  for row=0,1 do for col=0,1 do
   local delta=math.abs(H.sample_grid_cm(native,col,row)-H.sample_grid_cm(state,col,row))
   assert(delta<=native.height_scale_cm/2+0.001,'native encoding moved the terrain')
  end end
  local peak=-state.origin_z/100+native.height_scale_cm*65536/100
  assert(peak>2100,'UI altitude still capped at 1638m')
  assert(math.abs(peak-2242.3875)<0.0001)
 end
end
local zero={height_offset_cm=0}
assert(H.native_state(zero)==zero)
print('Native height encoding: datum, endian, rows, quantization and source preservation OK')
