-- A dependency supplies defaults; each map owns its optional model overrides.
-- Resolve and cache all data before touching native lifts, never during frames.
local Mesh=require('portable_mesh')
local Models={}
Models.roles={'platter','platter_upper','platter_shaft','platter_lower','poles_bundle','tower','angle_tower',
 'return_support','return_angle','fixed_return_support','inclined_wheel','guide_wheel','motor',
 'chair_tower','chair_head','drive','covered','return_station','release','fixed','modern','lattice','chair_drive','chair_return'}
local roles={palette=true}
for _,name in ipairs(Models.roles)do roles[name]=true end
local support_roles={tower=true,angle_tower=true,return_support=true,return_angle=true,
 fixed_return_support=true,guide_wheel=true,chair_tower=true,chair_head=true,palette=true}
local function overrides(value,allowed)
 assert(type(value)=='table','Lift models must be an object of model roles and map asset paths')
 for role,path in pairs(value)do
  assert(allowed[role],'Unknown lift model role: '..tostring(role))
  assert(type(path)=='string'and #path>0 and #path<=240 and not path:find('[%c\\:]')
   and path:sub(1,1)~='/'and not path:find('//',1,true),'Invalid lift model asset path')
  for part in path:gmatch('[^/]+')do assert(part~='.'and part~='..','Invalid lift model asset path')end
  assert(path:lower():sub(role=='palette'and -4 or -5)==(role=='palette'and '.png'or'.skpm'),
   'Lift model role '..role..' needs a '..(role=='palette'and 'PNG'or'SKPM')..' asset')
 end
end
function Models.validate(d)
 if d.models~=nil then overrides(d.models,roles)end
 if d.pylon_models==nil then return end
 assert(type(d.pylon_models)=='table','pylon_models must be an array')
 local count,seen=0,{}
 for key,row in pairs(d.pylon_models)do
  count=count+1
  assert(type(key)=='number'and key%1==0 and key>=1 and key<=32,'pylon_models must be an array of at most 32 entries')
  assert(type(row)=='table'and type(row.index)=='number'and row.index%1==0
   and row.index>=1 and row.index<=d.pylons,'Pylon model index must be between 1 and pylons')
  assert(not seen[row.index],'Duplicate pylon model index: '..row.index);seen[row.index]=true
  for field in pairs(row)do assert(field=='index'or field=='models','Unknown pylon model setting: '..tostring(field))end
  overrides(row.models,support_roles)
 end
 assert(count==#d.pylon_models,'pylon_models must be a dense array')
end
function Models.new(api,assets)
 local self={map=api._session or api,meshes={},materials={},mesh_count=0,material_count=0,bytes=0,vertices=0}
 function self:mesh(owner,path)
  local cache=self.meshes[owner];if not cache then cache={};self.meshes[owner]=cache end
  if cache[path]then return cache[path]end
  assert(self.mesh_count<88,'Too many surface lift meshes (24 defaults plus at most 64 custom meshes)')
  local bytes=owner:read_asset(path)
  assert(self.bytes+#bytes<=32*1024*1024,'Surface lift mesh data exceeds 32 MiB')
  -- Check aggregate vertices before allocating the decoded Lua arrays.
  assert(#bytes>=16,'Invalid SKPM size')
  local vertices=string.unpack('<I4',bytes,9)
  assert(self.vertices+vertices<=500000,'Surface lift meshes exceed 500000 total vertices')
  local mesh=Mesh.decode(bytes)
  self.bytes=self.bytes+#bytes;self.vertices=self.vertices+#mesh.vertices;self.mesh_count=self.mesh_count+1
  cache[path]=mesh;return mesh
 end
 function self:material(owner,path)
  local cache=self.materials[owner];if not cache then cache={};self.materials[owner]=cache end
  if cache[path]then return cache[path]end
  assert(self.material_count<32,'Surface lifts support at most 32 palettes')
  local material=Mesh.material(owner,path)
  self.material_count=self.material_count+1;cache[path]=material;return material
 end
 function self:bank(parent,changes)
  if not changes or not next(changes)then return parent end
  local bank={models={},paths={},material=parent.material,palette=parent.palette}
  for _,role in ipairs(Models.roles)do
   bank.models[role]=changes[role]and self:mesh(self.map,changes[role])or parent.models[role]
   bank.paths[role]=changes[role]or parent.paths[role]
  end
  if changes.palette then bank.material=self:material(self.map,changes.palette);bank.palette=changes.palette end
  return bank
 end
 function self:definition(d)
  Models.validate(d)
  local bank=self:bank(self.base,d.models);local pylons={}
  for _,row in ipairs(d.pylon_models or{})do pylons[row.index]=self:bank(bank,row.models)end
  return{bank=bank,pylons=pylons}
 end
 self.base={models={},paths={},palette=assets.palette}
 for _,role in ipairs(Models.roles)do
  assert(type(assets[role])=='string','Missing lift model: '..role)
  self.base.models[role]=self:mesh(api,assets[role]);self.base.paths[role]=assets[role]
 end
 self.base.material=self:material(api,assets.palette)
 return self
end
function Models.support(item,index)return item.pylon_banks[index]or item.bank end
function Models.rebind(component,previous,bank,role)
 local mesh=bank.models[role]
 if previous.models[role]~=mesh then
  component:CreateMeshSection(0,mesh.vertices,mesh.triangles,mesh.normals,mesh.uv,{},{},false)
 end
 if previous.material~=bank.material then component:SetMaterial(0,bank.material)end
end
function Models.perch(state,index,bank)
    local p=state.pool[index]
    if p then
        if p.bank==bank then return p end
        -- Reuse a matching unused slot before changing procedural geometry.
        -- The visible and station stocks still share the original 128-slot cap.
        for j=index+1,#state.pool do if state.pool[j].bank==bank then
            state.pool[index],state.pool[j]=state.pool[j],p;return state.pool[index]
        end end
        for role,component in pairs({platter=p.component,platter_upper=p.upper,platter_shaft=p.shaft,platter_lower=p.lower})do
            Models.rebind(component,p.bank,bank,role)
        end
        p.bank=bank;p.visible=false;return p
    end
    local a=Mesh.actor();local c=Mesh.component(a,bank.models.platter,bank.material)
    p={actor=a,component=c,bank=bank,upper=Mesh.component(a,bank.models.platter_upper,bank.material),
        shaft=Mesh.component(a,bank.models.platter_shaft,bank.material),lower=Mesh.component(a,bank.models.platter_lower,bank.material)}
    state.pool[index]=p;return p
end
return Models
