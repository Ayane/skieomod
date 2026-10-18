package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local Versions = require("versions")
assert(Versions.matches("1.2.0", "^1.0.0"))
assert(Versions.matches("1.2.0+build-tag", "*"))
assert(not Versions.matches("2.0.0", "^1.0.0"))
assert(Versions.matches("0.2.3", "^0.2.0"))
assert(not Versions.matches("0.3.0", "^0.2.0"))
assert(Versions.matches("1.2.0", ">=1.0.0 <2.0.0"))
assert(Versions.compare("1.0.0-beta.2", "1.0.0-beta.11") < 0)
assert(Versions.compare("1.0.0-beta.11", "1.0.0") < 0)
local function mod(id, version, deps) return {id=id, metadata={version=version}, dependencies=deps or {}} end
local mods = {
    mod("test.a", "2.0.0", {{id="test.shared",version="^2.0.0"}}),
    mod("test.a", "1.0.0", {{id="test.shared",version="^1.0.0"}}),
    mod("test.shared", "2.0.0"), mod("test.shared", "1.0.0"),
}
local result = Versions.resolve({dependencies={{id="test.a"},{id="test.shared",version="^1.0.0"}}}, mods)
assert(#result == 2 and result[1].id == "test.shared" and result[1].metadata.version == "1.0.0" and result[2].metadata.version == "1.0.0")
assert(not pcall(Versions.resolve, {dependencies={{id="test.missing"}}}, mods))
assert(not pcall(Versions.resolve, {dependencies={{id="test.a"}}}, {
    mod("test.a", "1.0.0", {{id="test.b"}}), mod("test.b", "1.0.0", {{id="test.a"}})
}))
local json = require("json")
assert(json.decode(json.encode({name='quotes " slash \\ newline\n', values={1,true,false}})).name == 'quotes " slash \\ newline\n')
package.preload.UEHelpers = function() return {} end
package.preload.terrain = function() return {unload=function() end} end
package.preload.catalog = function() return {} end
package.preload.loading = function() return {} end
ExecuteInGameThread = function() end
local Runtime = require("runtime")
_G.registration_order = {}
local dependency = {
    id="test.tools",metadata={name="Tools",version="1.0.0"},
    content={assets={"asset.txt"}},script={language="lua",api="1.0",entry="main.lua",permissions={"skieo.unrestricted"}},
    __manifest_path="test-tools",__read=function(path)
        if path == "asset.txt" then return "mod asset" end
        return [[return function(api)
            table.insert(registration_order,"mod")
            assert(api:read_asset("asset.txt")=="mod asset")
            api:on("map.ready",function() table.insert(registration_order,"mod ready") end)
        end]]
    end,
}
local map = {id="test.map",metadata={name="Map",version="1.0.0"},content={assets={"asset.txt"}},
    script={entry="main.lua",permissions={"skieo.unrestricted"}}, dependencies={{id="test.tools",version="^1.0.0"}},
    __manifest_path="test-map",__read=function(path)
        if path == "asset.txt" then return "map asset" end
        return [[return function(api)
            table.insert(registration_order,"map")
            assert(api:read_asset("asset.txt")=="map asset")
            api:on("map.ready",function() table.insert(registration_order,"map ready") end)
        end]]
    end,
}
Runtime.mods={dependency}
assert(Runtime.start(map))
Runtime.emit("map.ready")
assert(table.concat(registration_order,",")=="mod,map,mod ready,map ready")
local missing = {id="test.missing-map",metadata={name="Missing"},dependencies={{id="missing.mod"}}}
assert(not Runtime.start(missing))
print("Dependencies: version backtracking, cycle rejection, scoped assets and registration order OK")
