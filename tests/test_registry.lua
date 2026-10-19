package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local json, Catalog = require("json"), require("catalog")
local root = assert(arg[1], "pass temporary fixture directory") .. "/"
local function read(path) local f=assert(io.open(path,"rb"));local s=f:read("*a");f:close();return s end
local function write(path, source) local f=assert(io.open(path,"wb"));f:write(source);f:close() end
write(root .. "repositories.json", json.encode({repositories={{name="Test",url="https://repository.example"}}}))
local archive = assert(require("archive").open(root .. "deflate.zip"))
local manifest = json.decode(assert(archive:read("custom-map.json")))
local function release(map)
    return {id=map.id,kind="map",version=map.metadata.version,sha256=string.rep("a",64),size=#read(root .. "deflate.zip"),unpacked_size=20000,manifest=map,download_url="https://repository.example/api/v1/downloads/" .. map.id .. "/" .. map.metadata.version}
end
local first = release(manifest)
local second = json.decode(json.encode(manifest)); second.id="test.second";second.metadata.name="Second"
local responses = {
    ["https://repository.example/api/v1/registry?offset=0"]=json.encode({format="skieo-registry",version=1,packages={first},next_offset=128}),
    ["https://repository.example/api/v1/registry?offset=128"]=json.encode({format="skieo-registry",version=1,packages={release(second)},next_offset=json.null}),
    ["https://repository.example/api/v1/resolve?id=test.alpine&version=%3D1.0.0"]=json.encode({packages={first}}),
    [first.download_url]=read(root .. "deflate.zip"),
}
local delayed, requested = {}, {}
ExecuteWithDelay = function(_, callback) delayed[#delayed+1]=callback end
local old_loadlib=package.loadlib
package.loadlib=function(_,symbol)
    assert(symbol=="skieo_fetch")
    return function()
        local source=read(root .. "network.job")
        local url=source:sub(73);requested[#requested+1]=url
        if responses[url] then write(root .. "network.response",responses[url]);write(root .. "network.status","ok")
        else write(root .. "network.status","error: offline") end
    end
end
local function pump()
    local count=0
    while #delayed>0 do count=count+1;assert(count<100);collectgarbage("collect");table.remove(delayed,1)() end
end
local source=read("mod/SkiEO-CustomMaps/Scripts/repository.lua")
source=source:gsub('local directory = debug.getinfo[^\n]+','local directory = ' .. string.format('%q',root),1)
local repository=assert(load(source,"@repository-test","t",_G))()
local refreshed=false;assert(repository.refresh(function()refreshed=true end));pump()
assert(refreshed and #repository.merge({})==2 and #requested==2)
local local_map=Catalog.load(root .. "deflate.zip");assert(local_map)
local merged=repository.merge({local_map});assert(#merged==2)
for _,map in ipairs(merged) do if map.id==local_map.id then assert(not map.__remote) end end
local installed=false
local webmap
for _, map in ipairs(repository.merge({})) do if map.id=="test.alpine" then webmap=map end end
assert(repository.install(webmap,function(failure)assert(not failure,failure);installed=true end));pump();assert(installed)
local maps=repository.local_packages();assert(#maps==1 and maps[1].id=="test.alpine")
responses["https://repository.example/api/v1/registry?offset=0"]=nil
assert(repository.refresh());pump();assert(#repository.merge({})==2 and #repository.errors==1)
local offline=assert(load(source,"@repository-offline","t",_G))()
assert(#offline.merge({})==2)
-- The API and curated index share an origin but have independent caches.
local origin="https://skieomod.emillon.fr"
local api_map=json.decode(json.encode(first));api_map.download_url=origin.."/api/v1/downloads/"..api_map.id.."/"..api_map.version
local curated_map=release(second);curated_map.download_url=origin.."/downloads/"..curated_map.id.."-"..curated_map.version..".skieomap"
responses[origin.."/api/v1/registry?offset=0"]=json.encode({format="skieo-registry",version=1,packages={api_map}})
responses[origin.."/downloads/featured-maps.json"]=json.encode({format="skieo-registry",version=1,packages={curated_map}})
local config={repositories={{name="Web",url=origin},{name="Featured",url=origin,registry_url=origin.."/downloads/featured-maps.json",cache_prefix="featured-"}}}
repository.initialize(config);assert(repository.refresh());pump()
assert(#repository.entries(config.repositories[1])==1 and #repository.entries(config.repositories[2])==1)
local combined=repository.merge({});assert(#combined==2,"one registry overwrote the other on the same origin")
-- Upgrading an existing installation keeps its repositories.json. Both legacy
-- catalogue URLs must migrate before WinHTTP can see the server's redirects.
local legacy={repositories={
    {name="Old community",url="https://skieomap.emillon.fr"},
    {name="Old featured",url="https://skieomap.emillon.fr",registry_url="https://skieomap.emillon.fr/downloads/featured-maps.json",cache_prefix="featured-"},
}}
local previous_requests=#requested
repository.initialize(legacy);assert(repository.refresh());pump()
assert(#repository.errors==0 and #repository.merge({})==2,"legacy configuration lost its web catalogues")
assert(requested[previous_requests+1]==origin.."/api/v1/registry?offset=0")
assert(requested[previous_requests+2]==origin.."/downloads/featured-maps.json")
assert(legacy.repositories[1].url==origin and legacy.repositories[2].registry_url==origin.."/downloads/featured-maps.json")
for _,entry in ipairs(combined) do assert(entry.__web and entry.__remote and entry.__unavailable) end
repository.initialize(config);assert(#repository.merge({})==2,"separate registry caches were lost offline")
repository.initialize({repositories={{url="https://skieomap.emillon.fr"}}})
assert(repository.repositories[1].url==origin,"legacy configuration was not migrated")
package.loadlib=old_loadlib
print("Registry: pagination, local/web merge, install, callback retention and offline cache OK")
