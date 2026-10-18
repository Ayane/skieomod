-- Small curated catalogue only; map payloads are fetched when Play is pressed.
local Repository, Versions = require("repository"), require("versions")
local Featured = {busy = false, message = ""}
local ORIGIN = "https://skieomod.emillon.fr"
local definitions = {
    ["community.super-saint-bernard"] = {format = {name = "skieo-map"}, id = "community.super-saint-bernard",
        metadata = {name = "Super Saint-Bernard", version = "0.0.0", authors = {"SkiEO Community"},
            description = "The Reprieve: save the resort from 2003 to 2011. Maintain ageing lifts, fund upgrades and face historical weather. Downloaded when you play."},
        location = {label = "Bourg-Saint-Pierre, Valais, Suisse"}},
    ["community.veymont"] = {format = {name = "skieo-map"}, id = "community.veymont",
        metadata = {name = "Veymont", version = "0.0.0", authors = {"Albatar (Élie Millon)"},
            description = "Build your mountain escape in the heart of the Vercors. Explore snowy forests and open meadows beneath the Grand Veymont and Mont Aiguille, develop your resort and watch for shy foxes between the trees."},
        location = {label = "Gresse-en-Vercors, France"}},
}
local curated = {name = "Featured", url = ORIGIN,
    registry_url = ORIGIN .. "/downloads/featured-maps.json", cache_prefix = "featured-"}
-- Keep the separately released curated maps alongside the community API.
-- Repository's default configuration includes the canonical community server.
local repositories = Repository.repositories or {}
local has_community = false
for _, repo in ipairs(repositories) do if repo.url == ORIGIN and not repo.registry_url then has_community = true end end
if not has_community then repositories[#repositories + 1] = {name = "SkiEO Mod", url = ORIGIN} end
repositories[#repositories + 1] = curated
Repository.initialize({repositories = repositories})

function Featured.local_packages(inventory_only)
    return Repository.local_packages(inventory_only)
end

function Featured.merge(installed)
    local maps, by_id = {}, {}
    for _, map in ipairs(installed) do
        map.__featured, map.__update = definitions[map.id] ~= nil, nil
        maps[#maps + 1], by_id[map.id] = map, map
    end
    for _, repo in ipairs(Repository.repositories or {}) do
        for _, remote in ipairs(Repository.entries(repo)) do
            if definitions[remote.id] then
                remote.__featured, remote.__unavailable = true, true
                local current = by_id[remote.id]
                if not current then maps[#maps + 1], by_id[remote.id] = remote, remote
                elseif Versions.compare(remote.metadata.version, (current.__update or current).metadata.version) > 0 then current.__update = remote end
            end
        end
    end
    for id, definition in pairs(definitions) do
        if not by_id[id] then
            local entry = {id = id, format = definition.format, metadata = definition.metadata,
                location = definition.location, __featured = true, __unavailable = true}
            maps[#maps + 1] = entry
        end
    end
    table.sort(maps, function(a, b) return a.metadata.name:lower() < b.metadata.name:lower() end)
    return maps
end

function Featured.refresh(callback)
    if Featured.busy or Repository.busy then return false end
    Featured.busy, Featured.message = true, "Checking web maps…"
    return Repository.refresh(function()
        Featured.busy = false
        Featured.message = #Repository.errors > 0 and "Some web catalogues unavailable; downloaded maps remain available" or "Web maps refreshed"
        if callback then callback() end
    end)
end

function Featured.ensure(map, maps, mods, callback, progress)
    if not map or not map.__featured then return false end
    -- A complete local release never waits for a registry request. Updates
    -- discovered by Refresh remain optional; Play uses the installed release.
    if map.__read and not map.__update and pcall(Versions.resolve,map,mods) then
        if callback then callback() end
        return true
    end
    local id = map.id
    local function finish(failure)
        Featured.busy = false
        Featured.message = failure and tostring(failure) or "Featured map ready to play"
        if callback then callback(failure) end
    end
    if progress then progress("Checking available map content…",0) end
    return Repository.when_idle(function() Featured.refresh(function()
        Featured.busy = true
        local current
        for _, entry in ipairs(Featured.merge(maps)) do if entry.id == id then current = entry; break end end
        if current and current.__read and not current.__update then
            if pcall(Versions.resolve, current, mods) then finish()
            elseif not Repository.install(current, finish, mods, progress) then finish('Dependency download unavailable') end
            return
        end
        if not current or not (current.__remote or current.__update) then finish("Featured map unavailable; connect to the project server and try again"); return end
        Featured.message = "Downloading featured map…"
        if not Repository.install(current, finish, mods, progress) then finish("Featured download already in progress") end
    end) end)
end

return Featured
