local json, Catalog, Mods, Versions = require("json"), require("catalog"), require("mod_catalog"), require("versions")
local Repository = {remote = {}, errors = {}, busy = false, message = "", installed = {}}
local function registry_key(repo) return repo.registry_url or repo.url end
function Repository.entries(repo) return Repository.remote[registry_key(repo)] or {} end
local directory = debug.getinfo(1, "S").source:match("^@(.*[/\\])[^/\\]+$")
local function read(path)
    local file = io.open(path, "rb"); if not file then return nil end
    local source = file:read("*a"); file:close(); return source
end
local function write(path, source)
    local file = assert(io.open(path .. ".part", "wb")); assert(file:write(source)); file:close()
    os.remove(path); assert(os.rename(path .. ".part", path))
end
local function decode(path, fallback)
    local source = read(path)
    if not source then return fallback end
    local ok, value = pcall(json.decode, source)
    return ok and value or fallback
end
local function safe_origin(url)
    return type(url) == "string" and #url < 240 and (url:match("^https://[A-Za-z0-9.%-]+$") or url:match("^https://[A-Za-z0-9.%-]+:%d+$")) ~= nil
end
local function encode_query(value)
    return value:gsub("([^A-Za-z0-9_.~-])", function(char) return string.format("%%%02X", char:byte()) end)
end
local queue, active, native, idle_callbacks = {}, nil, nil, {}
function Repository.when_idle(callback)
    if Repository.busy then idle_callbacks[#idle_callbacks+1]=callback
    else callback() end
    return true
end
local function notify_idle()
    while not Repository.busy and #idle_callbacks > 0 do
        table.remove(idle_callbacks,1)()
    end
end
local function run_next()
    if active or #queue == 0 then return end
    active = table.remove(queue, 1)
    local request = active
    if not native then
        native = directory and package.loadlib(directory .. "skieo_repository.dll", "skieo_fetch")
    end
    if not native then active = nil; request.callback(nil, "network helper unavailable; reinstall Custom Map"); run_next(); return end
    local staged, failure = pcall(function()
        local file = assert(io.open(directory .. "network.job", "wb"))
        file:write(string.pack("<c4I4c64", "SKRQ", request.maximum, request.sha or string.rep(" ", 64)), request.url); file:close()
        os.remove(directory .. "network.status"); os.remove(directory .. "network.response")
        os.remove(directory .. "network.progress")
        native()
    end)
    if not staged then active = nil; request.callback(nil, tostring(failure)); run_next(); return end
    local function poll()
        local status = read(directory .. "network.status")
        if request.progress then
            local received,total=(read(directory .. "network.progress") or ""):match("^(%d+)/(%d+)$")
            if received and tonumber(total)>0 then request.progress(math.min(1,tonumber(received)/tonumber(total))) end
        end
        if not status then request.schedule(); return end
        active = nil
        if status == "ok" then request.callback(directory .. "network.response") else request.callback(nil, status) end
        run_next()
    end
    request.poll = poll -- UE4SS keeps weak references to delayed callbacks.
    request.dispatch = function()
        if type(ExecuteInGameThread) == 'function' then ExecuteInGameThread(poll) else poll() end
    end
    request.schedule = function()
        if type(ExecuteInGameThreadWithDelay) == 'function' then ExecuteInGameThreadWithDelay(100, poll)
        else ExecuteWithDelay(100, request.dispatch) end
    end
    request.schedule()
end
local function fetch(url, maximum, sha, callback, progress)
    queue[#queue + 1] = {url = url, maximum = maximum, sha = sha, callback = callback, progress=progress}
    run_next()
end
local function validate_release(release, origin)
    assert(type(release) == "table" and type(release.id) == "string" and release.id:match("^[a-z0-9]+[._-][a-z0-9._-]+$") and #release.id <= 120, "invalid repository package id")
    assert(release.kind == "map" or release.kind == "mod", "invalid package kind")
    assert(type(release.version) == "string" and #release.version <= 80 and release.version:match("^[0-9A-Za-z.+-]+$"), "invalid package version")
    Versions.compare(release.version, release.version)
    assert(type(release.sha256) == "string" and #release.sha256 == 64 and release.sha256:match("^[0-9a-f]+$"), "invalid repository SHA-256")
    assert(type(release.size) == "number" and release.size > 0 and release.size % 1 == 0 and release.size <= (release.kind == "map" and 512 or 256) * 1024^2, "invalid package size")
    assert(type(release.unpacked_size) == "number" and release.unpacked_size > 0
        and release.unpacked_size % 1 == 0 and release.unpacked_size <= 1024^3, "invalid unpacked size")
    local featured_url = origin == "https://skieomod.emillon.fr"
        and origin .. "/downloads/" .. release.id .. "-" .. release.version
            .. (release.kind == "map" and ".skieomap" or ".skieomod")
    assert(release.download_url == origin .. "/api/v1/downloads/" .. release.id .. "/" .. release.version
        or release.download_url == featured_url, "package download must stay in its repository")
    local manifest = release.kind == "map" and Catalog.validate(release.manifest) or Mods.validate(release.manifest)
    assert(manifest.id == release.id and manifest.metadata.version == release.version, "repository manifest identity mismatch")
    return manifest
end
Repository.validate_release = validate_release
local function accept_registry(source, origin, name)
    assert(#source <= 16 * 1024^2, "registry exceeds 16 MiB")
    local registry = json.decode(source)
    assert(registry.format == "skieo-registry" and registry.version == 1 and type(registry.packages) == "table" and #registry.packages <= 1024, "unsupported registry")
    local maps, seen = {}, {}
    for _, release in ipairs(registry.packages) do
        local manifest = json.decode(json.encode(validate_release(release, origin)))
        local key = manifest.id .. "@" .. release.version
        assert(not seen[key], "duplicate registry release"); seen[key] = true
        manifest.__remote = {origin = origin, name = name, release = release}
        manifest.__web, manifest.__unavailable = true, true
        maps[#maps + 1] = manifest
    end
    local next_offset = registry.next_offset
    if next_offset == json.null then next_offset = nil end
    assert(next_offset == nil or (type(next_offset) == "number" and next_offset >= 128 and next_offset <= 1024 and next_offset % 128 == 0), "invalid registry cursor")
    return maps, next_offset
end
function Repository.initialize(config)
    if not directory then return end
    config = config or decode(directory .. "repositories.json", {repositories = {}})
    Repository.remote = {}
    Repository.repositories = {}
    for index, repo in ipairs(config.repositories or {}) do
        if type(repo)=="table" and repo.url=="https://skieomap.emillon.fr" then
            repo.url="https://skieomod.emillon.fr"
            if repo.registry_url=="https://skieomap.emillon.fr/downloads/featured-maps.json" then
                repo.registry_url=repo.url.."/downloads/featured-maps.json"
            end
        end
        if index <= 8 and type(repo) == "table" and safe_origin(repo.url)
            and (repo.registry_url == nil or repo.url == "https://skieomod.emillon.fr" and repo.registry_url == repo.url .. "/downloads/featured-maps.json")
            and (repo.cache_prefix == nil or repo.cache_prefix == "featured-") then
            Repository.repositories[#Repository.repositories + 1] = repo
            local combined, offset = {}, 0
            repeat
                local cache = read(directory .. (repo.cache_prefix or "repository-") .. index .. "-" .. offset .. ".json")
                if not cache then break end
                local ok, maps, cursor = pcall(accept_registry, cache, repo.url, repo.name or repo.url)
                if not ok then break end
                for _, map in ipairs(maps) do combined[#combined + 1] = map end
                if cursor and cursor <= offset then break end
                offset = cursor
            until not offset
            Repository.remote[registry_key(repo)] = combined
        end
    end
    Repository.installed = decode(directory .. "repository-installed.json", {})
end
function Repository.refresh(callback)
    if Repository.busy then return false end
    Repository.busy, Repository.errors, Repository.message = true, {}, "Refreshing web repositories…"
    local index = 0
    local function next_repo()
        index = index + 1
        local repo = (Repository.repositories or {})[index]
        if not repo then
            Repository.busy = false
            Repository.message = #Repository.errors > 0 and "Some repositories unavailable; cached catalogue retained" or "Web repositories refreshed"
            if callback then callback() end
            notify_idle()
            return
        end
        local combined, sources, seen = {}, {}, {}
        local function page(offset)
            fetch(repo.registry_url or repo.url .. "/api/v1/registry?offset=" .. offset, 16 * 1024^2, nil, function(path, failure)
                local ok, cursor = false, failure
                if path then
                    ok, cursor = pcall(function()
                        local source = assert(read(path))
                        local maps, next_offset = accept_registry(source, repo.url, repo.name or repo.url)
                        for _, map in ipairs(maps) do
                            local key = map.id .. "@" .. map.metadata.version
                            assert(not seen[key], "duplicate paginated release"); seen[key] = true
                            combined[#combined + 1] = map
                        end
                        sources[offset] = source
                        assert(not next_offset or not repo.registry_url and next_offset > offset, "registry cursor does not advance")
                        return next_offset
                    end)
                end
                if not ok then
                    Repository.errors[#Repository.errors + 1] = {path = repo.url, message = tostring(cursor)}
                    next_repo()
                elseif cursor then page(cursor)
                else
                    local stored, error_message = pcall(function()
                        for offset, source in pairs(sources) do write(directory .. (repo.cache_prefix or "repository-") .. index .. "-" .. offset .. ".json", source) end
                    end)
                    if stored then Repository.remote[registry_key(repo)] = combined
                    else Repository.errors[#Repository.errors + 1] = {path = repo.url, message = tostring(error_message)} end
                    next_repo()
                end
            end)
        end
        page(0)
    end
    next_repo(); return true
end
function Repository.merge(local_maps)
    local maps, by_id = {}, {}
    for _, map in ipairs(local_maps) do maps[#maps + 1] = map; by_id[map.id] = map; map.__update = nil end
    for _, repo in ipairs(Repository.repositories or {}) do
        for _, remote in ipairs(Repository.entries(repo)) do
            if remote.format.name == "skieo-map" then
            local installed = by_id[remote.id]
            if not installed then maps[#maps + 1] = remote; by_id[remote.id] = remote
            elseif Versions.compare(remote.metadata.version, (installed.__update or installed).metadata.version) > 0 then
                if installed.__remote then
                    for i, entry in ipairs(maps) do if entry == installed then maps[i] = remote; break end end
                    by_id[remote.id] = remote
                else installed.__update = remote end
            end
            end
        end
    end
    table.sort(maps, function(a,b) return a.metadata.name:lower() < b.metadata.name:lower() end)
    return maps
end
function Repository.local_packages(inventory_only)
    local maps, mods = {}, {}
    for _, relative in ipairs(Repository.installed) do
        if type(relative) == "string" and relative:match("^repository%-%w[%w._+-]*%.skieo[mapod]+$") then
            local package = relative:match("%.skieomap$") and Catalog.load(directory .. relative,inventory_only) or Mods.load(directory .. relative,inventory_only)
            if package then
                package.__web = true
                table.insert(relative:match("%.skieomap$") and maps or mods, package)
            end
        end
    end
    local desktop = decode(directory .. 'skieomod-installed.json', {})
    if desktop.format == 'skieomod-installed' and desktop.version == 1 and type(desktop.packages) == 'table' and #desktop.packages <= 1024 then
        for _, entry in ipairs(desktop.packages) do
            if type(entry) == 'table' and type(entry.path) == 'string' and #entry.path <= 2048 and not entry.path:find('[%z\1-\31]') and (entry.kind == 'map' or entry.kind == 'mod') then
                local absolute = entry.path:match('^[A-Za-z]:[/\\]') or entry.path:sub(1, 1) == '/'
                local path = absolute and entry.path or directory .. entry.path
                local package = entry.kind == 'map' and Catalog.load(path,inventory_only) or Mods.load(path,inventory_only)
                if package and package.id == entry.id and package.metadata.version == entry.version then
                    table.insert(entry.kind == 'map' and maps or mods, package)
                end
            end
        end
    end
    return maps, mods
end
function Repository.install(map, callback, local_mods, progress)
    if Repository.busy then return false end
    local remote = (map.__update and map.__update.__remote) or map.__remote
    if not remote and map.__read and Repository.repositories[1] then
        remote = {origin=Repository.repositories[1].url, local_root=true,
            release={id=map.id, version=map.metadata.version,
                manifest=json.decode(assert(map.__read('custom-map.json')))}}
    end
    if not remote then return false end
    local _, cached_mods = Repository.local_packages(true)
    local available = {}
    for _, mod in ipairs(local_mods or {}) do available[#available + 1] = mod end
    for _, mod in ipairs(cached_mods) do available[#available + 1] = mod end
    Repository.busy, Repository.message = true, "Resolving required mods…"
    if progress then progress(Repository.message,0) end
    local function finish(failure)
        Repository.busy = false
        Repository.message = failure and tostring(failure) or "Installed and verified; ready to play"
        if callback then callback(failure) end
        notify_idle()
    end
    local function resolved(source, failure)
        if not source then finish(failure); return end
        local ok, packages = pcall(function()
            local result = json.decode(source)
            assert(type(result.packages) == "table" and (#result.packages > 0 or remote.local_root) and #result.packages <= 64, "invalid dependency closure")
            local root, mods, seen = remote.local_root and remote.release.manifest or nil, {}, {}
            for _, mod in ipairs(available) do mods[#mods + 1] = mod end
            for _, release in ipairs(result.packages) do
                local manifest = validate_release(release, remote.origin)
                assert(not seen[release.id], "duplicate resolved package"); seen[release.id] = true
                if release.kind == "map" then assert(release.id == remote.release.id and release.version == remote.release.version and not root, "wrong root package"); root = manifest
                else
                    assert(manifest.runtime ~= "ue4ss", "This map needs a UE4SS mod. Use the website CLI installation command with --ue4ss-mods, then restart the game.")
                    mods[#mods + 1] = manifest
                end
            end
            assert(root, "root map missing from closure")
            Versions.resolve(root, mods)
            return result.packages
        end)
        if not ok then finish(packages); return end
        local index, installed = 0, {}
        local function next_package()
            index = index + 1
            local release = packages[index]
            if not release then
                for _, relative in ipairs(installed) do
                    local found = false; for _, old in ipairs(Repository.installed) do if old == relative then found = true end end
                    if not found then Repository.installed[#Repository.installed + 1] = relative end
                end
                local stored, failure = pcall(write, directory .. "repository-installed.json", json.encode(Repository.installed))
                finish(not stored and tostring(failure) or nil); return
            end
            -- Package files are immutable and versioned. Reuse an already
            -- installed dependency; a different version remains alongside it.
            if release.kind == "mod" then
                for _, mod in ipairs(available) do
                    if mod.__read and mod.id == release.id and mod.metadata.version == release.version then
                        next_package(); return
                    end
                end
            elseif map.__read and map.id == release.id and map.metadata.version == release.version then
                next_package(); return
            end
            Repository.message = string.format("Downloading %s (%d/%d)…", release.manifest.metadata.name, index, #packages)
            local stage=Repository.message
            if progress then progress(stage,(index-1)/#packages) end
            fetch(release.download_url, release.size, release.sha256, function(download, message)
                if not download then finish(message); return end
                local accepted, relative = pcall(function()
                    local loaded, error_message
                    if release.kind == "map" then
                        -- Catalog detects archive kind by extension.
                        local staged = directory .. "repository-staged.skieomap"
                        os.remove(staged); assert(os.rename(download, staged))
                        loaded, error_message = Catalog.load(staged); download = staged
                    else
                        loaded, error_message = Mods.load(download)
                    end
                    assert(loaded, error_message)
                    assert(loaded.id == release.id and loaded.metadata.version == release.version, "download manifest mismatch")
                    local manifest_name = release.kind == 'map' and 'custom-map.json' or 'custom-mod.json'
                    assert(json.encode(json.decode(assert(loaded.__read(manifest_name)))) == json.encode(release.manifest),
                        'download differs from catalogue manifest')
                    local suffix = release.kind == "map" and ".skieomap" or ".skieomod"
                    local relative = "repository-" .. release.id .. "-" .. release.version .. suffix
                    -- Use the digest in the name so remote updates never overwrite local authored files.
                    relative = "repository-" .. release.sha256 .. suffix
                    os.remove(directory .. relative); assert(os.rename(download, directory .. relative))
                    return relative
                end)
                if not accepted then finish(relative); return end
                installed[#installed + 1] = relative
                next_package()
            end,progress and function(fraction)
                progress(stage..string.format(" %d%%",math.floor(fraction*100)),(index-1+fraction)/#packages)
            end)
        end
        next_package()
    end
    if remote.local_root or remote.release.download_url:sub(1, #remote.origin + 11) == remote.origin .. "/downloads/" then
        local ok, result = pcall(function()
            local candidates = {}
            for _, mod in ipairs(available) do candidates[#candidates + 1] = mod end
            for _, repo in ipairs(Repository.repositories or {}) do
                for _, entry in ipairs(Repository.entries(repo)) do
                    if repo.url == remote.origin and entry.format.name == "skieo-mod" then candidates[#candidates + 1] = entry end
                end
            end
            local packages = {}
            for _, mod in ipairs(Versions.resolve(remote.release.manifest, candidates)) do
                assert(mod.runtime ~= "ue4ss", "Featured dependencies must use the map API")
                if mod.__remote then packages[#packages + 1] = mod.__remote.release end
            end
            if not remote.local_root then packages[#packages + 1] = remote.release end
            return json.encode({packages = packages})
        end)
        if ok then resolved(result) else finish(result) end
    else
        fetch(remote.origin .. "/api/v1/resolve?id=" .. encode_query(remote.release.id) .. "&version=" .. encode_query("=" .. remote.release.version), 16 * 1024^2, nil,
            function(path, failure) resolved(path and read(path), failure) end)
    end
    return true
end

function Repository.ensure_dependencies(map, mods, callback, progress)
    if pcall(Versions.resolve, map, mods) then if callback then callback() end; return true end
    if progress then progress("Checking required mods…",0) end
    return Repository.when_idle(function()
        Repository.refresh(function()
            if not Repository.install(map, callback, mods, progress) and callback then callback('Dependency download unavailable') end
        end)
    end)
end
Repository.initialize()
return Repository
