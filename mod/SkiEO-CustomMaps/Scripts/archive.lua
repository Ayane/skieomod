local Archive = {}
local Deflate = require("deflate")
local directory = debug.getinfo(1, "S").source:match("^@(.*[/\\])[^/\\]+$")
local bxor, rshift
if bit32 then bxor, rshift = bit32.bxor, bit32.rshift
else
    local loader = load("return function(a,b) return (a ~ b) & 0xffffffff end, function(a,b) return a >> b end")
    if loader then bxor, rshift = loader() end
end
local crc_table = {}
for index = 0, 255 do
    local value = index
    for _ = 1, 8 do value = bxor(rshift(value, 1), value % 2 == 1 and 0xedb88320 or 0) end
    crc_table[index] = value
end
function Archive.crc32(source)
    local crc = 0xffffffff
    for index = 1, #source do crc = bxor(rshift(crc, 8), crc_table[bxor(crc, source:byte(index)) % 256]) end
    return bxor(crc, 0xffffffff)
end
local function safe_path(path)
    if type(path) ~= "string" or path == "" or #path > 240 or path:sub(1, 1) == "/"
        or path:find('[\\<>:"|?*%z\001-\031]') or path:find("//", 1, true) or path:sub(-1) == "/" then return false end
    for part in path:gmatch("[^/]+") do
        local stem = (part:match("^([^.]+)") or ""):upper()
        if part == "." or part == ".." or part:match("[. ]$") or stem == "CON" or stem == "PRN" or stem == "AUX" or stem == "NUL" or stem:match("^COM[1-9]$") or stem:match("^LPT[1-9]$") then return false end
    end
    return true
end
Archive.safe_path = safe_path
local function u16(source, offset)
    local a, b = source:byte(offset, offset + 1)
    assert(b, "truncated ZIP integer")
    return a + b * 256
end
local function u32(source, offset)
    local a, b, c, d = source:byte(offset, offset + 3)
    assert(d, "truncated ZIP integer")
    return a + b * 256 + c * 65536 + d * 16777216
end
local function read_at(file, offset, size)
    assert(offset >= 0 and size >= 0, "invalid ZIP range")
    assert(file:seek("set", offset), "invalid ZIP offset")
    local source = file:read(size) or ""
    assert(#source == size, "truncated ZIP data")
    return source
end
local function parse(file)
    local size = assert(file:seek("end"))
    assert(size <= 512 * 1024^2, "ZIP exceeds 512 MiB")
    local tail_size = math.min(size, 65557)
    local tail = read_at(file, size - tail_size, tail_size)
    local eocd
    for cursor = #tail - 21, 1, -1 do
        if tail:sub(cursor, cursor + 3) == "PK\005\006" and cursor + 21 + u16(tail, cursor + 20) == #tail then eocd = cursor; break end
    end
    assert(eocd, "not a ZIP archive")
    local count, central_size, central_offset = u16(tail, eocd + 10), u32(tail, eocd + 12), u32(tail, eocd + 16)
    assert(u16(tail, eocd + 4) == 0 and u16(tail, eocd + 6) == 0 and u16(tail, eocd + 8) == count, "multi-volume ZIP unsupported")
    assert(count <= 4096 and count ~= 65535 and central_size <= 4 * 1024^2 and central_offset + central_size == size - tail_size + eocd - 1, "invalid ZIP central directory or unsupported ZIP64")
    local central = read_at(file, central_offset, central_size)
    local entries, seen, ranges, cursor, total = {}, {}, {}, 1, 0
    for _ = 1, count do
        assert(central:sub(cursor, cursor + 3) == "PK\001\002", "invalid ZIP central entry")
        local flags, method = u16(central, cursor + 8), u16(central, cursor + 10)
        local crc, compressed, unpacked = u32(central, cursor + 16), u32(central, cursor + 20), u32(central, cursor + 24)
        local name_size, extra_size, comment_size = u16(central, cursor + 28), u16(central, cursor + 30), u16(central, cursor + 32)
        local offset, attributes = u32(central, cursor + 42), u32(central, cursor + 38)
        local name = central:sub(cursor + 46, cursor + 45 + name_size)
        local is_directory = name:sub(-1) == "/"
        local normalized = is_directory and name:sub(1, -2) or name
        assert(safe_path(normalized) and not seen[normalized:lower()], "unsafe or duplicate ZIP path: " .. name)
        seen[normalized:lower()] = true
        assert(flags % 2 == 0 and (method == 0 or method == 8), "only unencrypted ZIP Store/Deflate supported")
        local unix_type = math.floor(attributes / 65536) % 65536
        unix_type = math.floor(unix_type / 4096)
        assert(unix_type == 0 or unix_type == 8 or unix_type == 4, "ZIP links and special files forbidden")
        assert(u16(central, cursor + 34) == 0 and compressed ~= 0xffffffff and unpacked ~= 0xffffffff, "ZIP64 or volume entry unsupported")
        total = total + unpacked
        assert(total <= 1024^3, "ZIP exceeds 1 GiB unpacked")
        local header = read_at(file, offset, 30)
        assert(header:sub(1, 4) == "PK\003\004" and u16(header, 7) == flags and u16(header, 9) == method, "ZIP local/central mismatch")
        local local_name_size, local_extra_size = u16(header, 27), u16(header, 29)
        assert(read_at(file, offset + 30, local_name_size) == name, "ZIP local name mismatch")
        if math.floor(flags / 8) % 2 == 0 then assert(u32(header, 15) == crc and u32(header, 19) == compressed and u32(header, 23) == unpacked, "ZIP local size/CRC mismatch") end
        local first = offset + 30 + local_name_size + local_extra_size
        assert(first + compressed <= central_offset, "ZIP entry overlaps central directory")
        ranges[#ranges + 1] = {offset, first + compressed}
        if not is_directory then entries[name] = {first = first, compressed = compressed, size = unpacked, method = method, crc = crc} end
        cursor = cursor + 46 + name_size + extra_size + comment_size
        assert(cursor <= #central + 1, "truncated ZIP central entry")
    end
    assert(cursor == #central + 1, "ZIP central directory length mismatch")
    table.sort(ranges, function(a,b) return a[1] < b[1] end)
    for index = 2, #ranges do assert(ranges[index][1] >= ranges[index-1][2], "overlapping ZIP entries") end
    return entries
end
local helper
local function inflate(source, entry)
    if not helper and directory and package.config:sub(1, 1) == "\\" then helper = package.loadlib(directory .. "skieo_repository.dll", "skieo_inflate") end
    if helper then
        local job = assert(io.open(directory .. "inflate.job", "wb"))
        job:write(string.pack("<c4I4I4", "SKDF", entry.size, entry.crc), source); job:close()
        os.remove(directory .. "inflate.status"); os.remove(directory .. "inflate.response")
        helper()
        local status = io.open(directory .. "inflate.status", "rb")
        local message = status and status:read("*a"); if status then status:close() end
        assert(message == "ok", message or "native DEFLATE failed")
        local file = assert(io.open(directory .. "inflate.response", "rb"))
        local result = file:read("*a"); file:close()
        os.remove(directory .. "inflate.job"); os.remove(directory .. "inflate.response"); os.remove(directory .. "inflate.status")
        return result, true
    end
    return Deflate.inflate(source, entry.size), false
end
function Archive.open(path)
    local file, message = io.open(path, "rb")
    if not file then return nil, message end
    local ok, entries = pcall(parse, file)
    file:close()
    if not ok then return nil, entries end
    return {path = path, entries = entries, has = function(_, name) return entries[name] ~= nil end,
        read = function(_, name)
            local entry = entries[name]
            if not entry then return nil, "archive member is missing: " .. tostring(name) end
            local input, failure = io.open(path, "rb")
            if not input then return nil, failure end
            local success, result = pcall(function()
                local source = read_at(input, entry.first, entry.compressed)
                local bytes, verified = source, false
                if entry.method == 8 then bytes, verified = inflate(source, entry) end
                assert(#bytes == entry.size, "ZIP size mismatch")
                assert(verified or Archive.crc32(bytes) == entry.crc, "ZIP CRC mismatch")
                return bytes
            end)
            input:close()
            if not success then return nil, result end
            return result
        end}
end
return Archive
