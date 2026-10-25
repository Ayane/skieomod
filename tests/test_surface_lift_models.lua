package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Mesh=require('portable_mesh');local Models=require('surface_lift_models');local Api=require('api')
local function read(path)local f=assert(io.open(path,'rb'));local b=f:read('*a');f:close();return b end
-- Capture the actual stock bank, rather than duplicating its role mappings.
local source=read('mod/SkiEO-SurfaceLifts/Scripts/main.lua')
local defaults=assert(load(assert(source:match('^(.-)\nreturn function'))..'\nreturn models'))()
local paths={};for _,path in pairs(defaults)do paths[#paths+1]=path end
local default_reads,map_reads={},{}
local mod=Api.new({}, {id='community.surface-lifts',content={assets=paths},__read=function(path)
 default_reads[path]=(default_reads[path]or 0)+1;return read('mod/SkiEO-SurfaceLifts/'..path)
end})
local tower=read('mod/SkiEO-SurfaceLifts/Assets/tower.skpm')
local custom=tower:sub(1,16)..string.pack('<f',99)..tower:sub(21)
local map_files={['Assets/tower.skpm']=custom,['Assets/pulley.skpm']=read('mod/SkiEO-SurfaceLifts/Assets/guide-wheel.skpm'),
 ['Assets/palette.png']=read('mod/SkiEO-SurfaceLifts/Assets/palette.png')}
local map_paths={};for path in pairs(map_files)do map_paths[#map_paths+1]=path end
local map=Api.new({}, {id='test.models',content={assets=map_paths},__read=function(path)
 map_reads[path]=(map_reads[path]or 0)+1;return map_files[path]
end})
mod._session=map
local original_material=Mesh.material
Mesh.material=function(owner,path)owner:read_asset(path);return{owner=owner,path=path}end
local library=Models.new(mod,defaults)
local base=library.base
local d={pylons=4,models={tower='Assets/tower.skpm',palette='Assets/palette.png'},
 pylon_models={{index=2,models={guide_wheel='Assets/pulley.skpm',palette='Assets/palette.png'}}}}
local appearance=library:definition(d)
assert(appearance.bank.models.tower.vertices[1].X==99)
assert(base.models.tower.vertices[1].X~=99,'Map/model paths collided across package namespaces')
assert(appearance.bank.models.drive==base.models.drive and appearance.bank.models.platter==base.models.platter)
assert(appearance.bank.material.owner==map and base.material.owner==mod)
assert(appearance.pylons[2].models.tower==appearance.bank.models.tower)
assert(appearance.pylons[2].models.guide_wheel~=base.models.guide_wheel)
assert(appearance.pylons[2].material==appearance.bank.material,'Palette was imported twice')
assert(library:definition({pylons=2}).bank==base,'Unmodified maps lost their original bank')
assert(library:definition(d).bank.models.tower==appearance.bank.models.tower)
for path,count in pairs(default_reads)do assert(count==1,'Default mesh was decoded repeatedly: '..path)end
for path,count in pairs(map_reads)do assert(count==1,'Custom asset was read repeatedly: '..path)end
local function refused(value,fragment)
 local ok,error=pcall(library.definition,library,value)
 assert(not ok and tostring(error):find(fragment,1,true),tostring(error))
end
refused({pylons=4,models={typo='Assets/tower.skpm'}},'Unknown lift model role')
refused({pylons=4,models={tower='../tower.skpm'}},'Invalid lift model asset path')
refused({pylons=4,models={tower='C:/tower.skpm'}},'Invalid lift model asset path')
refused({pylons=4,models={tower='Assets/tower.fbx'}},'SKPM')
refused({pylons=4,models={tower='Assets/undeclared.skpm'}},'not declared')
refused({pylons=4,pylon_models={{index=0,models={}}}},'Pylon model index')
refused({pylons=4,pylon_models={{index=5,models={}}}},'Pylon model index')
refused({pylons=4,pylon_models={{index=1,models={}},{index=1,models={}}}},'Duplicate pylon')
refused({pylons=4,pylon_models={first={index=1,models={}}}},'pylon_models must be an array')
refused({pylons=4,pylon_models={{index=1,models={drive='Assets/tower.skpm'}}}},'Unknown lift model role')
assert(base.models.tower.vertices[1].X~=99,'Invalid overrides mutated the stock bank')
Mesh.material=original_material
print('Per-lift/pylon models: package isolation, fallback, palette/mesh caching and invalid overrides OK')

-- Render pools retain the existing global carrier cap, even when the camera
-- swaps between different lifts, stock rails and shared passenger slots.
local original_actor,original_component=Mesh.actor,Mesh.component
local actors,uploads,materials=0,0,0
Mesh.actor=function()actors=actors+1;return{id=actors}end
Mesh.component=function(actor,mesh,material)
 return{actor=actor,mesh=mesh,material=material,K2_SetWorldTransform=function()end,CreateMeshSection=function(self,_,vertices)
  self.vertices=vertices;uploads=uploads+1
 end,SetMaterial=function(self,_,value)self.material=value;materials=materials+1 end}
end
local state={pool={}}
local a=Models.perch(state,1,base);local b=Models.perch(state,2,appearance.bank)
assert(Models.perch(state,1,appearance.bank)==b and Models.perch(state,2,base)==a)
assert(actors==2 and uploads==0,'Pool order changes allocated actors or uploaded meshes')
local alternate=library:bank(base,{platter='Assets/tower.skpm'})
Models.perch(state,1,alternate)
assert(actors==2 and uploads==1)
for i=1,128 do Models.perch(state,i,i%2==0 and base or appearance.bank)end
local before=uploads
for frame=1,120 do for i=1,128 do Models.perch(state,i,(i+frame)%2==0 and base or appearance.bank)end end
assert(actors==128 and #state.pool==128 and uploads==before,'Mixed models caused per-frame allocations or uploads')
local item={bank=appearance.bank,pylon_banks=appearance.pylons,visual={}}
assert(Models.support(item,1)==appearance.bank and Models.support(item,2)==appearance.pylons[2])
local Wheels=require('surface_lift_wheels')
local transform={}
local w=Wheels.add(item,state,transform,80,1,nil,Models.support(item,2))
assert(w.mesh==appearance.pylons[2].models.guide_wheel and w.material==appearance.pylons[2].material)
-- Wheel placement needs only a transform call; the role resolves at assembly.
Mesh.actor,Mesh.component=original_actor,original_component
print('Carrier pools: shared 128-slot limit, camera reordering and geometry reuse for 120 frames OK')
