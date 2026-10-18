-- Small dependency-free JSON decoder for map manifests.
-- It intentionally decodes only JSON; manifests are never executed as Lua.
local json = {}

local function decode_error(source, position, message)
    local line = 1
    local column = 1
    for index = 1, position - 1 do
        if source:sub(index, index) == "\n" then
            line = line + 1
            column = 1
        else
            column = column + 1
        end
    end
    error(string.format("JSON line %d column %d: %s", line, column, message), 0)
end

local function utf8_character(codepoint)
    if codepoint <= 0x7f then
        return string.char(codepoint)
    elseif codepoint <= 0x7ff then
        return string.char(
            0xc0 + math.floor(codepoint / 0x40),
            0x80 + codepoint % 0x40)
    elseif codepoint <= 0xffff then
        return string.char(
            0xe0 + math.floor(codepoint / 0x1000),
            0x80 + math.floor(codepoint / 0x40) % 0x40,
            0x80 + codepoint % 0x40)
    end
    return string.char(
        0xf0 + math.floor(codepoint / 0x40000),
        0x80 + math.floor(codepoint / 0x1000) % 0x40,
        0x80 + math.floor(codepoint / 0x40) % 0x40,
        0x80 + codepoint % 0x40)
end

local function parser(source)
    local position = 1
    local length = #source

    local function skip_space()
        while position <= length and source:sub(position, position):match("%s") do
            position = position + 1
        end
    end

    local parse_value

    local function parse_string()
        if source:sub(position, position) ~= '"' then
            decode_error(source, position, "expected string")
        end
        position = position + 1
        local result = {}
        local segment_start = position
        while position <= length do
            local character = source:sub(position, position)
            if character == '"' then
                result[#result + 1] = source:sub(segment_start, position - 1)
                position = position + 1
                return table.concat(result)
            elseif character == "\\" then
                result[#result + 1] = source:sub(segment_start, position - 1)
                local escape = source:sub(position + 1, position + 1)
                local simple = {
                    ['"'] = '"', ["\\"] = "\\", ["/"] = "/",
                    b = "\b", f = "\f", n = "\n", r = "\r", t = "\t"
                }
                if simple[escape] then
                    result[#result + 1] = simple[escape]
                    position = position + 2
                elseif escape == "u" then
                    local hexadecimal = source:sub(position + 2, position + 5)
                    if not hexadecimal:match("^%x%x%x%x$") then
                        decode_error(source, position, "invalid Unicode escape")
                    end
                    local codepoint = tonumber(hexadecimal, 16)
                    position = position + 6
                    if codepoint >= 0xd800 and codepoint <= 0xdbff
                        and source:sub(position, position + 1) == "\\u" then
                        local low_text = source:sub(position + 2, position + 5)
                        local low = tonumber(low_text, 16)
                        if low and low >= 0xdc00 and low <= 0xdfff then
                            codepoint = 0x10000
                                + (codepoint - 0xd800) * 0x400
                                + (low - 0xdc00)
                            position = position + 6
                        end
                    end
                    if codepoint >= 0xd800 and codepoint <= 0xdfff then
                        decode_error(source, position, "unpaired Unicode surrogate")
                    end
                    result[#result + 1] = utf8_character(codepoint)
                else
                    decode_error(source, position, "invalid escape")
                end
                segment_start = position
            elseif character:byte() < 0x20 then
                decode_error(source, position, "control character in string")
            else
                position = position + 1
            end
        end
        decode_error(source, position, "unterminated string")
    end

    local function parse_number()
        local rest = source:sub(position)
        local token = rest:match("^-?%d+%.?%d*[eE][+-]?%d+")
            or rest:match("^-?%d+%.%d+")
            or rest:match("^-?%d+")
        if not token or token:match("^-?0%d") or token:match("%.[eE]") then
            decode_error(source, position, "invalid number")
        end
        local value = tonumber(token)
        if not value then
            decode_error(source, position, "number is out of range")
        end
        position = position + #token
        return value
    end

    local function parse_array()
        position = position + 1
        skip_space()
        local result = {}
        if source:sub(position, position) == "]" then
            position = position + 1
            return result
        end
        while true do
            result[#result + 1] = parse_value()
            skip_space()
            local separator = source:sub(position, position)
            if separator == "]" then
                position = position + 1
                return result
            elseif separator ~= "," then
                decode_error(source, position, "expected ',' or ']'")
            end
            position = position + 1
            skip_space()
        end
    end

    local function parse_object()
        position = position + 1
        skip_space()
        local result = {}
        if source:sub(position, position) == "}" then
            position = position + 1
            return result
        end
        while true do
            local key = parse_string()
            skip_space()
            if source:sub(position, position) ~= ":" then
                decode_error(source, position, "expected ':'")
            end
            position = position + 1
            local value = parse_value()
            if result[key] ~= nil then
                decode_error(source, position, "duplicate object key '" .. key .. "'")
            end
            result[key] = value
            skip_space()
            local separator = source:sub(position, position)
            if separator == "}" then
                position = position + 1
                return result
            elseif separator ~= "," then
                decode_error(source, position, "expected ',' or '}'")
            end
            position = position + 1
            skip_space()
        end
    end

    function parse_value()
        skip_space()
        local character = source:sub(position, position)
        if character == '"' then
            return parse_string()
        elseif character == "{" then
            return parse_object()
        elseif character == "[" then
            return parse_array()
        elseif character == "-" or character:match("%d") then
            return parse_number()
        elseif source:sub(position, position + 3) == "true" then
            position = position + 4
            return true
        elseif source:sub(position, position + 4) == "false" then
            position = position + 5
            return false
        elseif source:sub(position, position + 3) == "null" then
            position = position + 4
            return json.null
        end
        decode_error(source, position, "expected value")
    end

    local result = parse_value()
    skip_space()
    if position <= length then
        decode_error(source, position, "trailing data")
    end
    return result
end

json.null = setmetatable({}, { __tostring = function() return "null" end })

function json.decode(source)
    if type(source) ~= "string" then
        error("json.decode expects a string", 2)
    end
    return parser(source)
end

function json.encode(value)
    local active = {}
    local function encode(item)
        local kind = type(item)
        if item == json.null or kind == "nil" then return "null" end
        if kind == "boolean" then return tostring(item) end
        if kind == "number" then
            assert(item == item and item ~= math.huge and item ~= -math.huge, "nonfinite JSON number")
            return math.type(item)=='integer' and tostring(item) or string.format('%.17g', item)
        end
        if kind == "string" then
            return '"' .. item:gsub('[%z\001-\031\\"]', function(char)
                if char == '"' then return '\\"' end
                if char == '\\' then return '\\\\' end
                return string.format("\\u%04x", char:byte())
            end) .. '"'
        end
        assert(kind == "table" and not active[item], "unsupported or cyclic JSON value")
        active[item] = true
        local array, count = true, 0
        for key in pairs(item) do count = count + 1; if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then array = false end end
        array = array and count == #item
        local parts = {}
        if array then for _, child in ipairs(item) do parts[#parts + 1] = encode(child) end
        else
            local keys = {}; for key in pairs(item) do assert(type(key) == "string", "JSON object key must be string"); keys[#keys + 1] = key end
            table.sort(keys)
            for _, key in ipairs(keys) do parts[#parts + 1] = encode(key) .. ":" .. encode(item[key]) end
        end
        active[item] = nil
        return (array and "[" or "{") .. table.concat(parts, ",") .. (array and "]" or "}")
    end
    return encode(value)
end
return json
