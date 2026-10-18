package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local veymont=assert(loadfile('mod/SkiEO-Veymont/Scripts/veymont_data.lua'))()
local saint=assert(loadfile('mod/SkiEO-SuperSaintBernard/Scripts/station.lua'))()
local vbuild=assert(loadfile('mod/SkiEO-Veymont/Scripts/furnishings.lua'))()
local sbuild=assert(loadfile('mod/SkiEO-SuperSaintBernard/Scripts/furnishings.lua'))()
for _,case in ipairs({{vbuild,veymont,54,40},{sbuild,saint,14,8}}) do
    local objects=case[1](case[2]);assert(#objects==case[3])
    local ids,markers={},0
    for _,o in ipairs(objects) do
        local key=o.guid.A..':'..o.guid.D
        assert(not ids[key],'duplicate authored ID');ids[key]=true
        assert(o.kind=='decoration' and o.class:find('/Blueprints/Decorations/',1,true))
        assert(math.abs(o.position_cm[1])<480000 and math.abs(o.position_cm[2])<604800)
        if o.class:find('BP_TrailMarkers',1,true) then
            markers=markers+1;assert(o.variant=='Beginner' or o.variant=='Intermediate' or o.variant=='Expert')
        end
    end
    assert(markers==case[4])
    local repeated=case[1](case[2]);for i,o in ipairs(repeated) do assert(o.guid.D==objects[i].guid.D) end
end
print('Map furnishings: geographic anchors, stable native IDs, real difficulty variants and bounded counts OK')
