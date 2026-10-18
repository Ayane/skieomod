local UEHelpers = require("UEHelpers")
local NativeTerrain = require("native_terrain")
local Textures = {}
local DIRECTORY = debug.getinfo(1, "S").source:match("^@(.*[/\\])[^/\\]+$")

-- Only bounded RGB/RGBA PNGs enter the runtime importer. All mip levels are
-- portable images; Unreal owns the imported allocations and their full chain.
function Textures.png_size(bytes)
    assert(type(bytes) == "string" and #bytes >= 33
        and bytes:sub(1, 8) == "\137PNG\13\10\26\10"
        and bytes:sub(13, 16) == "IHDR", "terrain texture must be a PNG")
    local function u32(offset)
        local a,b,c,d = bytes:byte(offset, offset + 3)
        return ((a * 256 + b) * 256 + c) * 256 + d
    end
    local width, height = u32(17), u32(21)
    assert(width == height and width >= 1 and width <= 512
        and width == 2 ^ math.floor(math.log(width) / math.log(2) + 0.5),
        "terrain texture must be square with a power-of-two size up to 512")
    assert(bytes:byte(25) == 8 and (bytes:byte(26) == 2 or bytes:byte(26) == 6),
        "terrain texture must contain 8-bit RGB or RGBA pixels")
    return width
end

function Textures.load(map)
    local result = {}
    local definitions = map.terrain.textures or {}
    if next(definitions) == nil then return result end
    local rendering = StaticFindObject("/Script/Engine.Default__KismetRenderingLibrary")
    local update = StaticFindObject("/Script/Engine.CanvasRenderTarget2D:UpdateResource")
    local world = UEHelpers.GetWorld()
    assert(DIRECTORY and rendering:IsValid() and update:IsValid(), "terrain texture importer is unavailable")
    for channel, definition in pairs(definitions) do
        local paths = {definition.file}
        for _, path in ipairs(definition.mips) do paths[#paths + 1] = path end
        local sources, side = {}, nil
        for index, path in ipairs(paths) do
            local bytes, message = map.__read(path)
            assert(bytes, message)
            local size = Textures.png_size(bytes)
            if not side then side = size end
            assert(size == side / 2 ^ (index - 1), "terrain texture mip dimensions are inconsistent: " .. path)
            -- The package reader also handles .skieomap archives. Stage one
            -- small image at a time, and remove it immediately after import.
            local staged = DIRECTORY .. "portable_texture.png"
            local file = assert(io.open(staged, "wb"))
            file:write(bytes); file:close()
            local ok, texture = pcall(function() return rendering:ImportFileAsTexture2D(world, staged) end)
            os.remove(staged)
            assert(ok and texture and texture:IsValid(), "could not import terrain texture: " .. path)
            NativeTerrain.retain_texture(texture)
            assert(texture:Blueprint_GetSizeX() == size and texture:Blueprint_GetSizeY() == size,
                "imported terrain texture dimensions changed")
            texture.SRGB = (definition.color_space or "srgb") == "srgb"
            texture.NeverStream = true
            texture.Filter, texture.AddressX, texture.AddressY = 3, 0, 0
            sources[#sources + 1] = texture
        end
        assert(side / 2 ^ (#paths - 1) == 1, "terrain texture needs a complete mip chain down to 1x1")
        local installed, message = NativeTerrain.install_portable_texture_mips(sources)
        assert(installed, message)
        update(sources[1])
        result[channel] = sources[1]
    end
    return result
end

return Textures
