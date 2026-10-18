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
  SlotName=str('test.slot'),PlaythroughId=id}
end
objects={saved(fresh)}
local restored=Saves.find_restore({other,map})
assert(restored.map==map and not restored.legacy,'saved map identity followed selection order')
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
for path in pairs(tracked) do os.remove(path) end
io=actual_io
print('Custom map saves: fresh identities, persistent association, legacy migration and stock isolation OK')
