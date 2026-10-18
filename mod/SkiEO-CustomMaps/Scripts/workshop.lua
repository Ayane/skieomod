-- Steam is the sole remote catalogue. The game/native integration binds this
-- documented ISteamUGC adapter; absence is explicit, never an HTTP fallback.
local Json, Catalog, Mods, Versions, Vdf = require("json"), require("catalog"), require("mod_catalog"), require("versions"), require("steam_vdf")
local W = {items = {}, errors = {}, busy = false, message = "Steam Workshop client not connected", provider = nil, pending = {}}
local directory = debug.getinfo(1, "S").source:match("^@(.*[/\\])[^/\\]+$") or "./"
local function read(path)
    local file = io.open(path, "rb"); if not file then return nil end
    local value = file:read(16 * 1024^2 + 1); file:close()
    assert(#value <= 16 * 1024^2, "Workshop file exceeds limit")
    return value
end
local function decode(path, fallback)
    local ok, result = pcall(function() local text = read(path); return text and Json.decode(text) or fallback end)
    return ok and result or fallback
end
local function absolute(path)
    return path:match("^[A-Za-z]:[/\\]") or path:sub(1, 1) == "/"
end
function W.valid_id(value)
    return type(value) == "string" and value:match("^[1-9]%d*$") ~= nil and (#value < 20 or #value == 20 and value < "18446744073709551615")
end
local paths = decode(directory .. "workshop.json", {})
if paths.format ~= "skieomod-workshop-paths" or paths.version ~= 1 then paths = {} end
W.app_id = paths.app_id
function W.bind(provider)
    assert(type(provider) == "table" and provider.version == 1 and type(provider.app_id) == "string", "unsupported Steam Workshop adapter")
    assert(provider.app_id:match("^[1-9]%d*$") and #provider.app_id <= 10 and tonumber(provider.app_id) < 2^32, "invalid Steam AppID")
    if W.app_id then assert(provider.app_id == W.app_id, "Steam Workshop consumer AppID mismatch") end
    for _, method in ipairs({"query", "get_details", "subscribed_items", "get_item_state", "get_install_info", "subscribe_item", "download_item"}) do
        assert(type(provider[method]) == "function", "Steam Workshop adapter missing " .. method)
    end
    W.provider, W.app_id, W.message = provider, provider.app_id, "Steam Workshop connected"
end
local function state(id)
    if not W.provider then return {unknown = true} end
    local ok, result = pcall(W.provider.get_item_state, W.provider, id)
    return ok and type(result) == "table" and result or {unknown = true}
end
local function async(method, argument, callback)
    -- Native UE4SS integrations can hold weak Lua references. Keep one strong
    -- reference until completion, and ignore duplicate deliveries.
    local handler
    handler = function(...)
        if not W.pending[handler] then return end
        W.pending[handler] = nil
        callback(...)
    end
    W.pending[handler] = true
    local ok, failure = pcall(W.provider[method], W.provider, argument, handler)
    if not ok then W.pending[handler] = nil; error(failure, 0) end
end
function W.normalize(item)
    assert(type(item) == "table" and W.valid_id(item.published_file_id), "invalid Workshop item ID")
    assert(item.app_id == W.app_id, "Workshop consumer AppID mismatch")
    assert(item.result == 1 and not item.banned, "Workshop item is unavailable or banned")
    assert(type(item.title) == "string" and type(item.description) == "string", "invalid Workshop title/description")
    local summary = item.metadata
    if type(summary) == "string" then summary = Json.decode(summary) end
    if type(summary) == "table" and summary.format == "skieomod" and summary.version == 1 then item.kind = summary.kind end
    assert(item.kind == "map" or item.kind == "mod", "not a Custom Map Workshop item")
    for _, child in ipairs(item.required_items or {}) do assert(W.valid_id(child), "invalid Workshop child ID") end
    return item
end
local function load_item(item, folder, inventory_only)
    if type(folder) ~= "string" or #folder > 4096 or folder:find("[%z\1-\31]") then return nil, "invalid Workshop install path" end
    local path = folder .. (item.kind == "map" and "/custom-map.json" or "/custom-mod.json")
    local entry, failure
    if item.kind == "map" then entry, failure = Catalog.load(path,inventory_only) else entry, failure = Mods.load(path,inventory_only) end
    if not entry then return nil, failure end
    entry.__workshop = item
    -- Steam metadata is for discovery, not a replacement for the validated
    -- downloaded manifest. A mismatched logical ID is never accepted.
    local summary = item.metadata
    if type(summary) == "string" then local ok, value = pcall(Json.decode, summary); summary = ok and value or nil end
    if type(summary) == "table" and summary.id and summary.id ~= entry.id then return nil, "Workshop metadata/package ID mismatch" end
    return entry
end
function W.local_packages(inventory_only)
    local maps, mods, seen = {}, {}, {}
    local function add(item, folder)
        if seen[item.published_file_id] then return end
        seen[item.published_file_id] = true
        local entry, failure = load_item(item, folder, inventory_only)
        if entry then table.insert(item.kind == "map" and maps or mods, entry)
        else W.errors[#W.errors + 1] = {path = folder, message = tostring(failure)} end
    end
    if W.provider then
        for _, id in ipairs(W.provider:subscribed_items()) do
            assert(W.valid_id(id), "invalid subscribed Workshop ID")
            local current = state(id)
            if current.installed and not current.needs_update and not current.downloading and not current.download_pending then
                local info = W.provider:get_install_info(id)
                local item = W.items[id]
                if info and item then add(item, info.folder) end
            end
        end
    else
        -- Offline inventory: Steam's ACF decides which folders are complete.
        -- No fake owner, votes, subscription status or update date is invented.
        for _, root in ipairs(paths.content_roots or {}) do
            if type(root) == "string" then
                root = absolute(root) and root or directory .. root
                local acf = root .. "/../../appworkshop_" .. tostring(W.app_id) .. ".acf"
                local ok, inventory = pcall(function() return Vdf.decode(read(acf) or "") end)
                inventory = ok and inventory.AppWorkshop or nil
                if inventory and inventory.appid == W.app_id then
                    for id in pairs(inventory.WorkshopItemsInstalled or {}) do
                        if W.valid_id(id) then
                            local folder = root .. "/" .. id
                            local has_map, has_mod = read(folder .. "/custom-map.json"), read(folder .. "/custom-mod.json")
                            if (has_map ~= nil) ~= (has_mod ~= nil) then
                                local item = {published_file_id = id, app_id = W.app_id, kind = has_map and "map" or "mod", offline = true}
                                W.items[id] = item; add(item, folder)
                            end
                        end
                    end
                end
            end
        end
    end
    -- Local development artifacts stay usable without a Workshop subscription.
    local ledger = decode(directory .. "skieomod-installed.json", {})
    if ledger.format == "skieomod-installed" and ledger.version == 1 and type(ledger.packages) == "table" and #ledger.packages <= 1024 then
        for _, entry in ipairs(ledger.packages) do
            if type(entry.path) == "string" and #entry.path <= 2048 and not entry.path:find("[%z\1-\31]") and (entry.kind == "map" or entry.kind == "mod") then
                local path = absolute(entry.path) and entry.path or directory .. entry.path
                local package = entry.kind == "map" and Catalog.load(path,inventory_only) or Mods.load(path,inventory_only)
                if package and package.id == entry.id and package.metadata.version == entry.version then table.insert(entry.kind == "map" and maps or mods, package) end
            end
        end
    end
    return maps, mods
end
function W.merge(installed, kind)
    local result, seen = {}, {}
    for _, entry in ipairs(installed) do
        local id = entry.__workshop and entry.__workshop.published_file_id
        if not id or not seen[id] then result[#result + 1] = entry; if id then seen[id] = true end end
    end
    for id, item in pairs(W.items) do
        if item.kind == kind and not seen[id] and not item.offline then
            result[#result + 1] = {id = "workshop." .. id, metadata = {name = item.title, description = item.description, authors = {}},
                                  __workshop = item, __unavailable = true}
        end
    end
    table.sort(result, function(a,b) return (a.__workshop and a.__workshop.title or a.metadata.name):lower() < (b.__workshop and b.__workshop.title or b.metadata.name):lower() end)
    return result
end
function W.refresh(callback)
    if W.busy then return false end
    if not W.provider then W.message = "Steam Workshop client not connected; installed content and local projects are available"; if callback then callback() end; return false end
    W.busy, W.message = true, "Refreshing Steam Workshop…"
    local collected, page = {}, 1
    local function finish(failure)
        W.busy = false
        if not failure then W.items = collected end
        W.message = failure and tostring(failure) or "Steam Workshop refreshed"
        if callback then callback(failure) end
    end
    local function query()
        local completed = false
        local ok, failure = pcall(function() async("query", {page = page, kind = "all", search = "", return_metadata = true, return_children = true}, function(result, err)
            if completed then return end; completed = true
            if err then finish(err); return end
            local valid, error_message = pcall(function()
                assert(type(result) == "table" and result.app_id == W.app_id and type(result.items) == "table", "invalid Workshop query result")
                for _, item in ipairs(result.items) do item = W.normalize(item); collected[item.published_file_id] = item end
                assert(result.has_more ~= true or #result.items > 0, "empty Workshop page with more results")
            end)
            if not valid then finish(error_message); return end
            if result.has_more then page = page + 1; if page > 100 then finish("Workshop catalogue exceeds 100 pages") else query() end
            else finish() end
        end) end)
        if not ok and not completed then finish(failure) end
    end
    query(); return true
end
function W.ensure(entry, callback)
    if W.busy then return false end
    if not entry or not entry.__workshop then W.message = "Select a Steam Workshop item"; return false end
    if not W.provider then W.message = "Steam Workshop client not connected"; return false end
    W.busy, W.message = true, "Downloading Workshop content and required items…"
    local visiting, done, count = {}, {}, 0
    local finished = false
    local function finish(failure)
        if finished then return end; finished = true
        W.busy = false; W.message = failure and tostring(failure) or "Workshop content ready"
        if callback then callback(failure) end
    end
    local function visit(id, complete)
        if not W.valid_id(id) then complete("invalid required Workshop ID"); return end
        if done[id] then complete(); return end
        if visiting[id] then complete("cyclic Workshop dependency"); return end
        if not W.items[id] then
            local called = false
            local ok, failure = pcall(function() async("get_details", id, function(item, err)
                if called or finished then return end; called = true
                if err then complete(err); return end
                local valid, value = pcall(W.normalize, item)
                if not valid or value.published_file_id ~= id then complete(valid and "Workshop detail ID mismatch" or value); return end
                W.items[id] = value; visit(id, complete)
            end) end)
            if not ok then complete(failure) end
            return
        end
        count = count + 1; if count > 64 then complete("Workshop dependency closure exceeds 64 items"); return end
        visiting[id] = true
        local download_completed, subscribe_completed = false, false
        local function downloaded(result, failure)
            if download_completed or finished then return end; download_completed = true
            if failure then complete(failure); return end
            if not result or result.app_id ~= W.app_id or result.published_file_id ~= id or result.result ~= 1 then complete("Workshop download completion mismatch or failure"); return end
            local current = state(id)
            if not current.installed or current.needs_update or current.downloading or current.download_pending then complete("Workshop content is not fully installed"); return end
            local item = W.items[id]
            if not item then complete("Refresh Workshop before installing this dependency"); return end
            local info = W.provider:get_install_info(id)
            local package, error_message = load_item(item, info and info.folder)
            if not package then complete(error_message); return end
            local dependencies, seen = {}, {}
            for _, child in ipairs(item.required_items or {}) do dependencies[#dependencies + 1] = child; seen[child] = true end
            for _, dep in ipairs(package.dependencies or {}) do
                if not dep.optional then
                    if not W.valid_id(dep.workshop_id) then complete("Required mod lacks a Workshop ID: " .. dep.id); return end
                    if not seen[dep.workshop_id] then dependencies[#dependencies + 1] = dep.workshop_id; seen[dep.workshop_id] = true end
                end
            end
            local index = 0
            local function next_child(err)
                if err then complete(err); return end
                index = index + 1
                if dependencies[index] then visit(dependencies[index], next_child)
                else done[id] = package; visiting[id] = nil; complete() end
            end
            next_child()
        end
        local function subscribed(result, failure)
            if subscribe_completed or finished then return end; subscribe_completed = true
            if failure or not result or result.app_id ~= W.app_id or result.published_file_id ~= id or result.result ~= 1 then complete(failure or "Workshop subscription failed"); return end
            local current = state(id)
            if current.installed and not current.needs_update and not current.downloading and not current.download_pending then downloaded(result)
            else
                local ok, err = pcall(async, "download_item", id, downloaded)
                if not ok then complete(err) end
            end
        end
        local ok, failure = pcall(function() async("subscribe_item", id, subscribed) end)
        if not ok then complete(failure) end
    end
    visit(entry.__workshop.published_file_id, function(failure)
        if not failure then
            local root = done[entry.__workshop.published_file_id]
            local mods = {}; for _, package in pairs(done) do if package.format.name == "skieo-mod" then mods[#mods + 1] = package end end
            local ok, resolved = pcall(Versions.resolve, root, mods)
            if not ok then failure = resolved else
                for _, mod in ipairs(mods) do
                    if mod.runtime == "ue4ss" and not mod.__ue4ss_installed then failure = "UE4SS Workshop mod needs startup registration by the game: " .. mod.id; break end
                end
            end
        end
        finish(failure)
    end)
    return true
end
function W.open(entry)
    if W.provider and type(W.provider.open_workshop) == "function" then
        W.provider:open_workshop(entry and entry.__workshop and entry.__workshop.published_file_id or nil); return true
    end
    W.message = "Steam overlay not connected; open the game's Workshop in Steam"; return false
end
W.state = state
if type(rawget(_G, "SkiEOWorkshop")) == "table" then W.bind(SkiEOWorkshop) end
return W
