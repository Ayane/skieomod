package.path='mod/SkiEO-Veymont/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function()return{GetWorld=function()return{GetAddress=function()return 1 end}end}end
local S=require('snowmaking');local definitions=S.definitions(require('veymont_data'))
local ids,counts={},{}
for _,d in ipairs(definitions)do
 assert(not ids[d.id]);ids[d.id]=true
 local trail=d.guid.B;counts[trail]=(counts[trail]or 0)+1
 assert(d.kind=='snowblower'and d.class:find('/Buildings/BP_Snowblower',1,true))
 assert(d.yaw>=-180 and d.yaw<=180 and #d.position_cm==2)
end
assert(#definitions==21 and counts[1]==14 and counts[2]==7)
local saved={};local placed=0;local configured=0
local gun={SetTargetDepthCm=function(_,v)assert(v==60);configured=configured+1 end,
 SetStartBelowTempC=function(_,v)assert(v==-2)end,SetAutomationEnabled=function(_,v)assert(v)end}
package.loaded.scene_objects={place=function(api,defs)assert(not api._restoring);placed=placed+#defs;return{gun}end}
FindAllOf=function()return{}end
local api={_restoring=true,state=function()return saved end,log=function()end}
S.install(api,require('veymont_data'));assert(placed==21 and configured==1 and saved.veymont_snowmaking_version==1)
S.install(api,require('veymont_data'));assert(placed==21,'Saved player removals were recreated')
print('Veymont snowmaking: both pistes, stable native IDs, automation and one-time save migration OK')
