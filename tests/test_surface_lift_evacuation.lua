package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={GetAddress=function()return 1 end,IsValid=function()return true end}
package.preload.UEHelpers=function()return{GetWorld=function()return world end}end
local G=require('surface_lift_geometry');local R=require('surface_lift_evacuation_routes')
local function object(address,name)
 return{IsValid=function()return true end,GetWorld=function()return world end,GetAddress=function()return address end,
  GetClass=function()return{GetAddress=function()return address+1 end}end,GetFullName=function()return name or'test'end}
end
local groom=object(20,'GroomingSubsystem test')
FindAllOf=function(name)return name=='GroomingSubsystem'and{groom}or{}end
local function id(n)return{A=n,B=2,C=3,D=4}end
local function key(g)return string.format('%08x-%08x-%08x-%08x',g.A,g.B,g.C,g.D)end
local guests=object(30);guests.Guests={{GuestId=id(-1)}}
guests.GuestsHot={{ActivityState=3,CurrentTrailId=0,WorldPosition={X=350,Y=10000,Z=2000}}}
guests.Guests.GetArrayNum=function(t)return #t end;guests.GuestsHot.GetArrayNum=function(t)return #t end
local released=0
function guests:OnLiftDeleted(_,reason)
 assert(reason==0);released=released+1
 for _,h in ipairs(self.GuestsHot)do h.ActivityState=1 end
end
local definition={name='test',route={{0,0,0},{0,20000,4000}},kind='fixed_platter',pylons=2,speed_mps=2,capacity_per_hour=600}
local route=G.route(definition,function(_,y)return y*.2 end)
local choices=R.build(route,definition,function(_,y)return y*.2 end);choices[1].trail=100
local lift=object(50);lift.OperatingSpeed=200;lift.GetLiftId=function()return id(10)end;lift.GetEffectiveOperatingSpeed=function()return 0 end
local item={id='lift',lift=lift,definition=definition,route=route,groom_trail=100,requested_speed=0,evacuation_routes=choices}
local saved={}
local state={items={item},guests=guests,groom_trails=object(40),evacuation_records={},api={log=function()end,mod_state=function()return saved end}}
local open,remove,loadlib=io.open,os.remove,package.loadlib
local storage,waits={},{}
io.open=function(path,mode)
 if mode=='wb'then return{write=function(_,bytes)storage[path]=bytes end,close=function()end}end
 if not storage[path]then return nil end
 return{read=function()return storage[path]end,close=function()end}
end
os.remove=function(path)storage[path]=nil end
package.loadlib=function(_,symbol)return function()
 local name=symbol=='skieo_surface_wait'and'wait'or'evacuation';local path
 for p in pairs(storage)do if p:match('surface%-'..name..'%.job$')then path=p end end
 assert(path);local status=path:gsub('%.job$','.status');assert(not storage[status],'Stale result reused')
 local magic,version,count=string.unpack('<c4I4I4',storage[path]);assert(version==(name=='wait'and 2 or 1))
 if name=='wait'then
  assert(magic=='SKWT'and #storage[path]==2208);local ids={}
  for i=1,count do local id,blocked=string.unpack('<i4I4',storage[path],33+(i-1)*8);if blocked==1 then ids[#ids+1]=id end end
  waits[#waits+1]=ids
 else
  assert(magic=='SKEV'and #storage[path]==64+count*48)
  for i=1,count do
   local index,a,b,c,d,trail=string.unpack('<I4I4I4I4I4i4',storage[path],65+(i-1)*48)
   assert(index==0 and a==0xffffffff and b==2 and c==3 and d==4,'Wrong native guest identity')
   local h=guests.GuestsHot[index+1];assert(h.ActivityState==1,'Native seats were not released first');h.ActivityState=4;h.CurrentTrailId=trail
  end
 end
 storage[status]='ok: native test result'
end end
local E=require('surface_lift_evacuation')
local guest=guests.Guests[1].GuestId
E.release(state,item,{{index=0,guest=guest,key=key(guest),X=350,Y=10000,Z=2000}})
assert(released==1 and item.evacuation_waiting==1 and #waits==1 and waits[1][1]==100)
assert(state.evacuation_records[key(guest)]and guests.GuestsHot[1].ActivityState==4)
assert(saved.evacuation_guests['100']=='ffffffff000000020000000300000004','Saved GUID was not compact and sign-safe')
local env={paused=false,seconds=10}
E.update(state,{},env);assert(item.evacuation_waiting==1 and lift.OperatingSpeed==0)
-- Injury or another native activity must not release a snowcat while the
-- evacuated guest is still physically in its corridor.
guests.GuestsHot[1].ActivityState=6;env.seconds=11;E.update(state,{},env)
assert(item.evacuation_waiting==1 and state.evacuation_records[key(guest)])
guests.GuestsHot[1].WorldPosition.X=2000;env.paused=true;env.seconds=12;E.update(state,{},env)
assert(item.evacuation_waiting==1,'Paused evacuation changed occupancy')
env.paused=false;env.seconds=13;E.update(state,{},env)
assert(item.evacuation_waiting==0 and not next(state.evacuation_records)and lift.OperatingSpeed==0,'Manual stop was lost after clearance')
assert(#waits[#waits]==0,'Native snowcat gate did not reopen')
-- Native array compaction cannot transfer occupancy to a different guest.
state.evacuation_records[key(guest)]={lift='lift',trail=100};item.requested_speed=1;item.evacuation_waiting=1
guests.Guests[2]=guests.Guests[1];guests.Guests[1]={GuestId=id(99)}
guests.GuestsHot[2]=guests.GuestsHot[1];guests.GuestsHot[1]={ActivityState=1,CurrentTrailId=0,WorldPosition={X=350,Y=10000,Z=2000}}
env.seconds=14;E.update(state,{},env)
assert(item.evacuation_waiting==0 and lift.OperatingSpeed==200,'Compaction held the wrong guest or prevented restart')
-- Once a skier leaves the shared service stem, hold only their forest exit.
-- The service snowcat may resume while the escape-route snowcat stays put.
local escape={index=1,trail=200,points={{x=350,y=15000,z=3000},{x=5000,y=12000,z=2400}}}
choices[2]=escape
guests.Guests[1]={GuestId=guest};guests.Guests[2]=nil
guests.GuestsHot[1]={ActivityState=4,CurrentTrailId=200,WorldPosition={X=4000,Y=12645,Z=2500}};guests.GuestsHot[2]=nil
state.evacuation_records[key(guest)]={lift='lift',trail=200};env.seconds=14.5;E.update(state,{},env)
assert(item.evacuation_waiting==0 and escape.evacuation_waiting==1,'Escape occupancy held the wrong corridor')
assert(#waits[#waits]==1 and waits[#waits][1]==200,'Native escape-route snowcat was not held')
guests.GuestsHot[1].WorldPosition.X=10000;guests.GuestsHot[1].ActivityState=1
env.seconds=15;E.update(state,{},env)
assert(escape.evacuation_waiting==0 and #waits[#waits]==0,'Forest exit did not reopen after clearance')
-- Restoring a save can briefly expose no native guests. Keep the persisted
-- evacuation gate during that grace period, then discard a departed GUID.
state.evacuation_records[key(guest)]={lift='lift',trail=100};state.evacuation_restore_until=20
guests.Guests[1]=nil;guests.Guests[2]=nil;guests.GuestsHot[1]=nil;guests.GuestsHot[2]=nil
env.seconds=15.5;E.update(state,{},env);assert(item.evacuation_waiting==1)
env.seconds=21;E.update(state,{},env);assert(item.evacuation_waiting==0 and not next(state.evacuation_records))
E.dispose(state);assert(#waits[#waits]==0,'Disposed corridor policy remained active')
io.open,os.remove,package.loadlib=open,remove,loadlib
print('Surface evacuation: native release ordering, signed GUIDs, occupied/injured/pause gates, compaction, manual stop and save restoration grace OK')
