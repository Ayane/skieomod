-- UE4SS adds every discovered mod directory to package.path. Prefer this
-- installation's modules if an older copy remains in Content/Paks/~mods.
local source_directory = debug.getinfo(1, "S").source:match("^@(.*[/\\])[^/\\]+$")
-- Some UE4SS builds name the entry chunk just "main.lua". In that case the
-- global search path can pick the duplicate in ~mods for every dependency.
if not source_directory then
    for path in package.path:gmatch("[^;]+") do
        local normalized = path:gsub("\\", "/"):lower()
        if normalized:match("/skieo%-custommaps/scripts/%?%.lua$") then
            local directory = path:sub(1, -6)
            -- Disabled copies remain on UE4SS's module search path. Prefer
            -- a directory that still has its enabled entry script.
            local entry = io.open(directory .. "main.lua", "rb")
            if entry then
                entry:close()
                source_directory = directory
                break
            end
        end
    end
end
if source_directory then package.path = source_directory .. "?.lua;" .. package.path end

local Runtime = require("runtime")
local UI = require("ui")

local Compatibility=require('compatibility')
Compatibility.startup('input',function()require('map_input').install()end)
Compatibility.startup('entity_selection',function()require('entity_selection').install(function()return Runtime.active_api end)end)
Compatibility.startup('catalog',Runtime.refresh)
Compatibility.startup('events',Runtime.install_event_hooks)
Compatibility.startup('height_hooks',Runtime.terrain.install_height_hooks)
Compatibility.startup('ui',function()UI.install(Runtime)end)
Compatibility.startup('launch',function()require('launch').install(Runtime)end)

RegisterConsoleCommandHandler("custommaps", function(_, _, _)
    Runtime.refresh()
    if #Runtime.maps == 0 then
        Runtime.log("no valid custom maps are installed")
    end
    for index, map in ipairs(Runtime.maps) do
        Runtime.log(string.format(
            "%d. %s %s (%s)", index, map.metadata.name,
            map.metadata.version, map.id))
    end
    return true
end)

RegisterConsoleCommandHandler("custommap", function(_, parameters, _)
    Runtime.browse_kind = "map"
    local selector = parameters[1]
    local map = selector and Runtime.select(selector) or Runtime.selected()
    if not map then
        Runtime.log("unknown map; use 'custommaps' to list installed maps")
        return true
    end
    Runtime.play(map, UI.refresh)
    return true
end)

RegisterConsoleCommandHandler("custommap_reload", function(_, _, _)
    Runtime.refresh()
    UI.refresh()
    return true
end)

Runtime.log("ready; use New Game > Custom or the 'custommaps' console command")

RegisterConsoleCommandHandler('custommap_compatibility',function()
    ExecuteInGameThread(function()
        require('trail_ratings').capabilities()
        local entries=require('compatibility').snapshot()
        local names={};for name in pairs(entries) do names[#names+1]=name end;table.sort(names)
        for _,name in ipairs(names) do
            local entry=entries[name]
            Runtime.log(name..': '..(entry.available and 'available' or 'unavailable')..' — '..entry.detail)
        end
        Runtime.log('Feature checks only; full build qualification uses tools/check_game_compatibility.py')
    end)
    return true
end)

RegisterConsoleCommandHandler('custommap_test_snapshot',function(_,parameters)
    ExecuteInGameThread(function()
        local ok,failure=pcall(require('scenario_qa').capture,Runtime,parameters[1])
        if not ok then Runtime.log('QA checkpoint failed: '..tostring(failure)) end
    end)
    return true
end)
RegisterConsoleCommandHandler('custommap_test_resume',function()
    ExecuteInGameThread(function() require('scenario_qa').resume() end)
    return true
end)

RegisterConsoleCommandHandler("custommap_workshop", function()
    Runtime.refresh_workshop(UI.refresh)
    return true
end)

RegisterConsoleCommandHandler("custommap_install", function()
    Runtime.install_selected(UI.refresh)
    return true
end)

RegisterConsoleCommandHandler("custommap_status", function()
    ExecuteInGameThread(function()
        local terrain = Runtime.terrain
        local state = terrain.active
        Runtime.log("runtime module: " .. debug.getinfo(Runtime.start, "S").source)
        if state then
            Runtime.log(string.format("terrain: %dx%d, %d source bytes, generation %d",
                state.width, state.height, #state.bytes, terrain.generation))
        end
        local loading = require("loading")
        Runtime.log(string.format("loading: active=%s, stage=%s, progress=%s",
            tostring(loading.active), tostring(loading.stage), tostring(loading.fraction)))
    end)
    return true
end)
