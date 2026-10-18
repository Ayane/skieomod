package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function entry(id,version,path)
    return {id=id,metadata={name=id,version=version},__manifest_path=path}
end
local source=entry('community.veymont','0.5.0','/mods/Veymont/custom-map.json')
local archive=entry(source.id,'0.5.0','/mods/Veymont.skieomap')
local local_maps,cached_maps,local_mods,cached_mods={source},{archive},{},{}
for _,name in ipairs({'UEHelpers','api','terrain','vegetation','loading','world','saves'}) do
    package.preload[name]=function() return {} end
end
package.preload.catalog=function() return {discover=function() return {table.unpack(local_maps)},{} end} end
package.preload.mod_catalog=function() return {discover=function() return {table.unpack(local_mods)},{} end} end
package.preload.workshop=function() return {
    local_packages=function() return cached_maps,cached_mods end,
    merge=function(entries) return entries end,
} end
package.preload.featured=function() return {local_packages=function() return {},{} end,merge=function(entries) return entries end} end
local Runtime=require('runtime')
Runtime.refresh()
assert(#Runtime.maps==1 and Runtime.maps[1]==source,'CLI inventory duplicated discovered Veymont')
local newer=entry(source.id,'0.6.0','/workshop/Veymont/custom-map.json')
cached_maps={archive,newer,archive}
Runtime.refresh()
assert(#Runtime.maps==1 and Runtime.maps[1]==newer,'highest installed map version was not retained')
assert(Runtime.selected()==newer,'selected logical map was lost')
local distinct=entry('test.same-title','1.0.0','/mods/other/custom-map.json')
distinct.metadata.name=source.metadata.name
cached_maps={archive,distinct}
Runtime.refresh()
assert(#Runtime.maps==2,'unrelated map with the same title was discarded')
-- Mods retain parallel versions for dependency resolution.
local_mods={entry('test.tools','1.0.0','/mods/tools-1')}
cached_mods={entry('test.tools','2.0.0','/mods/tools-2')}
Runtime.refresh()
assert(#Runtime.mods==2,'map de-duplication removed a required mod version')
print('Catalogue inventory: logical map identity, latest version, selection and mod versions OK')
