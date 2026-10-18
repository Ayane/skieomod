local json, Archive, Versions = require("json"), require("archive"), require("versions")
local Mods = {}
function Mods.validate(manifest)
    assert(type(manifest) == "table" and type(manifest.format) == "table" and manifest.format.name == "skieo-mod" and manifest.format.version:match("^1%.%d+%.%d+$"), "unsupported mod format")
    assert(type(manifest.id) == "string" and manifest.id:match("^[a-z0-9]+[._-][a-z0-9._-]+$"), "invalid mod id")
    assert(type(manifest.metadata) == "table" and type(manifest.metadata.name) == "string" and type(manifest.metadata.description) == "string" and type(manifest.metadata.authors) == "table", "invalid mod metadata")
    Versions.compare(manifest.metadata.version, manifest.metadata.version)
    Versions.dependencies(manifest)
    assert(manifest.runtime == nil or manifest.runtime == "map-api" or manifest.runtime == "ue4ss", "unsupported mod runtime")
    assert(type(manifest.files) == "table" and #manifest.files > 0 and #manifest.files <= 4095, "invalid mod files")
    local files = {}
    for _, path in ipairs(manifest.files) do assert(Archive.safe_path(path) and not files[path:lower()], "invalid mod file"); files[path:lower()] = true end
    if manifest.runtime ~= "ue4ss" then
        assert(type(manifest.script) == "table" and manifest.script.language == "lua" and type(manifest.script.api) == "string" and manifest.script.api:match("^1%.%d+$") and files[(manifest.script.entry or ""):lower()], "invalid mod script")
        for _, permission in ipairs(manifest.script.permissions or {}) do assert(permission == "gameplay" or permission == "skieo.unrestricted", "unsupported mod permission") end
        for _, path in ipairs((manifest.content or {}).assets or {}) do assert(files[path:lower()], "mod asset is not declared") end
    end
    return manifest
end
function Mods.load(path, inventory_only)
    local archive, read, root = nil, nil, path:match("^(.*)[/\\][^/\\]+$") or "."
    local function load()
        if path:match("%.json$") then
            read = function(name) local file = io.open(root .. "/" .. name, "rb"); if not file then return nil end; local value = file:read("*a"); file:close(); return value end
        else archive = assert(Archive.open(path)); read = function(name) return archive:read(name) end end
        local source = assert(read("custom-mod.json"), "custom-mod.json missing")
        assert(#source <= 1024^2, "mod manifest exceeds limit")
        local mod = Mods.validate(json.decode(source))
        for _, relative in ipairs(mod.files) do
            if inventory_only then
                if archive then assert(archive:has(relative),"missing mod file: "..relative)
                else
                    local file=assert(io.open(root.."/"..relative,"rb"),"missing mod file: "..relative)
                    file:close()
                end
            else assert(read(relative), "missing mod file: " .. relative) end
        end
        mod.__manifest_path, mod.__root, mod.__read, mod.__archive = path, root, read, archive
        mod.__inventory_only=inventory_only or nil
        if mod.script and not archive then mod.__script_path = root .. "/" .. mod.script.entry end
        -- A manifest discovered in an actual UE4SS mod directory is usable
        -- after startup; an archive merely downloaded beside maps is not.
        mod.__ue4ss_installed = mod.runtime == "ue4ss" and not archive and read("enabled.txt") ~= nil
        return mod
    end
    local ok, result = pcall(load)
    if ok then return result end
    return nil, result
end
function Mods.discover(tree, inventory_only)
    local paths, seen, result, errors = {}, {}, {}, {}
    local function walk(node, depth)
        if type(node) ~= "table" or seen[node] or depth > 32 then return end
        seen[node] = true
        for _, file in pairs(node.__files or {}) do
            local name = type(file) == "table" and file.__name
            if type(name) == "string" and type(file.__absolute_path) == "string" and (name == "custom-mod.json" or name:lower():match("%.skieomod$")) then paths[#paths + 1] = file.__absolute_path end
        end
        for key, child in pairs(node) do if key ~= "__files" then walk(child, depth + 1) end end
    end
    walk(tree or IterateGameDirectories(), 0)
    table.sort(paths)
    for _, path in ipairs(paths) do local mod, failure = Mods.load(path,inventory_only); if mod then result[#result + 1] = mod else errors[#errors + 1] = {path = path, message = tostring(failure)} end end
    return result, errors
end
return Mods
