-- A pair of parallel lifts owns one maintenance/evacuation corridor. Its
-- centre follows both axes and its edges keep clear of either row of pylons.
local G=require('surface_lift_geometry')
local Service={}
function Service.prepare(definitions,ground)
 local groups,prepared={},{}
 for _,d in ipairs(definitions)do if d.service_group then
  local group=groups[d.service_group]or{};groups[d.service_group]=group;group[#group+1]=d
 end end
 for key,definitions in pairs(groups)do
  assert(#definitions==2,'A shared service group needs two parallel lifts')
  table.sort(definitions,function(a,b)return a.name<b.name end)
  local routes={G.route(definitions[1],ground),G.route(definitions[2],ground)}
  assert(math.abs(routes[1].length-routes[2].length)<math.max(routes[1].length,routes[2].length)*.1,'Shared lifts have different lengths')
  local fractions={[0]=true,[1]=true};local width=500
  for _,route in ipairs(routes)do
   for i=0,math.ceil(route.length/3000)do fractions[math.min(1,i*3000/route.length)]=true end
   for _,p in ipairs(route.nodes)do fractions[G.nearest(route,p.x,p.y)/route.length]=true end
  end
  -- Check the whole pair, including bends, rather than just its terminals.
  for i=0,math.ceil(routes[1].length/200)do
   local t=math.min(1,i*200/routes[1].length)
   local a,b=G.sample(routes[1],t*routes[1].length),G.sample(routes[2],t*routes[2].length)
   assert(math.cos(a.yaw-b.yaw)>.8,'Shared lifts must run in the same direction')
   local gap=math.abs((b.x-a.x)*a.nx+(b.y-a.y)*a.ny)
   assert(gap<=1500,'Shared lifts are too far apart')
   width=math.min(width,gap-200)
  end
  assert(width>=200,'Shared service corridor cannot clear both rows of pylons')
  local order={};for f in pairs(fractions)do order[#order+1]=f end;table.sort(order)
  local points={}
  for _,f in ipairs(order)do
   local a,b=G.sample(routes[1],f*routes[1].length),G.sample(routes[2],f*routes[2].length)
   local x,y=(a.x+b.x)*.5,(a.y+b.y)*.5
   if #points==0 or(x-points[#points][1])^2+(y-points[#points][2])^2>1 then points[#points+1]={x,y,assert(ground(x,y))}end
  end
  local d={name=key,route=points,ascent_side='right',service_width_m=width/100,service_offset_m=0}
  local geometry={};for k,v in pairs(definitions[1])do geometry[k]=v end
  geometry.route=points;geometry.service_group=nil;geometry.evacuation_routes=nil;geometry.ascent_side='right'
  local shared={key=key,name=definitions[1].name..' & '..definitions[2].name,definition=d,route=G.route(geometry,ground),members={},width=width}
  for _,definition in ipairs(definitions)do prepared[definition]=shared end
 end
 return prepared
end
function Service.geometry(item)
 local shared=item.service
 return shared and shared.route or item.route,shared and shared.definition or item.definition
end
function Service.held(item)
 local count=0
 for _,member in ipairs(item.service and item.service.members or{item})do
  if not member.disposed then count=count+(member.evacuation_waiting or 0)end
 end
 return count
end
return Service
