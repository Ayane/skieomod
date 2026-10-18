local json = require("json")
local Archive = require("archive")
local Versions = require("versions")

local Catalog = {}
local MANIFEST_NAME = "custom-map.json"
local GAME_BUILD = "25551097"
local COOKED_EXTENSIONS = { pak = true, ucas = true, utoc = true }

local function join_path(root, relative)
    local separator = root:find("\\", 1, true) and "\\" or "/"
    return root .. separator .. relative:gsub("/", separator)
end

local function directory_name(path)
    return path:match("^(.*)[/\\][^/\\]+$") or "."
end

local function is_safe_relative_path(path)
    if not Archive.safe_path(path) then return false end
    if type(path) ~= "string" or path == "" or path:sub(1, 1) == "/"
        or path:sub(1, 1) == "\\" or path:find("\\", 1, true)
        or path:find("//", 1, true) or path:sub(-1) == "/"
        or path:match("^[A-Za-z]:") then
        return false
    end
    for part in path:gmatch("[^/]+") do
        if part == "." or part == ".." then
            return false
        end
    end
    return true
end

local function assert_type(value, expected, label)
    if type(value) ~= expected then
        error(label .. " must be " .. expected, 0)
    end
end

local function assert_package_path(value, label)
    if type(value) ~= "string"
        or not value:match("^/Game/[A-Za-z0-9_./]+$") then
        error(label .. " is not a /Game package", 0)
    end
end

local function is_material_path(value)
    return type(value) == "string"
        and (value:match("^/Game/[A-Za-z0-9_./]+$")
            or value:match("^/Engine/[A-Za-z0-9_./]+$"))
end

local function add_reference(referenced, path, label)
    if not is_safe_relative_path(path) then
        error(label .. " is not a safe relative path", 0)
    end
    local extension = path:match("%.([^.]+)$")
    if extension and COOKED_EXTENSIONS[extension:lower()] then
        error(label .. " contains cooked Unreal data; .skieomap is source-only", 0)
    end
    referenced[#referenced + 1] = path
end

local function validate(manifest)
    assert_type(manifest, "table", "manifest")
    assert_type(manifest.format, "table", "format")
    if manifest.format.name ~= "skieo-map"
        or type(manifest.format.version) ~= "string"
        or not manifest.format.version:match("^1%.%d+%.%d+") then
        error("unsupported map format (expected skieo-map 1.x)", 0)
    end
    assert_type(manifest.id, "string", "id")
    if not manifest.id:match("^[a-z0-9]+[._-][a-z0-9._-]+$") then
        error("id must be lowercase and namespaced", 0)
    end
    assert_type(manifest.metadata, "table", "metadata")
    assert_type(manifest.metadata.name, "string", "metadata.name")
    assert_type(manifest.metadata.version, "string", "metadata.version")
    assert_type(manifest.metadata.description, "string", "metadata.description")
    Versions.compare(manifest.metadata.version, manifest.metadata.version)
    Versions.dependencies(manifest)
    local language = manifest.metadata.language or "en"
    assert_type(language, "string", "metadata.language")
    if not language:match("^[a-z][a-z][a-z]?%-?[A-Za-z0-9]*%-?[A-Za-z0-9]*$") then
        error("metadata.language must be a BCP 47 language tag", 0)
    end
    if manifest.metadata.localizations ~= nil then
        assert_type(manifest.metadata.localizations, "table", "metadata.localizations")
        for tag, localized in pairs(manifest.metadata.localizations) do
            if type(tag) ~= "string"
                or not tag:match("^[a-z][a-z][a-z]?%-?[A-Za-z0-9]*%-?[A-Za-z0-9]*$") then
                error("metadata.localizations keys must be BCP 47 language tags", 0)
            end
            assert_type(localized, "table", "metadata.localizations." .. tag)
            for _, field in ipairs({ "name", "description", "license" }) do
                if localized[field] ~= nil then
                    assert_type(localized[field], "string",
                        "metadata.localizations." .. tag .. "." .. field)
                end
            end
        end
    end
    assert_type(manifest.metadata.authors, "table", "metadata.authors")
    if #manifest.metadata.authors == 0 then error("metadata.authors is empty", 0) end
    local game = manifest.game
    if game == nil then game = {} end
    assert_type(game, "table", "game")
    if game.build and game.build ~= GAME_BUILD then
        error(string.format(
            "map targets game build %s; this loader targets %s",
            tostring(game.build), GAME_BUILD), 0)
    end
    if game.level ~= nil or game.initial_save ~= nil then
        error("game.level/initial_save are obsolete; maps initialize their own world", 0)
    end
    -- Older 1.x manifests may still name a template; it is never loaded.
    if game.template_level ~= nil then
        assert_package_path(game.template_level, "game.template_level")
    end
    assert_type(manifest.terrain, "table", "terrain")
    assert_type(manifest.terrain.size_meters, "table", "terrain.size_meters")
    assert_type(manifest.terrain.elevation_meters, "table", "terrain.elevation_meters")
    if #manifest.terrain.size_meters ~= 2
        or type(manifest.terrain.size_meters[1]) ~= "number"
        or type(manifest.terrain.size_meters[2]) ~= "number"
        or manifest.terrain.size_meters[1] <= 0
        or manifest.terrain.size_meters[2] <= 0 then
        error("terrain.size_meters must contain two positive numbers", 0)
    end
    if #manifest.terrain.elevation_meters ~= 2
        or type(manifest.terrain.elevation_meters[1]) ~= "number"
        or type(manifest.terrain.elevation_meters[2]) ~= "number"
        or manifest.terrain.elevation_meters[1] >= manifest.terrain.elevation_meters[2] then
        error("terrain.elevation_meters must contain an increasing range", 0)
    end
    assert_type(manifest.terrain.source, "table", "terrain.source")
    local source = manifest.terrain.source
    if source.format ~= "r16le" and source.format ~= "r16be" then
        error("terrain.source.format must be r16le or r16be", 0)
    end
    if type(source.vertices) ~= "table" or #source.vertices ~= 2
        or type(source.vertices[1]) ~= "number"
        or type(source.vertices[2]) ~= "number"
        or source.vertices[1] < 2 or source.vertices[1] % 1 ~= 0
        or source.vertices[2] < 2 or source.vertices[2] % 1 ~= 0 then
        error("terrain.source.vertices must contain two integers >= 2", 0)
    end
    if type(source.spacing_meters) ~= "number" or source.spacing_meters <= 0 then
        error("terrain.source.spacing_meters must be positive", 0)
    end
    for axis = 1, 2 do
        local expected = (source.vertices[axis] - 1) * source.spacing_meters
        if math.abs(manifest.terrain.size_meters[axis] - expected) > 0.000001 then
            error("terrain.size_meters must equal "
                .. "(vertices - 1) * spacing_meters", 0)
        end
    end
    if type(source.height_scale_meters) ~= "number"
        or source.height_scale_meters <= 0
        or type(source.height_offset_meters) ~= "number" then
        error("terrain source height scale/offset are invalid", 0)
    end
    if source.row_order ~= nil and source.row_order ~= "north_to_south"
        and source.row_order ~= "south_to_north" then
        error("terrain.source.row_order is invalid", 0)
    end
    if type(manifest.terrain.origin_centimeters) ~= "table"
        or #manifest.terrain.origin_centimeters ~= 3
        or type(manifest.terrain.origin_centimeters[1]) ~= "number"
        or type(manifest.terrain.origin_centimeters[2]) ~= "number"
        or type(manifest.terrain.origin_centimeters[3]) ~= "number" then
        error("terrain.origin_centimeters must contain X, Y and Z", 0)
    end
    local runtime = manifest.terrain.runtime
    if runtime ~= nil then
        assert_type(runtime, "table", "terrain.runtime")
        for _, name in ipairs({ "material", "snow_material", "skirt_material" }) do
            if runtime[name] ~= nil and not is_material_path(runtime[name]) then
                error("terrain.runtime." .. name
                    .. " is not a /Game or /Engine asset", 0)
            end
        end
        for _, name in ipairs({ "material_color", "snow_color", "skirt_color" }) do
            local color = runtime[name]
            if color ~= nil then
                if type(color) ~= "table" or (#color ~= 3 and #color ~= 4) then
                    error("terrain.runtime." .. name
                        .. " must contain three or four channels", 0)
                end
                for _, channel in ipairs(color) do
                    if type(channel) ~= "number" or channel < 0 or channel > 1 then
                        error("terrain.runtime." .. name
                            .. " channels must be within 0..1", 0)
                    end
                end
            end
        end
        if runtime.uv_tile_meters ~= nil
            and (type(runtime.uv_tile_meters) ~= "number"
                or runtime.uv_tile_meters <= 0) then
            error("terrain.runtime.uv_tile_meters must be positive", 0)
        end
        if runtime.snow_offset_centimeters ~= nil
            and (type(runtime.snow_offset_centimeters) ~= "number"
                or runtime.snow_offset_centimeters < 0) then
            error("terrain.runtime.snow_offset_centimeters must not be negative", 0)
        end
        local snow_bias=runtime.snow_surface_bias_centimeters
        if snow_bias~=nil and (type(snow_bias)~='number' or snow_bias~=snow_bias or math.abs(snow_bias)>100) then
            error('terrain.runtime.snow_surface_bias_centimeters must be -100..100',0)
        end
        if runtime.skirt_depth_meters ~= nil
            and (type(runtime.skirt_depth_meters) ~= "number"
                or runtime.skirt_depth_meters <= 0) then
            error("terrain.runtime.skirt_depth_meters must be positive", 0)
        end
        if runtime.skirt_enabled ~= nil
            and type(runtime.skirt_enabled) ~= "boolean" then
            error("terrain.runtime.skirt_enabled must be a boolean", 0)
        end
        if runtime.placeable_below_ground_tolerance_centimeters ~= nil
            and (type(runtime.placeable_below_ground_tolerance_centimeters)
                    ~= "number"
                or runtime.placeable_below_ground_tolerance_centimeters < 0) then
            error("terrain.runtime.placeable_below_ground_tolerance_centimeters must not be negative", 0)
        end
        if runtime.placeable_clearance_centimeters ~= nil
            and type(runtime.placeable_clearance_centimeters) ~= "number" then
            error("terrain.runtime.placeable_clearance_centimeters must be a number", 0)
        end
    end
    assert_type(manifest.terrain.preview, "table", "terrain.preview")
    local samples = manifest.terrain.preview.samples
    assert_type(samples, "table", "terrain.preview.samples")
    local width = nil
    if #samples < 3 or #samples > 33 then
        error("terrain preview must have 3..33 rows", 0)
    end
    for _, row in ipairs(samples) do
        assert_type(row, "table", "terrain preview row")
        width = width or #row
        if #row ~= width or width < 3 or width > 33 then
            error("terrain preview must be a rectangular 3..33 grid", 0)
        end
        for _, height in ipairs(row) do
            if type(height) ~= "number" or height < 0 or height > 1 then
                error("terrain preview values must be within 0..1", 0)
            end
        end
    end
    if manifest.location then
        assert_type(manifest.location, "table", "location")
        local latitude = manifest.location.latitude
        local longitude = manifest.location.longitude
        if type(latitude) ~= "number" or type(longitude) ~= "number"
            or latitude < -90 or latitude > 90
            or longitude < -180 or longitude > 180 then
            error("location must contain valid WGS84 coordinates", 0)
        end
        if manifest.location.world_map_uv then
            local position = manifest.location.world_map_uv
            if type(position) ~= "table" or #position ~= 2
                or type(position[1]) ~= "number" or type(position[2]) ~= "number"
                or position[1] < 0 or position[1] > 1
                or position[2] < 0 or position[2] > 1 then
                error("location.world_map_uv must contain two values within 0..1", 0)
            end
        end
    end
    local referenced = {}
    add_reference(referenced, source.file, "terrain.source.file")
    if manifest.terrain.textures ~= nil then
        assert_type(manifest.terrain.textures, "table", "terrain.textures")
        for channel, texture in pairs(manifest.terrain.textures) do
            if type(channel) ~= "string" or not channel:match("^[a-z][a-z0-9_]*$") then
                error("terrain texture channel must use a lowercase identifier", 0)
            end
            assert_type(texture, "table", "terrain.textures." .. channel)
            assert_type(texture.mips, "table", "terrain.textures." .. channel .. ".mips")
            if #texture.mips > 9 then error("terrain textures support at most nine additional mips", 0) end
            if texture.color_space ~= nil and texture.color_space ~= "srgb" and texture.color_space ~= "linear" then
                error("terrain texture color_space must be srgb or linear", 0)
            end
            local paths = {texture.file}
            for _, path in ipairs(texture.mips) do paths[#paths + 1] = path end
            -- Explicitly check file before constructing the array: nil would
            -- otherwise make a missing base image disappear from ipairs.
            add_reference(referenced, texture.file, "terrain texture file")
            for index, path in ipairs(paths) do
                if type(path) ~= "string" or not path:lower():match("%.png$") then
                    error("terrain textures must reference PNG images", 0)
                end
                if index > 1 then add_reference(referenced, path, "terrain texture mip") end
            end
        end
    end
    if runtime and runtime.texture_parameters ~= nil then
        assert_type(runtime.texture_parameters, "table", "terrain.runtime.texture_parameters")
        for channel, parameter in pairs(runtime.texture_parameters) do
            if not manifest.terrain.textures or not manifest.terrain.textures[channel]
                or type(parameter) ~= "string" or not parameter:match("^[A-Za-z][A-Za-z0-9_]*$") then
                error("texture_parameters must map declared channels to material parameter names", 0)
            end
        end
    end
    for channel in pairs(manifest.terrain.textures or {}) do
        if channel ~= "albedo" and not (runtime and runtime.texture_parameters and runtime.texture_parameters[channel]) then
            error("non-albedo texture channels need a runtime texture_parameters mapping", 0)
        end
    end
    assert_type(manifest.content, "table", "content")
    if manifest.content.containers ~= nil then
        error("content.containers is obsolete; custom maps may not embed cooked data", 0)
    end
    for _, asset in ipairs(manifest.content.assets or {}) do
        add_reference(referenced, asset, "content asset")
    end
    if manifest.script then
        if manifest.script.language ~= "lua" or type(manifest.script.api) ~= "string"
            or not manifest.script.api:match("^1%.%d+$") then
            error("only Lua script API 1.x is supported", 0)
        end
        add_reference(referenced, manifest.script.entry, "script.entry")
    end
    local seen = {}
    for _, path in ipairs(referenced) do
        if seen[path] then error("file is referenced more than once: " .. path, 0) end
        seen[path] = true
    end
    return manifest, referenced
end

function Catalog.load(path, inventory_only)
    local root = directory_name(path)
    local read
    local archive
    local source
    if path:lower():match("%.skieomap$") or path:lower():match("%.zip$") then
        local archive_error
        archive, archive_error = Archive.open(path)
        if not archive then return nil, archive_error end
        source, archive_error = archive:read(MANIFEST_NAME)
        if not source then return nil, archive_error end
        read = function(relative) return archive:read(relative) end
    else
        local file, open_error = io.open(path, "rb")
        if not file then return nil, open_error end
        source = file:read("*a")
        file:close()
        read = function(relative)
            local referenced_file, message = io.open(join_path(root, relative), "rb")
            if not referenced_file then return nil, message end
            local bytes = referenced_file:read("*a")
            referenced_file:close()
            return bytes
        end
    end
    if #source > 1024^2 then return nil, "map manifest exceeds 1 MiB" end
    local ok, manifest = pcall(json.decode, source)
    if not ok then
        return nil, manifest
    end
    local referenced
    ok, manifest, referenced = pcall(validate, manifest)
    if not ok then
        return nil, manifest
    end
    manifest.__manifest_path = path
    manifest.__root = root
    manifest.__archive = archive
    manifest.__read = read
    manifest.__inventory_only = inventory_only or nil
    for _, relative in ipairs(referenced) do
        local size
        if inventory_only then
            if archive then size=archive.entries[relative] and archive.entries[relative].size
            else
                local file=io.open(join_path(root,relative),"rb")
                if file then size=file:seek("end");file:close() end
            end
            if not size then return nil,"referenced file is missing: "..relative end
        else
            local bytes, read_error = read(relative)
            if not bytes then return nil, "referenced file cannot be read: " .. relative .. ": " .. tostring(read_error) end
            size=#bytes
        end
        if relative == manifest.terrain.source.file then
            local vertices = manifest.terrain.source.vertices
            local expected = vertices[1] * vertices[2] * 2
            if size ~= expected then
                return nil, string.format(
                    "terrain source has %d bytes; expected %d", size, expected)
            end
        end
    end
    if manifest.script and not archive then
        manifest.__script_path = join_path(manifest.__root, manifest.script.entry)
    end
    return manifest
end

local function installation_source(path)
    local normalized = path:gsub("\\", "/"):lower()
    return normalized:find("/.skieomod-backups/", 1, true)
        or normalized:find("/skieo-custommaps/examples/", 1, true)
end

local function collect_manifest_paths(node, result, visited, depth)
    if type(node) ~= "table" or visited[node] or depth > 32 then
        return
    end
    visited[node] = true
    -- IterateGameDirectories may expose directory entries through a proxy
    -- table.  Accessing __files normally keeps its metatable in play; rawget
    -- silently missed every manifest on the UE4SS build shipped with SkiEO.
    local files = node.__files
    if type(files) == "table" then
        for _, file in pairs(files) do
            if type(file) == "table" and file.__name == MANIFEST_NAME
                and type(file.__absolute_path) == "string"
                and not installation_source(file.__absolute_path) then
                result[#result + 1] = file.__absolute_path
            elseif type(file) == "table" and type(file.__name) == "string"
                and (file.__name:lower():match("%.skieomap$") or file.__name:lower():match("%.zip$"))
                and type(file.__absolute_path) == "string" then
                -- Distribution examples are installation sources. Only the
                -- installed copy belongs in the catalogue, including edits.
                if not installation_source(file.__absolute_path) then
                    result[#result + 1] = file.__absolute_path
                end
            end
        end
    end
    for key, child in pairs(node) do
        if key ~= "__files" and type(child) == "table" then
            collect_manifest_paths(child, result, visited, depth + 1)
        end
    end
end

function Catalog.discover(directory_tree, inventory_only)
    local paths = {}
    collect_manifest_paths(directory_tree or IterateGameDirectories(), paths, {}, 0)
    table.sort(paths)
    local maps = {}
    local errors = {}
    local identifiers = {}
    for _, path in ipairs(paths) do
        if path:lower():match("%.zip$") then
            local archive = Archive.open(path)
            if not archive or not archive:has(MANIFEST_NAME) then goto continue end
        end
        local manifest, load_error = Catalog.load(path, inventory_only)
        if not manifest then
            errors[#errors + 1] = { path = path, message = tostring(load_error) }
        elseif identifiers[manifest.id] then
            errors[#errors + 1] = {
                path = path,
                message = "duplicate map id; already provided by " .. identifiers[manifest.id]
            }
            for index, existing in ipairs(maps) do
                if existing.id == manifest.id and Versions.compare(manifest.metadata.version, existing.metadata.version) > 0 then
                    maps[index] = manifest
                    identifiers[manifest.id] = path
                    break
                end
            end
        else
            identifiers[manifest.id] = path
            maps[#maps + 1] = manifest
        end
        ::continue::
    end
    table.sort(maps, function(first, second)
        local first_name = first.metadata.name:lower()
        local second_name = second.metadata.name:lower()
        return first_name == second_name and first.id < second.id or first_name < second_name
    end)
    return maps, errors
end

Catalog.is_safe_relative_path = is_safe_relative_path
Catalog.join_path = join_path
Catalog.GAME_BUILD = GAME_BUILD
Catalog.validate = validate

return Catalog
