local Heightmap = {}

local function read_height(source, index, little_endian)
    local offset = index * 2 + 1
    local first, second = source:byte(offset, offset + 1)
    if not first or not second then
        error(string.format("R16 sample out of bounds: index=%s, bytes=%d", tostring(index), #source), 0)
    end
    if little_endian then return first + second * 0x100 end
    return first * 0x100 + second
end

function Heightmap.load(map)
    local definition = map.terrain.source
    local source, message = map.__read(definition.file)
    if not source then error(message, 0) end
    local width, height = definition.vertices[1], definition.vertices[2]
    local expected = width * height * 2
    if #source ~= expected then
        error(string.format(
            "heightmap %s has %d bytes; expected %d",
            definition.file, #source, expected), 0)
    end
    local origin = map.terrain.origin_centimeters or {
        -map.terrain.size_meters[1] * 50.0,
        -map.terrain.size_meters[2] * 50.0,
        0.0,
    }
    return {
        map = map,
        bytes = source,
        width = width,
        height = height,
        spacing_cm = definition.spacing_meters * 100.0,
        origin_x = origin[1],
        origin_y = origin[2],
        origin_z = origin[3] or 0.0,
        height_scale_cm = definition.height_scale_meters * 100.0,
        height_offset_cm = definition.height_offset_meters * 100.0,
        little_endian = definition.format == "r16le",
        row_order = definition.row_order or "north_to_south",
        runtime = map.terrain.runtime or {},
    }
end

function Heightmap.sample_raw(state, column, row)
    column = math.max(0, math.min(state.width - 1, column))
    row = math.max(0, math.min(state.height - 1, row))
    if state.row_order == "south_to_north" then
        row = state.height - 1 - row
    end
    return read_height(
        state.bytes, row * state.width + column, state.little_endian)
end

function Heightmap.sample_grid_cm(state, column, row)
    return state.origin_z + state.height_offset_cm
        + Heightmap.sample_raw(state, column, row) * state.height_scale_cm
end

function Heightmap.height_at(state, x, y)
    local gx = (x - state.origin_x) / state.spacing_cm
    local gy = (y - state.origin_y) / state.spacing_cm
    if gx < 0 or gy < 0 or gx > state.width - 1 or gy > state.height - 1 then
        return nil
    end
    local x0, y0 = math.floor(gx), math.floor(gy)
    local x1 = math.min(state.width - 1, x0 + 1)
    local y1 = math.min(state.height - 1, y0 + 1)
    local tx, ty = gx - x0, gy - y0
    local north = Heightmap.sample_grid_cm(state, x0, y0) * (1.0 - tx)
        + Heightmap.sample_grid_cm(state, x1, y0) * tx
    local south = Heightmap.sample_grid_cm(state, x0, y1) * (1.0 - tx)
        + Heightmap.sample_grid_cm(state, x1, y1) * tx
    return north * (1.0 - ty) + south * ty
end

-- Unreal also uses the Landscape's vertical range as the altitude UI limit.
-- Encode native textures from zero so their range includes the source datum,
-- while keeping the portable samples and visible world positions unchanged.
function Heightmap.native_state(state)
    if state.native_encoding then return state.native_encoding end
    if state.height_offset_cm <= 0 then return state end
    local scale = (state.height_offset_cm + state.height_scale_cm * 65536) / 65536
    local chunks, batch = {}, {}
    for offset = 1, #state.bytes, 2 do
        local first, second = state.bytes:byte(offset, offset + 1)
        local raw = state.little_endian and first + second * 256 or first * 256 + second
        local encoded = math.floor((state.height_offset_cm + raw * state.height_scale_cm) / scale + 0.5)
        encoded = math.max(0, math.min(65535, encoded))
        batch[#batch + 1] = string.char(encoded % 256, math.floor(encoded / 256))
        if #batch == 4096 then
            chunks[#chunks + 1], batch = table.concat(batch), {}
        end
    end
    if #batch > 0 then chunks[#chunks + 1] = table.concat(batch) end
    state.native_encoding = setmetatable({bytes=table.concat(chunks),
        height_offset_cm=0,height_scale_cm=scale,little_endian=true}, {__index=state})
    return state.native_encoding
end

return Heightmap
