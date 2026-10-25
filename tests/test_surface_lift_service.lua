package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local G=require('surface_lift_geometry');local Service=require('surface_lift_service')
local function lift(name,x,group)return{name=name,route={{x,0,0},{x,10000,1000}},kind='detachable_platter',pylons=2,speed_mps=2,capacity_per_hour=600,service_group=group}end
local a,b=lift('a',0,'pair'),lift('b',600,'pair')
local prepared=Service.prepare({a,b},function(_,y)return y/10 end)
local shared=assert(prepared[a]);assert(shared==prepared[b]and shared.width==400)
for _,p in ipairs(shared.route.points)do assert(math.abs(p.x-300)<.01)end
assert(Service.geometry({service=shared})==shared.route)
shared.members={{evacuation_waiting=2},{evacuation_waiting=3},{evacuation_waiting=9,disposed=true}}
assert(Service.held({service=shared})==5,'Either lift must hold the common snowcat job')
assert(not pcall(Service.prepare,{a},function()return 0 end))
b.route={{600,10000,1000},{600,0,0}};assert(not pcall(Service.prepare,{a,b},function()return 0 end))
local json=require('json');local f=assert(io.open('mod/SkiEO-Veymont/custom-map.json'));local m=json.decode(f:read('*a'));f:close()
local defs=m.extensions['community.surface-lifts'].lifts
local groups=Service.prepare(defs,function()return 0 end);local seen={}
for _,d in ipairs(defs)do if groups[d]then seen[groups[d].key]=groups[d].width end end
assert(seen.Pras>290 and seen.Pras<310 and seen.Bessards>370 and seen.Bessards<400)
print('Shared lift corridors: native group identity, pylon clearance, occupancy and Veymont pairs OK')
