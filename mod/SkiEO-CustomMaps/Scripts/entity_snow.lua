-- Asynchronous native snow readback, sampled on the CPU. The bridge owns no
-- Unreal objects and validates the supported layout on every request.
local Snow={}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local loader
function Snow.sample(cache,x,y)
    if not directory or type(package.loadlib)~='function' then return nil end
    if loader==nil then loader=package.loadlib(directory..'skieo_native_terrain.dll','skieo_sample_snow') or false end
    if not loader then return nil end
    local cls=StaticFindObject('/Script/SkiResortSimulator.SnowStateCache')
    if not cls or not cls:IsValid() then return nil end
    local f=assert(io.open(directory..'native_entity_snow.job','wb'))
    f:write(string.pack('<c4I4I8I8dd','SKSN',1,cache:GetAddress(),cls:GetAddress(),x,y));f:close()
    loader()
    f=io.open(directory..'native_entity_snow.bin','rb');if not f then return nil end
    local bytes=f:read('*a');f:close()
    if #bytes~=16 then return nil end
    local ready,packed,fresh,spacing=string.unpack('<ffff',bytes)
    if ready==1 then return packed+fresh,spacing,packed,fresh end
    return nil
end
return Snow
