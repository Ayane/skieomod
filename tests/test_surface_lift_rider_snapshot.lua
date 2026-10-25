package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.game_version=function()return{poll=function()return{supported=true,build='26178224'}end}end
local layouts={GuestSimulationSubsystem={Guests={0x58,'ArrayProperty'},GuestsHot={0x68,'ArrayProperty'}},GuestState={GuestId={0,'StructProperty'},QueueLiftId={0xa30,'StructProperty'},Discipline={0x1d,'EnumProperty'}},GuestHotState={ActivityState={0x68,'EnumProperty'},WorldPosition={0,'StructProperty'},Velocity={0x18,'StructProperty'},ColorIndex={0x50,'IntProperty'}}}
StaticFindObject=function(path)return{ForEachProperty=function(_,fn)for name,field in pairs(layouts[path:match('%.([^%.]+)$')])do fn({GetFName=function()return{ToString=function()return name end}end,GetOffset_Internal=function()return field[1]end,GetClass=function()return{GetFName=function()return{ToString=function()return field[2]end}end}end})end end}end
local memory={};local original_open,original_remove,original_load=io.open,os.remove,package.loadlib
io.open=function(path,mode)
 if mode=='wb'then return{write=function(_,...)memory[path]=table.concat({...})end,close=function()end}end
 if memory[path]then return{read=function()return memory[path]end,close=function()end}end
end
os.remove=function(path)memory[path]=nil end
local stale=false;local x=123;local index=4
package.loadlib=function(_,symbol)return function()
 local directory='mod/SkiEO-CustomMaps/Scripts/'
 if symbol=='skieo_surface_lifts'then memory[directory..'surface-lifts.status']='ok: reviewed';return end
 assert(symbol=='skieo_surface_riders')
 local magic,version,owner,cls,nonce=string.unpack('<c4I4I8I8I4',memory[directory..'surface-riders.job'])
 assert(magic=='SKRD'and version==1 and owner==9 and cls==10)
 assert(memory[directory..'surface-riders.bin']==nil,'Stale snapshot was not removed')
 memory[directory..'surface-riders.bin']=string.pack('<c4I4I4I4','SKRD',1,stale and nonce-1 or nonce,1)..string.pack('<I4I4i4I4I4I4I4I4I4I4I4I4ddd',index,1,42,0,0xffffffff,2,3,4,7,0,0,0,x,22,33)
end end
local Bridge=require('surface_lift_native');Bridge.visuals({})
local guests={GetAddress=function()return 9 end,GetClass=function()return{GetAddress=function()return 10 end}end}
local state={};local id='00000007-00000000-00000000-00000000'
local row=Bridge.riders(state,guests)[id][1]
assert(row.key=='ffffffffffffffff-00000002-00000003-00000004'and row.color==42 and row.X==123 and row.index==4)
x=456;index=2
local next_row=Bridge.riders(state,guests)[id][1]
assert(next_row==row and row.X==456 and row.index==2,'Snapshot did not preserve identity through native compaction')
stale=true;assert(not pcall(Bridge.riders,state,guests),'Stale response nonce was accepted')
io.open,os.remove,package.loadlib=original_open,original_remove,original_load
print('Native rider snapshots: complete packets, live positions, palette, stable GUID pools and stale response rejection OK')
