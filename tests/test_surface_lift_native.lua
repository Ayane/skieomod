-- Private native cache writes must fail closed before an unreviewed game is touched.
package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local version={supported=false,build='26143813'}
local layout=true;local registrations={}
package.preload.game_version=function() return {poll=function() return version end} end
package.preload.compatibility=function() return {check=function() return layout,'layout changed' end} end
PropertyTypes={FloatProperty='FloatProperty'}
RegisterCustomProperty=function(p) registrations[#registrations+1]=p end
local Bridge=require('surface_lift_native')
local c={SkiEOTowLength=10000,SkiEOTowBoard=200,SkiEOTowExit=4800}
local a={CableComp=c,GetCableLength=function() return 10000 end,GetUphillCableLength=function() return 4600 end,
 ChairISM={GetInstanceCount=function() return 0 end},CableSpline={GetSplineLength=function() return 12000 end}}
assert(not pcall(Bridge.prepare,a) and #registrations==0)
version={supported=true,build='26143812'}
assert(not pcall(Bridge.prepare,a) and #registrations==0)
version.build='26143813';layout=false
assert(not pcall(Bridge.prepare,a) and #registrations==0)
layout=true
local original,phase=Bridge.prepare(a)
assert(#registrations==3 and phase==0)
for i,p in ipairs(registrations) do
 assert(p.OffsetInternal==0x12c+i*4 and p.Type=='FloatProperty' and p.BelongsToClass=='/Script/SkiResortSimulator.LiftCableComponent')
end
assert(not pcall(Bridge.set,a,5000,100) and c.SkiEOTowLength==10000)
assert(not pcall(Bridge.set,a,0,12000) and c.SkiEOTowLength==10000)
Bridge.set(a,0,5900)
assert(c.SkiEOTowLength==12000 and c.SkiEOTowBoard==0 and c.SkiEOTowExit==5900)
Bridge.restore(a,original)
assert(c.SkiEOTowLength==10000 and c.SkiEOTowBoard==200 and c.SkiEOTowExit==4800)
c.SkiEOTowLength=9500;assert(not pcall(Bridge.prepare,a))
c.SkiEOTowLength=10000;c.SkiEOTowExit=5000;assert(not pcall(Bridge.prepare,a))
c.SkiEOTowExit=0/0;assert(not pcall(Bridge.prepare,a))
print('Surface lift native cache: exact build, layout, marker semantics, bounds and restoration OK')

-- Exercise the actual Lua/native protocol without loading a Windows DLL.
local real_open,real_loadlib=io.open,package.loadlib
local memory,calls={},0
local offsets={GuestSimulationSubsystem={Guests=0x58,GuestsHot=0x68},GuestState={GuestId=0,QueueLiftId=0xa30,Discipline=0x1d},GuestHotState={ActivityState=0x68,ColorIndex=0x50,WorldPosition=0,Velocity=0x18}}
StaticFindObject=function(path)
 local fields=assert(offsets[path:match('%.([^%.]+)$')])
 return {ForEachProperty=function(_,callback)
  for name,offset in pairs(fields)do callback({GetFName=function()return{ToString=function()return name end}end,GetOffset_Internal=function()return offset end,GetClass=function()return{GetFName=function()return{ToString=function()return ({Guests='ArrayProperty',GuestsHot='ArrayProperty',GuestId='StructProperty',QueueLiftId='StructProperty',Discipline='EnumProperty',ActivityState='EnumProperty',ColorIndex='IntProperty',WorldPosition='StructProperty',Velocity='StructProperty'})[name]end}end}end})end
 end}
end
io.open=function(path,mode)
 if mode=='wb' then return{write=function(_,bytes)memory[path]=bytes end,close=function()end}end
 assert(memory[path],'missing protocol result')
 return{read=function()return memory[path]end,close=function()end}
end
package.loadlib=function(path,symbol)
 assert(symbol=='skieo_surface_lifts')
 local directory=path:match('^(.*[/\\])')
 return function()
  local bytes=memory[directory..'surface-lifts.job'];assert(#bytes==1360)
  local magic,revision,count,posed=string.unpack('<c4I4I4I4',bytes)
  assert(magic=='SKTL' and revision==2 and count<=16 and posed<=64)
  calls=calls+1;memory.last=bytes;memory[directory..'surface-lifts.status']='ok: tested'
 end
end
local g={A=-1,B=2,C=3,D=4}
local item={definition={kind='fixed_platter',speed_mps=2},lift={GetLiftId=function()return g end}}
offsets.GuestState.GuestId=8
assert(not pcall(Bridge.visuals,{item},{g}) and calls==0,'Changed GUID layout must fail before native invocation')
offsets.GuestState.GuestId=0
Bridge.visuals({item},{g});assert(calls==1)
assert(string.unpack('<I4',memory.last,17)==0xffffffff)
assert(string.unpack('<I4',memory.last,337)==0xffffffff,'Posed GUIDs start after sixteen lift rows')
local too_many={};for i=1,65 do too_many[i]=g end
assert(not pcall(Bridge.visuals,{item},too_many) and calls==1)
item.disposed=true;Bridge.visuals({item},{})
local _,_,count,posed=string.unpack('<c4I4I4I4',memory.last);assert(count==0 and posed==0)
version.supported=false;assert(not pcall(Bridge.visuals,{},{}))
io.open,package.loadlib=real_open,real_loadlib
print('Surface visual bridge: GUID guards, bounded SKTL v2 packet and cleanup OK')
-- Native chairlifts can embark just before the closed spline wraps to zero.
Bridge.set_loop(a,9500,4500)
assert(c.SkiEOTowBoard==9500 and c.SkiEOTowExit==4500)
assert(not pcall(Bridge.set_loop,a,2000,2000),'Zero-length chair ascent must fail')
Bridge.restore(a,original)
print('Native chair boarding markers remain valid across the closed-loop seam')
