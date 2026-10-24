-- Optional live acceptance driver for compatibility/ue4ss_probe.lua review mode.
-- Run only in the protocol's isolated game and save directory, after starting
-- packaged Veymont 0.8.0. It spawns visitors, renames/deletes test lifts, saves,
-- opens the native load menu and verifies restored GUIDs after forced GC.
-- Every action runs on the UE4SS game thread; no window focus/input is required.
local Q=assert(SkiEOCompatibilityProbe);local H=Q.helpers;local G=require('surface_lift_geometry')
local D={phase='loading',deadline=os.time()+1200,tracked={},exits={},samples=0,min_clearance=1e9,max_clearance=-1e9,
 pose_samples=0,max_sole_error=0,max_grip_error=0,disciplines={}}
_G.SurfaceLiftQA=D
local function current(name)
 for _,a in ipairs(FindAllOf(name) or {}) do if a:IsValid() and not a:GetFullName():find('Default__',1,true) then
 local w=a:GetWorld();if w and w:IsValid() and w:GetAddress()==H.GetWorld():GetAddress() then return a end end end
end
local function id(g) return string.format('%08x-%08x-%08x-%08x',g.A,g.B,g.C,g.D) end
local function status()
 local api=Q.runtime.active_api;local s=assert(api._surface_lifts);local rows={}
 for _,i in ipairs(s.items) do if not i.disposed then local a=i.lift
  rows[#rows+1]={kind=i.definition.kind,id=i.id,name=a:GetInstanceName():ToString(),definition=i.definition.name,capacity=a:GetBoardingCapacity(),
    class=a:GetClass():GetFullName(),riders=a:GetActiveRiderCount(),total=a:GetTotalGuestRidersAllTime(),chairs=a.ChairISM:GetInstanceCount(),
    length=a:GetCableLength(),up=a:GetUphillCableLength(),route=i.route.length,pylons=#i.supports-2,standing=a.ChairMesh.Sockets:GetArrayNum()}
 end end
 return rows
end
local function capture(name)
 Q.write('review/'..name..'.json',{lifts=status(),world=Q.snapshot(),samples=D.samples,min_clearance=D.min_clearance,
 max_clearance=D.max_clearance,exits=D.exits,mod_state=Q.runtime.active_api:state()})
 Q.screenshot('review/'..name)
end
local function checkpoint(name)
 local report=require('scenario_qa').capture(Q.runtime,name)
 report.compatibility_world=Q.snapshot()
 Q.write('review/'..name..'.json',report)
end
RegisterCustomProperty({Name='SkiEOCompatPendingSlot',Type=PropertyTypes.StrProperty,BelongsToClass='/Script/SkiResortSimulator.SaveLoadMenuWidget',OffsetInternal=0x5D0})
RegisterCustomProperty({Name='SkiEOCompatConfirmAction',Type=PropertyTypes.ByteProperty,BelongsToClass='/Script/SkiResortSimulator.SaveLoadMenuWidget',OffsetInternal=0x608})
D.tick=function()
 local ok,err=xpcall(function()
 if D.phase=='done' or D.phase=='failed' then return end
 assert(os.time()<D.deadline,'surface lift QA timed out in '..D.phase)
 local api=Q.runtime.active_api
 if D.phase=='loading' then
  if not api or not api._loading_success or not api._surface_lifts or require('loading').active then return end
  local s=api._surface_lifts;assert(#s.items==9,'packaged mapmod did not adapt eight surface lifts and the chairlift')
  local w=Q.snapshot();assert(w.lifts==9 and w.staff==22,'native resort incomplete')
  local two=0;for _,a in ipairs(FindAllOf('BP_FixedChair2_C') or {}) do if a:IsValid() and a:GetWorld():GetAddress()==H.GetWorld():GetAddress() then two=two+1;assert(a:GetBoardingCapacity()==2) end end
  assert(two==1,'Blanchon is not a two-seat chairlift')
  local time=current('TimeSubsystem');time:ResumeTime();time:SetTimeRate(3);time:SetDayNightPhase(.48);time:SetTimeOfDayHeld(true)
  H.GetGameplayStatics():SetGamePaused(H.GetWorld(),false)
  local guests=current('GuestSimulationSubsystem')
  for _,i in ipairs(s.items) do if i.definition.name=='Bessards 1' or i.definition.name=='Pré Levé' then guests:SpawnGuests(i.lift:GetBottomTerminalLocation(),60) end end
  local p=s.items[2].route.points[1];api:focus_camera(p.x,p.y,p.z+250,2800)
  H.GetKismetSystemLibrary():ExecuteConsoleCommand(H.GetWorld(),'r.ScreenPercentage 100',H.GetPlayerController())
  H.GetKismetSystemLibrary():CollectGarbage()
  D.started=os.time();D.phase='riding';capture('packaged-ready')
 elseif D.phase=='riding' then
  local s=api._surface_lifts;local byid={};for _,i in ipairs(s.items) do if i.definition.kind~='fixed_chair' then byid[i.id]=i end end
  local guests=current('GuestSimulationSubsystem')
  guests.GuestsHot:ForEach(function(index,r)
   local h=r:get();local guest_key=id(guests.Guests[index].GuestId);local previous=D.tracked[guest_key]
   if h.ActivityState==3 then
    local a=byid[id(guests.Guests[index].QueueLiftId)]
    if a then local p=h.WorldPosition;local distance=G.nearest(a.route,p.X,p.Y)
     D.tracked[guest_key]={name=a.definition.name,distance=distance,length=a.route.length}
     if distance>1000 and distance<a.route.length-1000 then
      local gap=p.Z-api:environment(p.X,p.Y).z
      D.samples=D.samples+1;D.min_clearance=math.min(D.min_clearance,gap);D.max_clearance=math.max(D.max_clearance,gap)
     end
    end
   elseif previous then
    if previous.distance>previous.length*.9 then D.exits[#D.exits+1]=previous end
    D.tracked[guest_key]=nil
   end
  end)
  local P=require('surface_lift_pose_math')
  for _,e in ipairs(s.poses or{})do if e.component:IsVisible()then
   D.max_grip_error=math.max(D.max_grip_error,e.grip_error or math.huge)
   local discipline=tostring(e.discipline);D.disciplines[discipline]=(D.disciplines[discipline]or 0)+1
   for i,side in ipairs({'L','R'})do
    -- PoseableMesh owns the freshly edited pose; the inherited SkinnedMesh
    -- accessor still returns last frame's component-space bone cache here.
    local b=e.bones['Foot_'..side].t;local t=e.component:GetBoneTransformByName(H.FindOrAddFName('Foot_'..side),0)
    local inverse={X=-b.Rotation.X,Y=-b.Rotation.Y,Z=-b.Rotation.Z,W=b.Rotation.W}
    local v=t.Translation
    local sole=P.add({X=v.X,Y=v.Y,Z=v.Z},P.rotate(t.Rotation,P.rotate(inverse,{X=0,Y=0,Z=e.sole_z-b.Translation.Z})))
    D.max_sole_error=math.max(D.max_sole_error,P.length(P.sub(sole,e.contacts[i])))
    D.pose_samples=D.pose_samples+1
   end
  end end
  Q.write('review/ride-contact-progress.json',{samples=D.samples,poses=D.pose_samples,sole_error=D.max_sole_error,grip_error=D.max_grip_error,exits=#D.exits})
  if os.time()-D.started>20 and not D.ride_shot then D.ride_shot=true;capture('packaged-riders') end
  if os.time()-D.started<90 or #D.exits<5 then return end
  assert(D.samples>100,'no meaningful rider surface samples')
  -- Native transport Z follows the coarse snow cache. It is diagnostic only:
  -- close skiers use the equipped skeleton grounded on the rendered snow.
  assert(D.pose_samples>=100 and D.max_sole_error<1,'Rendered ski soles lost their contact targets')
  assert(D.max_grip_error<3,'Towing hand does not reach the perche')
  capture('packaged-ride-verified')
  -- Persist a rename by GUID and a deletion, while preserving the other lifts.
  local doomed
  for _,i in ipairs(s.items) do
   if i.definition.name=='Pré Levé' then i.lift:SetInstanceName(FText('Pré Levé QA'));D.renamed=i.id end
   if i.definition.name=='Bessards 2' then doomed=i.lift;D.removed=i.id end
  end
  local registry=current('PlaceableRegistrySubsystem');local keep={}
  registry.Lifts:ForEach(function(_,r) local a=r:get();if a:GetAddress()~=doomed:GetAddress() then keep[#keep+1]=a end end)
  registry.Lifts=keep;doomed:K2_DestroyActor()
  api:_sync_state();D.phase='save_next';D.settle=os.time()
 elseif D.phase=='save_next' then
  if os.time()-D.settle<5 then return end
  if not D.deletion_gc then D.deletion_gc=true;H.GetKismetSystemLibrary():CollectGarbage();D.settle=os.time()-4;return end
  D.before=status();assert(#D.before==8)
  capture('packaged-save')
  checkpoint('veymont-saved')
  local session=current('GameSessionSubsystem');local words={}
  for i=0,3 do words[#words+1]=string.format('%08X',session['SkiEOPlaythroughWord'..i]) end
  D.slot=table.concat(words):sub(1,8)..'_SurfaceLiftQA'
  local ui=current('UIManagerComponent');ui.PauseMenuWidget:OnSaveGameButtonClicked()
  local menu=ui.SaveLoadMenuWidget;menu:OnSaveTabClicked();menu.NameInput:SetText(FText('SurfaceLiftQA'));menu:OnConfirmClicked()
  D.phase='saving';D.settle=os.time()
 elseif D.phase=='saving' then
  local dump=StaticFindObject('/Script/SkiResortSimulator.Default__SaveDumpLibrary')
  local dir=dump:GetSaveGamesDir():ToString():gsub('\\','/')
  local f=io.open(dir..'/'..D.slot..'.sav','rb');if not f then assert(os.time()-D.settle<45,'native save missing');return end;f:close()
  checkpoint('veymont-saved')
  D.phase='menu';H.GetGameplayStatics():OpenLevel(H.GetWorld(),H.FindOrAddFName('/Game/Maps/MainMenu'),true,'')
 elseif D.phase=='menu' then
  if not H.GetWorld():GetFullName():find('/Game/Maps/MainMenu',1,true) then return end
  local pc=H.GetPlayerController();if not pc or not pc:IsValid() or not pc.MainMenuWidget:IsValid() then return end
  pc.MainMenuWidget:OnLoadGameButtonClicked();local menu=pc.SaveLoadMenuWidget
  menu.SkiEOCompatPendingSlot=D.slot;menu.SkiEOCompatConfirmAction=1;menu:OnConfirmYes();D.phase='restoring'
 elseif D.phase=='restoring' then
  if not api or not api._loading_success or not api._surface_lifts or require('loading').active then return end
  if not D.restored_at then D.restored_at=os.time();H.GetKismetSystemLibrary():CollectGarbage();return end
  if os.time()-D.restored_at<15 then return end
  local after=status();assert(#after==8,'deleted lift returned or existing lift was lost')
  local ids={};for _,a in ipairs(after) do ids[a.id]=a end
  assert(not ids[D.removed] and ids[D.renamed].name=='Pré Levé QA','GUID binding lost player edit')
  for _,a in ipairs(D.before) do assert(ids[a.id] and ids[a.id].capacity==a.capacity and ids[a.id].standing==a.standing,'restored lift lost passenger socket') end
  checkpoint('veymont-restored-gc');capture('packaged-restored');D.phase='done'
  Q.write('review/surface-lift-result.json',{complete=true,samples=D.samples,min_clearance=D.min_clearance,max_clearance=D.max_clearance,
    exits=#D.exits,pose_samples=D.pose_samples,max_sole_error=D.max_sole_error,max_grip_error=D.max_grip_error,disciplines=D.disciplines,
    restored_lifts=#after,removed=D.removed,renamed=D.renamed,slot=D.slot,run_id=Q.spec.run_id})
 end
 end,debug.traceback)
 if not ok then D.phase='failed';Q.write('review/surface-lift-result.json',{complete=false,error=tostring(err)}) end
 return false
end
D.handle=LoopInGameThreadWithDelay(1000,D.tick)
local World=require('world');local original_finish=World.finish_loading
World.finish_loading=function(map)
 original_finish(map)
 if D.phase=='restoring' and Q.runtime.active_api and Q.runtime.active_api._restoring then
  require('scenario_qa').pause(Q.runtime)
 end
end
