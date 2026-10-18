package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local json=require('json')
local Nanite=require('nanite_terrain')
local source={format='r16le',spacing_meters=4,height_scale_meters=.025,
    height_offset_meters=723.9875,row_order='north_to_south',vertices={2,2}}
local state={map={id='test.veymont',terrain={source=source}},runtime={},
    width=2,height=2,origin_x=0,origin_y=0,origin_z=0,section_count=1,bytes=string.rep('\0',8),
    independent_world=true}
local cache={version=1,target_platform='Windows',engine_family='5.8',mesh_algorithm=1,
    map_id=state.map.id,game_render_verified=true,sample_step=4,tile_quads=63,uv_tile_meters=20,
    source=source,source_origin_centimeters={0,0,0},
    source_crc32=string.format('%08x',require('archive').crc32(state.bytes)),
    sections={{section=0,asset='/Game/CustomMaps/Veymont/Nanite/SM_Terrain_0.SM_Terrain_0',origin_meters={0,0,0}}}}
assert(Nanite.validate(cache,state))
cache.game_render_verified=false
assert(not pcall(Nanite.validate,cache,state),'unverified cache accepted')
cache.game_render_verified=true
cache.source_crc32='deadbeef'
assert(not pcall(Nanite.validate,cache,state),'different terrain accepted')
cache.source_crc32=state.nanite_source_crc32
cache.sample_step=2
assert(not pcall(Nanite.validate,cache,state),'different tile layout accepted')
cache.sample_step=4
assert(Nanite.cache_path({__root='map'})=='map/Runtime/Nanite/cache.json')
assert(Nanite.cache_path({__archive={},__manifest_path='map.skieomap'})=='map.skieomap.nanite-5.8.json')
local root=os.tmpname();local file=assert(io.open(root,'w'));file:write(json.encode(cache));file:close()
local old_path=Nanite.cache_path
Nanite.cache_path=function() return root end
local queue,hidden,done,collision_disabled={},false,false,false
local mesh={GetNumNaniteTriangles=function() return 16 end,IsValid=function() return true end,
 GetAddress=function() return 123 end}
local loaded_mesh=mesh
local triangles,enabled,hide_throw=16,1,false
mesh.GetNumNaniteTriangles=function() return triangles end
StaticFindObject=function() return mesh end
local material={IsValid=function() return true end,GetBaseMaterial=function() return {bUsedWithNanite=true} end}
package.preload.UEHelpers=function() return {GetKismetSystemLibrary=function()
 return {IsValid=function() return true end,GetConsoleVariableIntValue=function() return enabled end,
 MakeSoftObjectPath=function(_,path) return path end,
 Conv_SoftObjPathToSoftObjRef=function(_,path) return {native_reference=path} end,
 Conv_SoftObjectReferenceToString=function(_,reference)
  return {ToString=function() return reference.native_reference end}
 end,
 LoadAsset_Blocking=function(_,reference) assert(reference.native_reference);return loaded_mesh end}
end} end
local component={IsValid=function() return true end,SetVisibility=function() end,
 SetCollisionEnabled=function(_,value) assert(value==0);collision_disabled=true end,
 SetStaticMesh=function(_,value) assert(value==mesh) end,SetForceDisableNanite=function(_,value) assert(not value) end,
 SetMaterial=function(_,slot,value) assert(slot==0 and value==material) end,K2_DestroyComponent=function() end}
local terrain={active=state,generation=1,
 actor={AddComponentByClass=function() return component end},
 component={IsValid=function() return true end,GetMaterial=function() return material end,SetMeshSectionVisible=function(_,section,value)
  assert(section==0);hidden=not value
  if hide_throw and not value then error('simulated partial render failure') end
 end}}
local function schedule(_,callback) queue[#queue+1]=callback end
Nanite.apply(terrain,schedule,function() done=true end,function() end)
assert(not hidden and not done,'source hidden before asset/material initialization')
while #queue>0 do table.remove(queue,1)() end
assert(hidden and done and collision_disabled and #state.nanite_components==1)
-- CPU root pages disappear after GPU upload. Reloading the same object must
-- keep Nanite, while a different object with no Nanite data stays rejected.
triangles=0;hidden,done=false,false
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(hidden and done and #state.nanite_components==1,'uploaded mesh rejected on reload')
local other={IsValid=function() return true end,GetNumNaniteTriangles=function() return 0 end,
 GetAddress=function() return 456 end}
assert(not Nanite.has_validated_data(cache.sections[1].asset,other),'validation reused for another mesh')
triangles=16
-- A missing cooked asset leaves the source renderer visible.
hidden,done=false,false
loaded_mesh=nil
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(not hidden and done and #state.nanite_components==0)
-- Runtime data matters: editor-only NaniteSettings are absent in shipping.
loaded_mesh=mesh;triangles=0;hidden,done=false,false
Nanite.validated_meshes={}
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(not hidden and done and #state.nanite_components==0)
triangles=16;enabled=0;hidden,done=false,false
Nanite.apply(terrain,schedule,function() done=true end,function() end)
assert(not hidden and done and #queue==0)
enabled=1;hide_throw=true;hidden,done=false,false
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(not hidden and done and #state.nanite_components==0,'partial replacement did not restore source')
hide_throw=false
-- A continuous massif replaces both covered sections and their snow shell.
state.section_count=2;cache.mesh_algorithm=2;cache.snow_offset_centimeters=30
local rock_entry=cache.sections[1]
rock_entry.source_sections={0,1};rock_entry.layer='terrain'
local snow_entry={section=0,source_sections={0,1},layer='snow',
 asset='/Game/CustomMaps/Veymont/Nanite/SM_Snow.SM_Snow',origin_meters={0,0,0}}
cache.sections={rock_entry,snow_entry}
assert(Nanite.validate(cache,state))
snow_entry.layer='terrain';assert(not pcall(Nanite.validate,cache,state),'overlapping rock sections accepted')
snow_entry.layer='snow'
cache.sections={rock_entry};assert(not pcall(Nanite.validate,cache,state),'massif without matching snow accepted')
cache.sections={rock_entry,snow_entry}
local rock_hidden,snow_hidden={},{}
local reject_snow=false
terrain.component.SetMeshSectionVisible=function(_,section,value) rock_hidden[section]=not value end
terrain.snow_component={IsValid=function() return true end,GetMaterial=function()
 if reject_snow then error('snow material unavailable') end;return material end,
 SetMeshSectionVisible=function(_,section,value) snow_hidden[section]=not value end}
file=assert(io.open(root,'w'));file:write(json.encode(cache));file:close()
done=false
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(done and #state.nanite_components==2)
assert(rock_hidden[0] and rock_hidden[1] and snow_hidden[0] and snow_hidden[1])
-- A failed snow replacement must restore the already installed rock as well.
rock_hidden,snow_hidden={},{};reject_snow=true;done=false
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(done and #state.nanite_components==0)
assert(not rock_hidden[0] and not rock_hidden[1])
assert(not snow_hidden[0] and not snow_hidden[1])
-- Partitioned replacements must be complete and activate atomically.
cache.mesh_algorithm=3;state.section_count=1;reject_snow=false
rock_entry.source_sections={0};rock_entry.part=0;rock_entry.parts=2
snow_entry.source_sections={0};snow_entry.part=0;snow_entry.parts=2
local rock_second={section=0,source_sections={0},layer='terrain',part=1,parts=2,
 asset='/Game/CustomMaps/Veymont/Nanite/SM_Rock2.SM_Rock2',origin_meters={0,0,0}}
local snow_second={section=0,source_sections={0},layer='snow',part=1,parts=2,
 asset='/Game/CustomMaps/Veymont/Nanite/SM_Snow2.SM_Snow2',origin_meters={0,0,0}}
cache.sections={rock_entry,snow_entry,rock_second,snow_second}
assert(Nanite.validate(cache,state))
cache.sections={rock_entry,snow_entry,rock_second}
assert(not pcall(Nanite.validate,cache,state),'missing snow partition accepted')
cache.sections={rock_entry,snow_entry,rock_second,snow_second}
snow_second.part=0;assert(not pcall(Nanite.validate,cache,state),'duplicate partition accepted');snow_second.part=1
file=assert(io.open(root,'w'));file:write(json.encode(cache));file:close()
done=false;rock_hidden,snow_hidden={},{}
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do
 table.remove(queue,1)()
 if not done then assert(not rock_hidden[0] and not snow_hidden[0],'incomplete massif hid native surfaces') end
end
assert(done and #state.nanite_components==4 and rock_hidden[0] and snow_hidden[0])
reject_snow=true;done=false;rock_hidden,snow_hidden={},{}
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(done and #state.nanite_components==0 and not rock_hidden[0] and not snow_hidden[0])
local coat={section=0,source_sections={0},layer='snow_deposits',part=0,parts=2,
 asset='/Game/CustomMaps/Veymont/Nanite/SM_Coat.SM_Coat',origin_meters={0,0,0},
 snow_uv_bounds={{.25,.5},{.375,.75}},coat_material='/Game/Materials/Backgrounds/M_Snow.M_Snow'}
cache.sections[#cache.sections+1]=coat
assert(Nanite.validate(cache,state),'optional partial snow coats rejected')
local Snow=require('nanite_snow')
local create_snow,weather_start=Snow.material,Snow.start
Snow.material=function() return material end
Snow.start=function(_,_,coats) assert(#coats==1) end
terrain.actor.GetWorld=function() return {} end
reject_snow=false;done=false;rock_hidden,snow_hidden={},{}
file=assert(io.open(root,'w'));file:write(json.encode(cache));file:close()
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(done and #state.nanite_components==5 and rock_hidden[0] and snow_hidden[0])
-- An unavailable coat must preserve the complete original surface, too.
Snow.material=function() error('missing coat shader') end
done=false;rock_hidden,snow_hidden={},{}
Nanite.apply(terrain,schedule,function() done=true end,function() end)
while #queue>0 do table.remove(queue,1)() end
assert(done and #state.nanite_components==0 and not rock_hidden[0] and not snow_hidden[0])
Snow.material,Snow.start=create_snow,weather_start
coat.parts=3;assert(not pcall(Nanite.validate,cache,state),'inconsistent coat partition accepted');coat.parts=2
coat.snow_uv_bounds[1][1]=0/0
assert(not pcall(Nanite.validate,cache,state),'invalid snow footprint accepted');coat.snow_uv_bounds[1][1]=.25
coat.coat_material='/Game/Other.Mat'
assert(not pcall(Nanite.validate,cache,state),'unexpected snow material accepted')
Nanite.cache_path=old_path;os.remove(root)
print('Nanite terrain: source/data checks, deferred replacement and render rollback OK')
