package.path="mod/SkiEO-CustomMaps/Scripts/?.lua;"..package.path
local P=require("map_presentation")
local map=assert(require("catalog").load("mod/SkiEO-Veymont/custom-map.json"))
local card=P.card(map)
assert(card.title=="Veymont" and card.terrain=="8.06 × 12.10 km" and card.elevation=="745 – 2341 m")
assert(card.trails=="20" and card.lifts=="9" and #card.difficulties==3)
local source=assert(loadfile("mod/SkiEO-Veymont/Scripts/veymont_data.lua"))()
assert(#source.trails==tonumber(card.trails) and #source.lifts==tonumber(card.lifts),"presentation counts differ from actual Veymont data")
assert(P.matches(map,"Veymont France") and P.matches(map,"gresse") and not P.matches(map,"nordic"))
assert(P.matches(map,"[" )==false,"search interpreted a Lua pattern")
assert(P.preview_path(map)=="Preview/veymont.png")
local bytes=assert(map.__read(P.preview_path(map)))
local width,height=P.png_header(bytes);assert(width and height)
assert(P.preview_path(map,"loading")=="Preview/veymont-loading.png")
local loading=assert(map.__read(P.preview_path(map,"loading")))
local loading_width,loading_height=P.png_header(loading)
assert(loading_width==2048 and loading_height==1152 and loading~=bytes,"loading photo and map icon must be separate")
local definition=map.extensions["community.skieo.presentation"]
definition.loading_image=nil
assert(P.preview_path(map,"loading")==P.preview_path(map),"older maps must keep their shared illustration")
definition.loading_image="undeclared.png"
assert(not P.preview_path(map,"loading"),"loading artwork must be declared in content.assets")
definition.loading_image="Preview/veymont-loading.png"
assert(not P.png_header("bad"))
local remote={metadata={name="False title",description="Local description"},__workshop={published_file_id="123",title="Steam title",description="Steam text"},
    extensions={["community.skieo.presentation"]={trails=999,lifts=999,difficulties={"expert"},image="undeclared.png"}}}
card=P.card(remote)
assert(card.title=="Steam title" and card.description=="Steam text")
assert(card.trails=="—" and card.lifts=="—" and #card.difficulties==0 and not P.preview_path(remote))
map.extensions["community.skieo.presentation"]={trails=-1,lifts=0.5,difficulties={"unknown"}}
card=P.card(map);assert(card.trails=="—" and card.lifts=="—" and #card.difficulties==0)
local mod={metadata={name="Local mod",version="1.0.0",description="Tools"},runtime="ue4ss"}
assert(P.card(mod).description:find("startup registration required",1,true))
print("Map presentation: installed manifest facts, Veymont counts, Steam provenance, literal search and bounded PNGs OK")

assert(P.matches(map,"Albatar","local") and not P.matches(map,"","web"))
assert(P.matches(remote,"Steam","workshop") and not P.matches(remote,"","local"))
local web={id="author.web",metadata={name="Web Valley",description="Snow",authors={"Creator"}},__remote={}}
assert(P.matches(web,"Creator","web") and not P.matches(web,"Snow","local"))
web.__read=function() end
assert(P.matches(web,"author.web","local") and P.matches(web,"valley","web"))
assert(not P.matches(web,"","unknown"))
