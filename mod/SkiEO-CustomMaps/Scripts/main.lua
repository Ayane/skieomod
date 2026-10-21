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

-- Recover a prepared/interrupted update before importing gameplay hooks or DLLs.
-- This entry point and the small bootstrap DLL form update ABI v1.
if package.config and package.config:sub(1,1)=="\\" then
    assert(source_directory,'Custom Map bootstrap path unavailable')
    local status_path=source_directory..'update_bootstrap.status'
    os.remove(status_path)
    local recover=assert(package.loadlib(source_directory..'skieo_update_bootstrap.dll','skieo_update_recover'))
    recover()
    local file=io.open(status_path,'rb')
    local status=file and file:read(1024);if file then file:close() end
    assert(status=='ok',status or 'Custom Map update recovery failed; reinstall the mod')
end
local Runtime = require("entry")
