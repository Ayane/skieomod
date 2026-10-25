package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local G=require('surface_lift_geometry');local R=require('surface_lift_evacuation_routes')
local d={name='test',route={{0,0,0},{0,20000,4000}},kind='fixed_platter',pylons=2,speed_mps=2,capacity_per_hour=600}
local function ground(_,y)return y*.2 end
local route=G.route(d,ground);local service=R.service(route,d)
assert(service[1].y>service[#service].y,'Evacuation must descend')
local width,offset=R.dimensions(d);assert(width==500 and offset==350)
for _,p in ipairs(service)do assert(math.abs(p.x)==350,'Service path must clear the pylons')end
local choices=R.build(route,d,ground);assert(#choices==1 and choices[1].index==0)
assert(R.choose(choices,5000)==choices[1],'Missing emergency route must use the service descent')
local x=service[1].x
d.evacuation_routes={{{x,10000,2000},{x+1000,8000,1600}},{{x,14000,2800},{x+8000,1000,200}}}
choices=R.build(route,d,ground)
local low=G.nearest(route,0,9000);local high=G.nearest(route,0,18000)
assert(R.choose(choices,low)==choices[1],'A guest below an emergency entry must never ski uphill to it')
local selected,cost=R.choose(choices,high)
assert(selected==choices[2]and cost<high,'Choose the shortest eligible exit, regardless of declaration order')
local first=choices[2].points[1];assert(first.y==service[1].y,'Native emergency trail must retain the upper service approach')
local last=choices[2].points[#choices[2].points];assert(last.y==8000 and last.x==x+1000)
for _,choice in ipairs(choices)do
 local curves=R.curves(choice.points,width)
 for i,c in ipairs(curves)do assert(c.CorridorWidth==500);if i>1 then assert(c.StartPoint==curves[i-1].Endpoint)end end
end
d.evacuation_routes={{{x+2000,10000,2000},{x+3000,8000,1600}}}
assert(not pcall(R.build,route,d,ground),'Disconnected emergency entrance accepted')
d.evacuation_routes={{{x,10000,2000},{x,14000,2800}}}
assert(not pcall(R.build,route,d,ground),'Uphill emergency route accepted')
d.evacuation_routes={{{x,10000,2000},{x,8000,1600}}}
assert(not pcall(R.build,route,d,function()return nil end),'Off-map emergency route accepted')
d.evacuation_routes={{}}
assert(not pcall(G.validate,d),'Invalid authored route accepted')
d.evacuation_routes=nil;d.service_width_m=10
assert(not pcall(G.validate,d),'A service corridor crossing the pylons was accepted')
print('Surface evacuation routes: downhill fallback, shortest eligible emergency exit, connected native geometry and unsafe-input rejection OK')
