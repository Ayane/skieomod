package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local G=require('surface_lift_geometry');local Jobs=require('surface_lift_cable_jobs')
local d={name='test',route={{0,0,0},{0,50000,1000}},kind='fixed_platter',speed_mps=2,capacity_per_hour=600,pylons=4}
local r=G.route(d,function(_,y)return y/50 end);local supports=G.supports(r,d.pylons,d.kind,d)
local publications=0;local item={route=r,supports=supports,loads={},cable_component={CreateMeshSection=function(_,_,vertices,triangles)publications=publications+1;assert(#vertices>100 and #triangles>100)end}}
local state={items={item}};local ticks=0;local clock=function()ticks=ticks+.0005;return ticks end
Jobs.step(state,1,clock);assert(item.cable_job and publications==0,'Complete cable was rebuilt in one frame')
for i=1,300 do Jobs.step(state,1+i*.01,clock);if publications>0 then break end end
assert(publications==1 and not item.cable_job)
Jobs.step(state,10,clock);assert(publications==1 and not item.cable_job,'Unchanged load rebuilt a cable')
print('Cable jobs: bounded work, atomic publication and unchanged-load suppression OK')

local full=G.cable_mesh(r,supports)
local static=G.cable_mesh(r,supports,nil,d,nil,{static=true})
local vertices,triangles=#static.vertices,#static.triangles
for i=1,#supports-1 do
 local m=G.cable_mesh(r,supports,nil,d,nil,{low=supports[i].distance,high=supports[i+1].distance})
 vertices=vertices+#m.vertices;triangles=triangles+#m.triangles
end
assert(vertices==#full.vertices and triangles==#full.triangles,'Span partition changed cable geometry')
local section_publications=0
item.cable_component.CreateMeshSection=function()section_publications=section_publications+1 end
item.cable_sections={}
for i=1,2 do item.cable_sections[i]={section=i,range={low=(i-1)*r.length/2,high=i*r.length/2}}end
for i=1,400 do
 local before=section_publications;Jobs.step(state,30+i*.01,clock)
 assert(section_publications-before<=1,'Multiple native mesh uploads happened in one frame')
 if section_publications==2 then break end
end
assert(section_publications==2)
print('Cable spans: exact complete rope partition and one bounded native publication per frame OK')
