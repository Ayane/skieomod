-- Export the exact existing render/collision tile without Unreal dependencies.
-- lua tools/export_nanite_tile.lua <manifest> <zero-based section> <output-dir>
package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local json=require('json')
local Heightmap=require('heightmap')
local Mesh=require('terrain_mesh')
local manifest,section,output=assert(arg[1]),assert(tonumber(arg[2])),assert(arg[3])
assert(section>=0 and section%1==0,'section must be a nonnegative integer')
local function read(path)
    local f=assert(io.open(path,'rb'));local data=f:read('*a');f:close();return data
end
local map=json.decode(read(manifest))
local directory=manifest:match('^(.*[/\\])') or ''
map.__read=function(path) return read(directory..path) end
local state=Heightmap.load(map)
local step=math.max(1,math.floor(state.runtime.sample_step or 4))
local quads=math.max(8,math.min(127,math.floor(state.runtime.tile_quads or 63)))
state.sample_step=step
local plan=Mesh.plan(state,step)
local tile_columns=math.ceil((#plan.columns-1)/quads)
local tile_rows=math.ceil((#plan.rows-1)/quads)
assert(section<tile_columns*tile_rows,'section is outside the map')
local x=(section%tile_columns)*quads+1
local y=math.floor(section/tile_columns)*quads+1
local vertices,indices,normals,uvs=Mesh.build_tile(state,plan.columns,plan.rows,x,y,quads,0,true,plan)
assert(#vertices<=100000 and #indices/3<=100000,'source tile exceeds export budget')
local origin={0,0,0}
local min,max={math.huge,math.huge,math.huge},{-math.huge,-math.huge,-math.huge}
for _,v in ipairs(vertices) do
    for axis,value in ipairs({v.X,v.Y,v.Z}) do
        min[axis]=math.min(min[axis],value);max[axis]=math.max(max[axis],value)
    end
end
for axis=1,3 do origin[axis]=(min[axis]+max[axis])/200 end
local function write(name,values,callback)
    local file=assert(io.open(output..'/'..name..'.txt','w'))
    for _,value in ipairs(values) do file:write(callback(value),'\n') end
    file:close()
end
write('positions',vertices,function(v)
    return ('%.12g %.12g %.12g'):format(v.X/100-origin[1],v.Y/100-origin[2],v.Z/100-origin[3])
end)
write('normals',normals,function(v) return ('%.12g %.12g %.12g'):format(v.X,v.Y,v.Z) end)
write('uvs',uvs,function(v) return ('%.12g %.12g'):format(v.X,v.Y) end)
local file=assert(io.open(output..'/indices.txt','w'))
-- Runtime terrain uses clockwise fronts; the portable cooker input uses CCW.
for i=1,#indices,3 do file:write(('%d %d %d\n'):format(indices[i],indices[i+2],indices[i+1])) end
file:close()
local info={version=1,coordinate_system='east-south-up-metres',winding='counterclockwise',
    vertices=#vertices,triangles=#indices/3,origin_meters=origin,
    map_id=map.id,source_section=section,sample_step=step,tile_quads=quads,
    uv_tile_meters=state.runtime.uv_tile_meters or 20,
    source_manifest=manifest,source_file=directory..map.terrain.source.file,
    source_definition=map.terrain.source,
    source_origin_centimeters={state.origin_x,state.origin_y,state.origin_z}}
file=assert(io.open(output..'/tile-source.json','w'));file:write(json.encode(info));file:close()
print(('Source section %d: %d vertices, %d triangles'):format(section,#vertices,#indices/3))
