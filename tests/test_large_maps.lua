package.path = 'mod/SkiEO-CustomMaps/Scripts/?.lua;' .. package.path
package.preload.UEHelpers = function() return {} end
-- This fixture inspects file encoding only; runtime layout guards are covered
-- in test_runtime_compatibility.lua and the isolated UE4SS verification.
package.preload.compatibility=function()return {require=function()end,require_startup=function()end}end
local Heightmap = require('heightmap')
local Native = require('native_terrain')
local pieces = {}
for value = 0, 1100, 100 do pieces[#pieces + 1] = string.pack('<I2', value) end
local bytes = table.concat(pieces)
local state = Heightmap.load({terrain={size_meters={12000,18000},
    origin_centimeters={-600000,-900000,100},
    source={file='heightmap.r16',format='r16le',vertices={3,4},
        spacing_meters=6000,height_scale_meters=.5,height_offset_meters=0}},
    __read=function() return bytes end})
assert(Heightmap.height_at(state, 600000, 900000) == 55100)
assert(Heightmap.height_at(state, 0, 0) == 27600)
assert(Heightmap.height_at(state, 600001, 0) == nil)
assert(Native.resampled_raw(state, 2016, 2016, 2017, 2017) == 1100)
assert(Native.resampled_raw(state, 1008, 1008, 2017, 2017) == 550)

-- Inspect the actual native job without a game process, native memory writes
-- or temporary files in the mod's Scripts directory.
local files, captured, topology = {}, nil, nil
local open, remove, loadlib = io.open, os.remove, package.loadlib
local prefix = 'mod/SkiEO-CustomMaps/Scripts/'
io.open = function(path, mode)
    if path:sub(1, #prefix) ~= prefix then return open(path, mode) end
    if mode == 'rb' and files[path] == nil then return nil end
    return {write=function(self, data) files[path]=data;return self end,
        read=function() return files[path] end,close=function() end}
end
os.remove = function(path) files[path]=nil;return true end
package.loadlib = function(path, symbol)
    assert(path == prefix .. 'skieo_native_terrain.dll')
    assert(symbol == 'skieo_copy_heightmap')
    return function()
        captured = {string.unpack('<c4I4I8I8I4I4I4I4I4ddddddffff',
            assert(files[prefix .. 'native_terrain.job']))}
        topology={string.unpack('<I4I4I4I4',files[prefix .. 'native_terrain.job'],captured[20])}
        assert(files[prefix .. 'native_terrain.r16'] == bytes)
        files[prefix .. 'native_terrain.status'] = 'ok: staged rectangular terrain'
        files[prefix .. 'native_landscape.bounds'] = string.rep('\0', 32 * 32 * 4)
    end
end
local ok, message = pcall(Native.prepare_world, state)
io.open, os.remove, package.loadlib = open, remove, loadlib
assert(ok, message)
assert(captured[1] == 'SKNT' and captured[2] == 6)
assert(captured[3] == 0 and captured[4] == 0)
assert(captured[5] == 3 and captured[6] == 4)
assert(captured[7] == 2017 and captured[8] == 2017)
assert(topology[1]==4 and topology[2]==1 and topology[3]==0 and topology[4]==0)
assert(captured[12] == -600000 and captured[13] == -900000)
assert(captured[14] == 600000 and captured[15] == 900000)
assert(math.abs(captured[18] - 1200000 / 2016) < .001)
assert(math.abs(captured[19] - 1800000 / 2016) < .001)
assert(state.width == 3 and state.height == 4 and state.bytes == bytes)
assert(state.bootstrap.width == 2017 and state.bootstrap.height == 2017)
assert(math.abs(state.bootstrap.spacing_y / state.bootstrap.spacing_x - 1.5) < 1e-10)

-- A hollow omitted by the visible mesh must not survive in the simulation
-- cache: that discrepancy buried guests below otherwise flat snow.
local valley=Heightmap.load({terrain={size_meters={4,4},source={file='x',format='r16le',
    vertices={3,3},spacing_meters=2,height_scale_meters=.1,height_offset_meters=700},
    runtime={sample_step=2}},__read=function()
        return string.pack('<I2I2I2I2I2I2I2I2I2',1000,1000,1000,1000,0,1000,1000,1000,1000)
    end})
assert(Heightmap.height_at(valley,0,0)==70000)
require('terrain_mesh').prepare(valley)
assert(Native.resampled_raw(valley,1008,1008,2017,2017)==1000,
    'native snow/guest terrain retained the hidden source hollow')
assert(Heightmap.height_at(valley,0,0)==70000,'portable source was rewritten')
print('Large maps: rectangular world bounds, height queries, native resampling and independent XY spacing OK')
