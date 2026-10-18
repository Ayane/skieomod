package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local Json, Catalog, View, Presentation = require("json"), require("catalog"), require("workshop_view"), require("map_presentation")
local root = assert(arg[1], "pass temporary fixture directory") .. "/featured/"
local origin = "https://skieomod.emillon.fr"
local function read(path) local f=assert(io.open(path,"rb"));local s=f:read("*a");f:close();return s end
local function write(path,source) local f=assert(io.open(path,"wb"));assert(f:write(source));f:close() end
os.remove(root .. "repository-installed.json")
os.remove(root .. "featured-1-0.json")
local queue, requested, responses = {}, {}, {}
ExecuteWithDelay = function(_,callback) queue[#queue+1]=callback end
local original = package.loadlib
package.loadlib = function(_,symbol)
    assert(symbol=="skieo_fetch")
    return function()
        local job=read(root .. "network.job")
        local url=job:sub(73);requested[#requested+1]=url
        if responses[url] then write(root .. "network.response",responses[url]);write(root .. "network.status","ok")
        else write(root .. "network.status","error: offline") end
    end
end
local function pump()
    local count=0
    while #queue>0 do count=count+1;assert(count<100);collectgarbage("collect");table.remove(queue,1)() end
end
local source=read("mod/SkiEO-CustomMaps/Scripts/repository.lua")
source=source:gsub('local directory = debug.getinfo[^\n]+','local directory = ' .. string.format('%q',root),1)
package.loaded.repository=assert(load(source,"@featured-repository","t",_G))()
local F=require("featured")
-- This fixture exercises the curated channel; community pagination and merging
-- are covered by test_registry.lua.
package.loaded.repository.initialize({repositories={{name="Featured",url=origin,
    registry_url=origin.."/downloads/featured-maps.json",cache_prefix="featured-"}}})
local function publish(version,digest)
    local data=read(root .. "featured-" .. version .. ".skieomap")
    local manifest=assert(Catalog.load(root .. "featured-" .. version .. ".skieomap"))
    local release={id=manifest.id,kind="map",version=version,sha256=string.rep(digest,64),size=#data,unpacked_size=20000,
        manifest=Json.decode(assert(manifest.__read("custom-map.json"))),download_url=origin .. "/downloads/" .. manifest.id .. "-" .. version .. ".skieomap"}
    responses[origin .. "/downloads/featured-maps.json"]=Json.encode({format="skieo-registry",version=1,packages={release}})
    responses[release.download_url]=data
    return release
end
local function veymont(entries) for _,entry in ipairs(F.merge(entries)) do if entry.id=='community.veymont' then return entry end end end
local featured=F.merge({});assert(#featured==2 and featured[1].id=='community.super-saint-bernard')
local stub=veymont({})
assert(stub.__featured and stub.__unavailable and View.row(stub):find("[Featured]",1,true))
assert(Presentation.card(stub).subtitle=="Featured · download on Play" and View.action(stub)=="Play")
local first=publish("1.0.0","b")
assert(F.refresh());pump()
assert(#requested==1,"browsing downloaded a map payload")
local map=veymont({})
local complete=false
assert(F.ensure(map,{}, {},function(failure)assert(not failure,failure);complete=true end));pump()
assert(complete and not F.busy and #requested==3 and requested[3]==first.download_url)
local maps=F.local_packages();map=veymont(maps)
assert(map.__read and map.__featured and not map.__unavailable)
assert(View.row(map):find("[Featured]",1,true) and not Presentation.card(map).subtitle:find("Local",1,true))
local count=#requested
assert(F.ensure(map,maps,{},function(failure)assert(not failure,failure) end));pump()
assert(#requested==count,"a current installed map contacted the network")
local second=publish("2.0.0","c")
local updated_bytes=responses[second.download_url]
responses[second.download_url]=nil
local update_failed=false
assert(F.refresh());pump();map=veymont(maps)
assert(F.ensure(map,maps,{},function(failure)assert(failure);update_failed=true end));pump()
assert(update_failed and #F.local_packages()==1,"a failed update changed installed content")
responses[second.download_url]=updated_bytes
assert(F.ensure(map,maps,{},function(failure)assert(not failure,failure) end));pump()
maps=F.local_packages()
local latest
for _,entry in ipairs(maps) do if entry.metadata.version=="2.0.0" then latest=entry end end
assert(latest and latest.__read and requested[#requested]==second.download_url)
local old=assert(io.open(root .. "repository-" .. string.rep("b",64) .. ".skieomap","rb"));old:close()
responses[origin .. "/downloads/featured-maps.json"]=nil
count=#requested
assert(F.ensure(veymont({latest}),{latest},{},function(failure)assert(not failure,failure) end));pump()
assert(#requested==count,"an offline installed map contacted the network")
-- A fresh unavailable map reports failure instead of starting absent terrain.
package.loaded.repository.remote={}
local failed=false
assert(F.ensure(veymont({}),{},{},function(failure)assert(failure);failed=true end));pump();assert(failed and not F.busy)
-- Two maps can pin different versions without embedding the mapmod. Only the
-- required version is fetched, dependencies precede the root, and local maps
-- can reuse the same installed package offline.
local R=package.loaded.repository
local function fox_release(version,digest)
    local data=read(root..'foxes-'..version..'.skieomod')
    local mod=assert(require('mod_catalog').load(root..'foxes-'..version..'.skieomod'))
    local release={id=mod.id,kind='mod',version=version,sha256=string.rep(digest,64),size=#data,unpacked_size=20000,
        manifest=Json.decode(assert(mod.__read('custom-mod.json'))),download_url=origin..'/downloads/'..mod.id..'-'..version..'.skieomod'}
    responses[release.download_url]=data;return release
end
local fox1,fox2=fox_release('1.0.0','d'),fox_release('2.0.0','e')
local third=publish('3.0.0','f')
responses[origin..'/downloads/featured-maps.json']=Json.encode({format='skieo-registry',version=1,packages={third,fox2,fox1}})
count=#requested
assert(F.refresh());pump()
assert(F.ensure(veymont({latest}),{latest},{},function(failure)assert(not failure,failure) end));pump()
assert(#requested==count+4 and requested[count+3]==fox1.download_url and requested[count+4]==third.download_url)
local installed_maps,installed_mods=F.local_packages()
assert(#installed_mods==1 and installed_mods[1].metadata.version=='1.0.0')
assert(#R.merge({})==1,'mapmods leaked into the map picker')
local third_map
for _,m in ipairs(installed_maps) do if m.metadata.version=='3.0.0' then third_map=m end end
local retained={}
for _,path in ipairs(R.installed) do if path:match('%.skieomap$') then retained[#retained+1]=path end end
R.installed=retained;count=#requested
assert(F.ensure(veymont({third_map}),{third_map},{},function(failure)assert(not failure,failure) end));pump()
assert(#requested==count+2 and requested[#requested]==fox1.download_url,'installed Featured map could not recover its missing mod')
local fourth=publish('4.0.0','a')
responses[origin..'/downloads/featured-maps.json']=Json.encode({format='skieo-registry',version=1,packages={fourth,fox1,fox2}})
assert(F.refresh());pump()
assert(F.ensure(veymont({third_map}),{third_map},installed_mods,function(failure)assert(not failure,failure) end));pump()
installed_maps,installed_mods=F.local_packages();assert(#installed_mods==2,'updating a map replaced the old mod version')
local local_map=Catalog.load(root..'featured-3.0.0.skieomap')
count=#requested
assert(R.ensure_dependencies(local_map,installed_mods,function(failure)assert(not failure,failure) end));pump()
assert(#requested==count,'compatible local map dependencies triggered a download')
-- The map is already present but its pinned mod is missing: fetch only the mod.
R.installed={};responses[fox2.download_url]=nil
assert(R.ensure_dependencies(local_map,{},function(failure)assert(not failure,failure) end));pump()
assert(requested[#requested]==fox1.download_url)
local _,mods=R.local_packages();assert(#mods==1 and mods[1].metadata.version=='1.0.0')
-- A pending metadata refresh must not serialize complete local releases.
count=#requested
R.busy,F.busy=true,true
local_map.__featured,local_map.__update=true,nil
local immediate=false
assert(F.ensure(local_map,{local_map},mods,function(failure)assert(not failure,failure);immediate=true end))
assert(immediate and R.busy and F.busy and #requested==count,'local playback waited for a refresh')
immediate=false
assert(R.ensure_dependencies(local_map,mods,function(failure)assert(not failure,failure);immediate=true end))
assert(immediate and #requested==count,'installed dependencies waited for a refresh')
R.busy,F.busy=false,false
-- Missing content may queue behind metadata, while its loading screen remains
-- visible. It must eventually finish rather than dropping its callback.
assert(F.refresh())
complete=false
assert(F.ensure(veymont({}),{},mods,function(failure)assert(not failure,failure);complete=true end))
assert(not complete)
responses[fox2.download_url]=read(root..'foxes-2.0.0.skieomod')
pump();assert(complete and not F.busy and not R.busy)
-- A curated map can receive a newer community API release. Featured must
-- select that update rather than reverting to its older static release.
local api_fourth=Json.decode(Json.encode(fourth))
api_fourth.download_url=origin..'/api/v1/downloads/'..fourth.id..'/'..fourth.version
responses[api_fourth.download_url]=responses[fourth.download_url]
responses[origin..'/api/v1/registry?offset=0']=Json.encode({format='skieo-registry',version=1,packages={api_fourth,fox1,fox2}})
responses[origin..'/downloads/featured-maps.json']=Json.encode({format='skieo-registry',version=1,packages={third,fox1,fox2}})
responses[origin..'/api/v1/resolve?id='..fourth.id..'&version=%3D4.0.0']=Json.encode({packages={fox2,api_fourth}})
R.initialize({repositories={{url=origin},{url=origin,registry_url=origin..'/downloads/featured-maps.json',cache_prefix='featured-'}}})
assert(F.refresh());pump()
local from_api=veymont({third_map});assert(from_api.__update.metadata.version=='4.0.0')
assert(F.ensure(from_api,{third_map},installed_mods,function(failure)assert(not failure,failure) end));pump()
assert(requested[#requested]==api_fourth.download_url,'Featured ignored a newer API release')
package.loadlib=original
print("Featured: metadata-only browsing, Play download, current cache, updates, retained old maps and offline playback OK")
