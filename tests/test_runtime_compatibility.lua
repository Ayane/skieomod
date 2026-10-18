package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function()return {}end
local objects,hooks={},{}
local next_address=10000
local function object(fields)
 next_address=next_address+1000;local address=next_address
 fields.IsValid=function()return true end;fields.GetAddress=function()return address end
 return fields
end
local function property(name,kind,offset)
 return {GetFName=function()return {ToString=function()return name end}end,
  GetClass=function()return {GetFName=function()return {ToString=function()return kind end}end}end,
  ContainerPtrToValuePtr=function(_,owner) return string.format('userdata: 0x%x',owner:GetAddress()+(offset or 0)) end}
end
local function class(path,fields,parent)
 local cls=object({ForEachProperty=function(_,callback)for _,p in ipairs(fields) do callback(p) end end,
  GetSuperStruct=function()return parent end})
 objects[path]=cls
 objects[path:gsub('%.([^%.]+)$','.Default__%1')]=object({})
 return cls
end
StaticFindObject=function(path)return objects[path]end
RegisterHook=function(path,pre,post) hooks[#hooks+1]={path=path,pre=pre,post=post}end
local C=require('compatibility')
local owner=object({})
assert(C.field_offset({ContainerPtrToValuePtr=function()return string.format('userdata: %016X',owner:GetAddress()+0x68)end},owner)==0x68,
 'Windows Lua pointer formatting was not recognized')
local inherited=class('/Script/Test.Base',{property('Inherited','IntProperty',0x20)})
class('/Script/Test.Derived',{property('Value','FloatProperty',0x40)},inherited)
local contract={classes={['/Script/Test.Derived']={Value={type='FloatProperty',offset=0x40},Inherited='IntProperty'}}}
assert(C.check('private',contract))
local snapshot=C.snapshot();snapshot.private.available=false
assert(C.snapshot().private.available,'diagnostics leaked mutable state')
class('/Script/Test.Derived',{property('Value','FloatProperty',0x48)},inherited)
assert(not C.check('private',contract),'moved private anchor was accepted')
assert(C.check('public',{classes={['/Script/Test.Derived']={Value='FloatProperty'}}}),'moving public field was refused')
assert(not C.check('changed',{classes={['/Script/Test.Derived']={Value='DoubleProperty'}}}))
assert(not C.check('missing',{classes={['/Script/Test.Deleted']={Value='FloatProperty'}}}))
local fn='/Script/Test.Derived:Height'
class(fn,{property('X','FloatProperty'),property('ReturnValue','FloatProperty')})
local params={X='FloatProperty',ReturnValue='FloatProperty'}
local calls=0
assert(C.hook('height',fn,'post',function()calls=calls+1;return 123 end,params))
assert(hooks[1].post()==123 and calls==1)
assert(C.hook('height',fn,'post',function()error('reinstalled')end,params) and #hooks==1)
assert(C.hook('broken_callback',fn,'pre',function()calls=calls+1;error('game API changed')end,params))
assert(hooks[2].pre()==nil and not C.snapshot().broken_callback.available)
hooks[2].pre();assert(calls==2,'failed optional hook continued running')
class(fn,{property('X','FloatProperty'),property('Z','FloatProperty'),property('ReturnValue','FloatProperty')})
assert(not C.hook('new_argument',fn,'post',function()error('unsafe shifted callback')end,params))
assert(#hooks==2,'mismatched function reached RegisterHook')
assert(not C.hook('deleted_function','/Script/Test.Derived:Deleted','pre',function()end))
assert(C.snapshot().height.available,'one failed hook disabled another feature')
class(fn,{property('ReturnValue','FloatProperty'),property('X','FloatProperty')})
assert(not C.hook('reordered',fn,'post',function()error('shifted')end,{parameters=params,order={'X','ReturnValue'}}))
assert(not C.startup('events',function()error('native travel hook missing')end))
assert(not pcall(C.require_startup,'events'))
assert(C.startup('optional',function()end) and C.snapshot()['startup.optional'].available)
assert(C.startup('events',function()end));C.require_startup('events')
-- Real save/terrain entry points must reject layout drift before registering
-- any private property or changing pending native save pointers.
local path='/Script/SkiResortSimulator.GameSessionSubsystem'
class(path,{property('PendingInitialSave','ObjectProperty',0x70),
 property('PendingScenario','ObjectProperty',0x78),property('OnNewGameStarted','MulticastInlineDelegateProperty',0xB8)})
local session={PendingInitialSave='keep save',PendingScenario='keep scenario'}
FindFirstOf=function()return session end
PropertyTypes={}
local registrations=0
RegisterCustomProperty=function()registrations=registrations+1 end
local Saves=require('saves')
assert(not pcall(Saves.prepare_new,{metadata={name='test'}}))
assert(not pcall(Saves.start_new,{id='test.map'}))
assert(registrations==0 and session.PendingInitialSave=='keep save' and session.PendingScenario=='keep scenario')
local Native=require('native_terrain')
assert(not Native.install() and registrations==0,'unsafe terrain custom properties were registered')
assert(not pcall(Native.prepare_world,{}) and registrations==0,'unsafe world was staged before checking layout drift')
print('Runtime compatibility: reflected types, inheritance, private offsets, function signatures, isolated hooks and pre-write guards OK')
