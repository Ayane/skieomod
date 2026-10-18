package.path = 'mod/SkiEO-CustomMaps/Scripts/?.lua;' .. package.path
local world = {GetAddress=function() return 1 end,IsValid=function() return true end}
local other = {GetAddress=function() return 2 end,IsValid=function() return true end}
package.preload.UEHelpers=function() return {GetWorld=function() return world end} end
package.preload.terrain=function() return {} end
local changes={}
local actor={IsValid=function() return true end,GetWorld=function() return world end,
 SetActorHiddenInGame=function(_,hidden) changes[#changes+1]=hidden end,
 K2_DestroyActor=function() end}
local level=0
local stale={IsValid=function() return true end,GetWorld=function() return other end,
 GetObstacleFadeLevel=function() error('previous world overlay queried') end}
local overlay={IsValid=function() return true end,GetWorld=function() return world end,
 GetObstacleFadeLevel=function() return level end}
FindAllOf=function(class) assert(class=='TerrainOverlaySubsystem');return {stale,overlay} end
ExecuteInGameThread=function(callback) callback() end
local Vegetation=require('vegetation');Vegetation.actor=actor;Vegetation.overlay=stale
Vegetation.sync_visibility();assert(changes[1]==false)
Vegetation.sync_visibility();assert(#changes==1,'unchanged visibility dirties render state')
level=1;Vegetation.sync_visibility();assert(changes[2]==true)
level=0;Vegetation.sync_visibility();assert(changes[3]==false)
Vegetation.unload();assert(Vegetation.overlay==nil and Vegetation.hidden==nil)
level=1;Vegetation.actor=actor;Vegetation.sync_visibility();assert(changes[4]==true,'initially hidden view ignored')
actor.GetWorld=function() return other end
level=0;Vegetation.sync_visibility();assert(#changes==4,'previous world actor changed')
print('Portable forest visibility: native fade, initial state, restored world and no redundant updates OK')
