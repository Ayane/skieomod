package.path='mod/SkiEO-Veymont/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local queued={}
local view,position,control,cached
local function valid()return true end
local camera={IsValid=valid,K2_SetWorldRotation=function(_,rotation)view=rotation end}
local player={IsValid=valid,FollowCamera=camera,
 K2_SetActorLocationAndRotation=function(_,location)position=location end}
local controller={IsValid=valid,SetControlRotation=function(_,rotation)control=rotation end}
package.preload.UEHelpers=function()return{
 GetWorld=function()return{IsValid=valid,GetFullName=function()return'Test world'end}end,
 GetPlayer=function()return player end,GetPlayerController=function()return controller end,
}end
package.preload.native_terrain=function()return{retain_texture=function()end,
 set_camera_rotation=function(_,rotation)cached=rotation end}end
package.preload.climate=function()return{apply=function()end}end
package.preload.snowmaking=function()return{definitions=function()return{}end,install=function()end}end
package.preload.vegetation=function()return{unload=function()end}end
ExecuteInGameThread=function(fn)queued[#queued+1]=fn end
local colors,calls
local api={game={set_trail_rating_system=function(_,options)colors=options;calls=(calls or 0)+1 end},
 hold_loading=function()return function()end end,every=function()end,after=function()end,
 read_asset=function()return''end}
local map=assert(loadfile('mod/SkiEO-Veymont/Scripts/main.lua'))()
map.on_event('map.ready',{restored=false},api)
assert(#queued==2 and calls==1)
queued[1]()
assert(view and control and position and cached,'Opening view did not update cached native view, component and controller')
assert(view.Pitch==control.Pitch and view.Yaw==control.Yaw)
local data=require('veymont_data')
local dx,dy,dz=data.ticket_office.X-position.X,data.ticket_office.Y-position.Y,data.ticket_office.Z-position.Z
local yaw,pitch=math.rad(view.Yaw),math.rad(view.Pitch)
local facing=(dx*math.cos(yaw)*math.cos(pitch)+dy*math.sin(yaw)*math.cos(pitch)+dz*math.sin(pitch))
 /math.sqrt(dx*dx+dy*dy+dz*dz)
assert(facing>.95,'Opening camera faces away from the base area')
local config=require('trail_ratings').validate(colors)
assert(config.color_mask==15 and config.style==-1 and config.count==0)
assert(config.colors[1]==0x008000 and config.colors[2]==0x0080FF and config.colors[3]==0xFF0000 and config.colors[4]==0)
local counts={0,0,0,0};local levels={}
for _,trail in ipairs(data.trails)do counts[trail.difficulty+1]=counts[trail.difficulty+1]+1;levels[trail.name]=trail.difficulty end
assert(counts[1]==4 and counts[2]==6 and counts[3]==7 and counts[4]==3,'Veymont lost its four piste levels')
for _,name in ipairs({'Cerf','Le Mur','Les Bouquetins','Les Chamois','Les Myrtilles','Les Tétras','Marmottes'})do
 assert(levels[name]==2,'Red piste classified as blue: '..name)
end
-- Palette applies to saved games as well; their saved camera is preserved.
queued={};view=nil;control=nil;position=nil;cached=nil
map.on_event('map.ready',{restored=true},api)
assert(calls==2 and #queued==0 and not view and not control and not position and not cached)
print('Veymont: French four-level palette, seven OSM red pistes, opening view towards the resort and saved camera preservation OK')
