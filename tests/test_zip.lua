package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local Archive, Deflate, Mods = require("archive"), require("deflate"), require("mod_catalog")
local root = assert(arg[1], "pass ZIP fixture directory") .. "/"
local maps, errors = require("catalog").discover({__files={
    {__name="deflate.zip",__absolute_path=root .. "deflate.zip"},
    {__name="z-new.zip",__absolute_path=root .. "z-new.zip"},
}})
assert(#maps==1 and #errors==1 and maps[1].metadata.version=="2.0.0", "prefer the newest installed map version")
local installed, failures = require("catalog").discover({__files={
    {__name="deflate.zip",__absolute_path=root .. "deflate.zip"},
    {__name="Veymont-0.5.1.skieomap",__absolute_path=root .. "SkiEO-CustomMaps/Examples/Veymont-0.5.1.skieomap"},
    {__name="Veymont-0.5.1.skieomap",__absolute_path="C:\\Game\\ue4ss\\Mods\\SkiEO-CustomMaps\\Examples\\Veymont-0.5.1.skieomap"},
    {__name="Veymont-0.5.1.skieomap",__absolute_path=root .. "SkiEO-CustomMaps/.skieomod-backups/123/Examples/Veymont-0.5.1.skieomap"},
    {__name="map.skieomap",__absolute_path="C:\\Game\\~mods\\.skieomod-backups\\123\\map.skieomap"},
    {__name="custom-map.json",__absolute_path=root .. ".skieomod-backups/123/custom-map.json"},
}})
assert(#installed==1 and #failures==0, "distribution examples and backups must not shadow or duplicate installed maps")
for _, name in ipairs({"store.zip","deflate.zip"}) do
    local zip, failure = Archive.open(root .. name); assert(zip, failure)
    local manifest, error_message = zip:read("custom-map.json"); assert(manifest, error_message)
    assert(manifest:find("test.alpine",1,true))
    assert(#assert(zip:read("Terrain/heightmap.r16")) == 18)
end
local zip = assert(Archive.open(root .. "descriptor.zip"))
assert(#assert(zip:read("test.txt")) == #(string.rep("overlapping backreferences ",3000)))
assert(not Archive.open(root .. "unsafe.zip"))
zip = assert(Archive.open(root .. "bad-crc.zip"))
assert(not zip:read("custom-map.json"))
local mod, failure = Mods.load(root .. "mod.skieomod");assert(mod,failure);assert(mod.id == "test.snow-tools")
-- Menu inventory reads manifests and sizes without inflating large payloads.
-- Full loading still reads/verifies every file before the map is activated.
local open=Archive.open
local payload_reads=0
Archive.open=function(path)
    local archive=assert(open(path))
    local read=archive.read
    archive.read=function(self,name)
        if name~='custom-map.json' and name~='custom-mod.json' then
            payload_reads=payload_reads+1
            return nil,'payload CRC mismatch'
        end
        return read(self,name)
    end
    return archive
end
local inventory=assert(require('catalog').load(root..'deflate.zip',true))
assert(inventory.__inventory_only and payload_reads==0)
assert(Mods.load(root..'mod.skieomod',true).__inventory_only and payload_reads==0)
assert(not require('catalog').load(root..'deflate.zip') and payload_reads==1)
assert(not Mods.load(root..'mod.skieomod') and payload_reads==2)
Archive.open=open
local file = assert(io.open(root .. "fixed.deflate", "rb"));local compressed=file:read("*a");file:close()
file=assert(io.open(root .. "expected.txt","rb"));local expected=file:read("*a");file:close()
assert(Deflate.inflate(compressed,#expected)==expected)
assert(not pcall(Deflate.inflate,compressed,#expected-1))
assert(not pcall(Deflate.inflate,compressed:sub(1,-2),#expected))
assert(Archive.crc32("123456789")==0xcbf43926)
print("ZIP: Store, fixed/dynamic Deflate, descriptors, overlaps, CRC, traversal and limits OK")
