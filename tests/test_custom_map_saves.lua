package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local root=os.tmpname();os.remove(root)
local objects,registered={},{}
local session={IsValid=function() return true end}
local function str(value) return {ToString=function() return value end} end
local fresh='11111111-22222222-33333333-44444444'
local guid_library={NewGuid=function() return fresh end,
 Conv_GuidToString=function(_,value) return str(value) end}
local dump={GetSaveGamesDir=function() return str('/tmp') end}
-- Use a task-specific filename prefix while exercising actual metadata IO.
local actual_io=io
local tracked={}
io=setmetatable({open=function(path,mode)
 local rewritten=path:gsub('/tmp/SkiEO%-CustomMap%-',root..'-')
 tracked[rewritten]=true
 return actual_io.open(rewritten,mode)
end},{__index=actual_io})
package.preload.UEHelpers=function() return {} end
-- Reflection safety has its own engine-contract fixtures; this one tests IO.
package.preload.compatibility=function() return {require=function()end} end
StaticFindObject=function(name) return name:find('KismetGuid') and guid_library or dump end
FindFirstOf=function(name) assert(name=='GameSessionSubsystem');return session end
FindAllOf=function(name) assert(name=='SkiResortSaveGame');return objects end
PropertyTypes={UInt32Property='uint32',ByteProperty='byte',StrProperty='string'}
RegisterCustomProperty=function(def)
 assert(def.BelongsToClass=='/Script/SkiResortSimulator.GameSessionSubsystem')
 registered[#registered+1]=def.OffsetInternal
end
local Saves=require('saves')
local map={id='test.first'}
local other={id='test.second'}
map.metadata={name='Fresh resort'};session.PendingInitialSave='stock';session.PendingScenario='stock'
Saves.prepare_new(map)
assert(session.SkiEOPendingNewGame==1 and session.SkiEOPendingLoadSlot=='' and session.SkiEOPendingResortName=='Fresh resort')
assert(not session.PendingInitialSave and not session.PendingScenario)
assert(#registered==3 and registered[1]==0x30 and registered[2]==0x41 and registered[3]==0x48)
registered={}
local guid=Saves.start_new(map)
assert(guid=='11111111222222223333333344444444')
assert(#registered==4 and registered[1]==0xA0 and registered[4]==0xAC)
assert(session.SkiEOPlaythroughWord0==0x11111111 and session.SkiEOPlaythroughWord3==0x44444444)
local function saved(id,path)
 return {IsValid=function() return true end,MapPath=str(path or '/Engine/Maps/Entry'),
  SlotName=str('test.slot'),PlaythroughId=id,
  Buildings={ForEach=function()end},Lifts={ForEach=function()end}}
end
objects={saved(fresh)}
local restored=Saves.find_restore({other,map})
assert(restored.map==map and not restored.legacy,'saved map identity followed selection order')
objects[1].bSandboxMode=true
assert(Saves.find_restore({other,map}).sandbox,'native save lost sandbox mode')
objects[1].bSandboxMode=false
assert(not Saves.find_restore({other,map}).sandbox,'normal save acquired sandbox mode')
assert(not pcall(Saves.find_restore,{other}),'missing saved map was replaced silently')
assert(not pcall(Saves.bind,guid,other),'association was overwritten')
local legacy='55555555-66666666-77777777-88888888'
objects={saved(legacy)}
assert(not pcall(Saves.find_restore,{map,other}),'ambiguous legacy save was guessed')
restored=Saves.find_restore({map})
assert(restored.map==map and restored.legacy)
assert(not Saves.find_restore({other,map}).legacy,'legacy association did not persist')
objects={saved(legacy,'/Game/Maps/Generated/Map_sugar_bowl_real')}
assert(not Saves.find_restore({map}),'stock save was treated as custom')
objects={saved(fresh),saved('99999999-AAAAAAAA-BBBBBBBB-CCCCCCCC')}
Saves.bind('99999999aaaaaaaabbbbbbbbcccccccc',other)
assert(not pcall(Saves.find_restore,{map,other}),'conflicting live save candidates were ignored')
local notify
NotifyOnNewObject=function(class,callback)
 assert(class=='/Script/SkiResortSimulator.SkiResortSaveGame');notify=callback
end
Saves.install()
notify(objects[2])
assert(Saves.find_restore({map,other}).map==other,'stale save objects overrode the loaded map')
notify(saved(legacy,'/Game/Maps/Generated/Map_sugar_bowl_real'))
assert(not Saves.find_restore({map,other}),'old custom save overrode a stock load')
local function array(values)
 return {ForEach=function(_,callback) for i,value in ipairs(values) do callback(i,{get=function() return value end}) end end}
end
local building_id='12345678-00000000-00000000-00000001'
local lift_id='12345678-00000000-00000000-00000002'
local base={ID=building_id,DisplayName=str(''),Transform={Translation={X=1,Y=2,Z=3}}}
local lift_base={ID=lift_id,DisplayName=str('Custom lift'),Transform={Translation={X=10,Y=20,Z=30}}}
local entries=Saves.read_placeables({Buildings=array({{BaseData=base}}),Lifts=array({{BaseData=lift_base}})})
local key=lift_id:gsub('[^%x]',''):lower()
lift_base.Transform.Translation.Z=-900
assert(entries[key].position.Z==30,'saved transform retained a native wrapper')
assert(entries[building_id:gsub('[^%x]',''):lower()].name=='','empty native label was discarded')
assert(not pcall(Saves.read_placeables,{Buildings=array({{BaseData=base},{BaseData=base}}),Lifts=array({})}),
 'duplicate saved identities were accepted')
lift_base.Transform.Translation.Z=0/0
assert(not pcall(Saves.read_placeables,{Buildings=array({}),Lifts=array({{BaseData=lift_base}})}),
 'non-finite origin was accepted')
local root={Mobility=0,IsValid=function()return true end,GetAddress=function()return 123 end}
root.SetMobility=function(self,value)self.Mobility=value end
local position={X=10,Y=20,Z=45}
local child_pose={Translation={X=15,Y=25,Z=50},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}}
local child={Mobility=0,GetAttachParent=function()return root end,K2_GetComponentToWorld=function()return child_pose end}
child.SetMobility=root.SetMobility
child.K2_SetWorldTransform=function(_,pose)child_pose=pose end
local actor={RootComponent=root,GetPlaceableId=function()return lift_id end,
 IsA=function(_,class)return class=='/Script/SkiResortSimulator.LiftActor' end,
 K2_GetActorLocation=function()return position end,K2_GetComponentsByClass=function()return {child} end,
 SetInstanceName=function(self,name)self.name=name end}
actor.K2_SetActorLocation=function(_,value)
 -- Model the attached terminal moving with its root. The saved origin repair
 -- must preserve this geometry and must not retain a live transform view.
 child_pose.Translation.Z=child_pose.Translation.Z+value.Z-position.Z
 position={X=value.X,Y=value.Y,Z=value.Z}
end
FText=function(value)return value end
Saves.restore_placeable(actor,entries)
assert(position.Z==30 and child_pose.Translation.Z==50,'origin repair moved the grounded terminal')
assert(root.Mobility==0 and child.Mobility==0 and actor.name=='Custom lift')
actor.GetPlaceableId=function()return building_id end
Saves.restore_placeable(actor,entries)
assert(actor.name=='' and position.Z==30,'empty name was replaced or a building was moved')
actor.GetPlaceableId=function()return fresh end
actor.name='Unrelated';Saves.restore_placeable(actor,entries)
assert(actor.name=='Unrelated','missing/deleted save entries changed another actor')
actor.GetPlaceableId=function()return lift_id end
position.Z=45;actor.K2_SetActorLocation=function()error('engine refused movement')end
assert(not pcall(Saves.restore_placeable,actor,entries),'movement failure was ignored')
assert(root.Mobility==0 and child.Mobility==0,'movement failure left movable components')
-- Native saves from before the marker rename carry their old variant in
-- CustomData. Preserve it as plain Lua data and apply its available alias.
local variant_entries=Saves.read_placeables({Buildings=array({{BaseData=base,
 CustomData={[str('Variant')]=str('Expert')}}}),Lifts=array({})})
local building_key=building_id:gsub('[^%x]',''):lower()
assert(variant_entries[building_key].variant=='Expert','native variant was discarded during world travel')
local native_map={ForEach=function(_,callback)
 callback({get=function()return str('Variant')end},{get=function()return str('Expert')end})
end}
local native_entries=Saves.read_placeables({Buildings=array({{BaseData=base,CustomData=native_map}}),Lifts=array({})})
assert(native_entries[building_key].variant=='Expert','reflected native TMap could not be read')
actor.GetPlaceableId=function()return building_id end
actor.IsA=function(_,class)return class=='/Game/Blueprints/Decorations/BP_TrailMarkers.BP_TrailMarkers_C' end
actor.Variants=array({{Id=str('BlackDiamond')}})
actor.ApplyVariant=function(self,id)self.VariantId=str(id)end
package.loaded.UEHelpers.FindOrAddFName=function(value)return value end
Saves.restore_placeable(actor,variant_entries)
assert(actor.VariantId:ToString()=='BlackDiamond','old native save did not migrate its marker variant')
for path in pairs(tracked) do os.remove(path) end
io=actual_io
print('Custom map saves: fresh identities, persistent association, legacy migration and stock isolation OK')
