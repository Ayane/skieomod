package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local json=require('json');local G=require('surface_lift_geometry')
local function read(path)local f=assert(io.open(path,'rb'));local s=f:read('*a');f:close();return json.decode(s)end
local base='repository/web/public/tutorials/surface-lifts/files/'
local options=read(base..'surface-lifts-options.json');local scene=read(base..'objects.json')
local d=assert(options.lifts[1]);G.validate(d)
local native=scene.objects[1]
assert(native.name==d.name)
for axis=1,2 do
 assert(native.position[axis]*100==d.route[1][axis])
 assert(native.end_position[axis]*100==d.route[#d.route][axis])
end
local route=G.route(d,function(_,y)return 20000-y*.1875 end)
local supports=G.supports(route,d.pylons,d.kind,d)
assert(#supports==d.pylons+2,'tutorial pylon count differs from the loader')
assert(route.length>48000 and route.length<50000,'tutorial route length or centimetre units changed')
print('Surface lift tutorial: real API validation, scene matching, route units and intermediate supports OK')
