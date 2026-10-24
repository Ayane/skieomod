package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local version={supported=false,build='26178224'}
package.preload.game_version=function()return{poll=function()return version end}end
local compatible,checks=true,0
package.preload.compatibility=function()return{require=function(feature,contract)
 checks=checks+1;assert(compatible,'changed camera layout')
 local fields=contract.classes['/Script/SkiResortSimulator.SkiResortCameraPawn']
 assert(feature=='camera.private_view'and fields.FollowCamera.offset==0x328 and fields.OrbitMinPitch.offset==0x5dc)
end}end
PropertyTypes={UInt64Property='UInt64Property'}
local properties={}
RegisterCustomProperty=function(p)properties[#properties+1]=p end
local function bits(n)return string.unpack('<i8',string.pack('<d',n))end
local function number(n)return string.unpack('<d',string.pack('<i8',n))end
local values={SkiEOViewPitchBits=bits(-20),SkiEOViewYawBits=bits(45),SkiEOViewRollBits=bits(0)}
local writes=0
local pawn=setmetatable({IsValid=function()return true end,
 IsA=function(_,class)return class=='/Script/SkiResortSimulator.SkiResortCameraPawn'end,
 OrbitMinPitch=-85,OrbitMaxPitch=-5},
 {__index=values,__newindex=function(_,key,value)values[key]=value;writes=writes+1 end})
local Camera=require('camera_view');local rotation={Pitch=-43,Yaw=145,Roll=0}
assert(not pcall(Camera.set,pawn,rotation)and writes==0 and #properties==0)
version.supported=true;version.build='unknown'
assert(not pcall(Camera.set,pawn,rotation)and #properties==0)
version.build='26178224';compatible=false
assert(not pcall(Camera.set,pawn,rotation)and writes==0 and #properties==0)
compatible=true
Camera.set(pawn,rotation)
assert(writes==3 and #properties==3)
for i,p in ipairs(properties)do
 assert(p.OffsetInternal==0x6f8+i*8 and p.Type=='UInt64Property')
end
assert(number(values.SkiEOViewPitchBits)==-43 and number(values.SkiEOViewYawBits)==145 and number(values.SkiEOViewRollBits)==0)
-- Model Tick reading its own cache instead of actor/control transforms.
local function tick()return{Pitch=number(values.SkiEOViewPitchBits),Yaw=number(values.SkiEOViewYawBits)}end
for _=1,60 do assert(tick().Yaw==145 and tick().Pitch==-43)end
version.build='26143813';Camera.set(pawn,{Pitch=-35,Yaw=505})
assert(tick().Yaw==145 and tick().Pitch==-35 and #properties==3)
local before=writes
for _,bad in ipairs({{Pitch=-91,Yaw=0},{Pitch=-43,Yaw=0/0},{Pitch=-43,Yaw=145,Roll=181}})do
 assert(not pcall(Camera.set,pawn,bad)and writes==before)
end
values.SkiEOViewPitchBits=bits(1234)
assert(not pcall(Camera.set,pawn,rotation)and writes==before,'Malformed old camera state was overwritten')
values.SkiEOViewPitchBits=bits(-20)
local wrong={IsValid=function()return true end,IsA=function()return false end}
assert(not pcall(Camera.set,wrong,rotation)and writes==before,'Wrong pawn class was accepted')
print('Native camera view: exact builds, reflected anchors, UE5 cached rotator, limits and invalid-state refusal OK')
