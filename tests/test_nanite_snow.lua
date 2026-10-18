package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Snow=require('nanite_snow')
local function valid() return true end
local rt={IsValid=valid,SizeX=1008,SizeY=1008}
local snow={IsValid=valid,CoarseMipReadbackFp16RT=rt}
local depth,reads=100,0
StaticFindObject=function()
 return {ReadRenderTargetRawPixel=function(_,world,target,x,y,normalized)
  assert(target==rt and x>=0 and x<1008 and y>=0 and y<1008 and not normalized)
  reads=reads+1;return {R=depth}
 end}
end
FName=function(value) return value end
local visible,threshold,visibility_calls=false,nil,0
local coats={{entry={layer='snow_deposits',snow_uv_bounds={{.25,.5},{.375,.75}}},
 material={IsValid=valid,SetScalarParameterValue=function(_,name,value) threshold=value end},
 component={IsValid=valid,SetVisibility=function(_,value) visible=value;visibility_calls=visibility_calls+1 end}}}
local value,coverage=Snow.refresh({},coats,snow)
assert(value==100 and coverage==1 and reads==9 and visible and threshold==-10000000)
-- A renderer/debug view can temporarily hide the layer. A stable weather
-- update must not override that visibility.
visible=false;Snow.refresh({},coats,snow);assert(not visible and visibility_calls==1)
depth=0;Snow.refresh({},coats,snow);assert(not visible and threshold==10000000)
depth=5;Snow.refresh({},coats,snow);assert(visible and coats[1].coverage>0 and coats[1].coverage<1)
assert(Snow.coverage(-1)==0 and Snow.coverage(0/0)==0 and Snow.coverage(nil)==0)
depth=0/0;assert(not pcall(Snow.refresh,{},coats,snow),'invalid native samples accepted')
-- Scheduled work stops after map destruction/replacement.
local queue={}
snow.GetWorld=function() return {GetAddress=function() return 1 end} end
FindAllOf=function() return {snow} end
local state={}
local terrain={active=state,generation=1,actor={IsValid=valid,GetWorld=snow.GetWorld}}
depth=0
Snow.start(terrain,state,coats,function(_,callback) queue[#queue+1]=callback end,function() end)
assert(#queue==1 and state.nanite_snow_coverage==0)
terrain.generation=2;table.remove(queue,1)();assert(#queue==0)
print('Cliff snow: bounded native sampling, coverage, visibility and map lifecycle OK')
