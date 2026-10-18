package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local Json, Versions, View = require("json"), require("versions"), require("workshop_view")
local Vdf = require("steam_vdf")
assert(Vdf.decode('"AppWorkshop" { "appid" "4493130" // hello\n "WorkshopItemsInstalled" { "123" { "manifest" "8" } } }').AppWorkshop.WorkshopItemsInstalled["123"].manifest == "8")
assert(not pcall(Vdf.decode, '"a" { "b" "c"'))
local folders = {
    ["/installed/map/custom-map.json"] = {id="author.map", format={name="skieo-map"}, metadata={name="Local map title",version="1.0.0",authors={"Credits"},description="Local description"}, dependencies={{id="author.mod",version="^1.0.0",workshop_id="9007199254740993"}}, terrain={size_meters={1000,1000},elevation_meters={0,200}}},
    ["/installed/mod/custom-mod.json"] = {id="author.mod", format={name="skieo-mod"}, metadata={name="Mod",version="1.0.0",authors={"Credits"},description="Mod description"},runtime="map-api",dependencies={}},
}
package.loaded.catalog = {load=function(path) return folders[path] end}
package.loaded.mod_catalog = {load=function(path) return folders[path] end}
package.loaded.workshop = nil
local W = require("workshop")
assert(W.valid_id("9007199254740993") and W.valid_id("18446744073709551614"))
assert(not W.valid_id(123) and not W.valid_id("0") and not W.valid_id("18446744073709551615"))
assert(not W.refresh() and W.message:find("not connected",1,true))
local map = {published_file_id="123",app_id="4493130",result=1,kind="map",title="Steam map title",description="Steam description",owner_steam_id="76561198012587946",updated_at=1700000000,votes_up=8,votes_down=1,required_items={"9007199254740993"}}
local mod = {published_file_id="9007199254740993",app_id="4493130",result=1,kind="mod",title="Steam mod",description="description"}
local queue, subscribed, downloaded, installed = {}, {}, {}, {}
local provider = {version=1,app_id="4493130"}
function provider:query(options, callback)
    assert(options.return_metadata and options.return_children)
    queue[#queue+1] = function() callback({app_id=self.app_id,items={map},has_more=false}) end
end
function provider:get_details(id, callback) assert(id == mod.published_file_id); callback(mod) end
function provider:subscribed_items() local result={}; for id in pairs(subscribed) do result[#result+1]=id end; return result end
function provider:get_item_state(id) return {installed=installed[id],subscribed=subscribed[id],needs_update=false} end
function provider:get_install_info(id) assert(installed[id]); return {folder=id=="123" and "/installed/map" or "/installed/mod"} end
function provider:subscribe_item(id, callback)
    subscribed[id]=true
    queue[#queue+1]=function() callback({app_id=self.app_id,published_file_id=id,result=1}) end
end
function provider:download_item(id, callback)
    downloaded[#downloaded+1]=id
    queue[#queue+1]=function() installed[id]=true; callback({app_id=self.app_id,published_file_id=id,result=1}) end
end
local function pump() while #queue>0 do table.remove(queue,1)() end end
W.bind(provider)
assert(W.refresh()); assert(W.busy); pump(); assert(not W.busy)
local entries=W.merge({},"map"); assert(#entries==1 and entries[1].__unavailable and not entries[1].terrain)
assert(View.row(entries[1]):find("Steam map title",1,true))
local text=View.details(entries[1],{})
assert(text:find("76561198012587946",1,true) and text:find("Votes: +8 / -1",1,true))
assert(not text:find("Terrain:",1,true) and not text:find("v1.0.0",1,true))
local complete=false
assert(W.ensure(entries[1],function(failure) assert(not failure,failure); complete=true end));collectgarbage("collect");pump()
assert(complete and not W.busy and #downloaded==2 and downloaded[2]==mod.published_file_id)
assert(next(W.pending)==nil)
local maps,mods=W.local_packages();assert(#maps==1 and #mods==1)
assert(Versions.resolve(maps[1],mods)[1].id=="author.mod")
assert(View.details(maps[1],{}):find("Terrain:",1,true))
assert(View.action(maps[1],{needs_update=true})=="Update")
local action,enabled=View.action(maps[1],{downloading=true});assert(action=="Downloading…" and not enabled)
local mismatch={id="author.mod",metadata={version="1.0.0"},__workshop={published_file_id="456"}}
assert(not pcall(Versions.resolve,maps[1],{mismatch}))
assert(not pcall(W.normalize,{published_file_id="123",app_id="480",result=1,title="x",description="x",kind="map"}))
-- A download callback from another app cannot expose its content to this game.
installed["123"]=false
function provider:download_item(id,callback) callback({app_id="480",published_file_id=id,result=1}) end
local rejected=false
assert(W.ensure(entries[1],function(failure) assert(failure:find("mismatch",1,true));rejected=true end));pump();assert(rejected and not W.busy)
-- Last good catalogue survives failed refreshes.
function provider:query(_,callback) callback(nil,"Steam offline") end
assert(W.refresh());assert(W.items["123"]==map and W.message=="Steam offline")
-- A native binding may retain only a weak reference to the Lua callback.
local weak=setmetatable({}, {__mode="v"})
function provider:query(_,callback) weak[1]=callback end
assert(W.refresh());collectgarbage("collect");assert(weak[1])
weak[1]({app_id=provider.app_id,items={map},has_more=false})
assert(not W.busy and next(W.pending)==nil)
print("Steam Workshop adapter and presentation checks passed")
