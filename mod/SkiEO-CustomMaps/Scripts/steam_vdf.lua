-- Small bounded reader for Steam's local appworkshop_*.acf inventory.
local Vdf = {}
function Vdf.decode(source)
    assert(type(source) == "string" and #source <= 16 * 1024^2, "Steam inventory exceeds limit")
    local position, tokens = 1, {}
    while position <= #source do
        local char = source:sub(position, position)
        if char:match("%s") then position = position + 1
        elseif source:sub(position, position + 1) == "//" then
            position = (source:find("\n", position, true) or #source) + 1
        elseif char == "{" or char == "}" then
            tokens[#tokens + 1] = char; position = position + 1
        elseif char == '"' then
            local value, closed = {}, false; position = position + 1
            while position <= #source do
                char = source:sub(position, position); position = position + 1
                if char == '"' then closed = true; break end
                if char == "\\" then
                    local next_char = source:sub(position, position)
                    if next_char == "\\" or next_char == '"' then char = next_char; position = position + 1 end
                end
                value[#value + 1] = char
            end
            assert(closed, "unterminated Steam inventory string")
            tokens[#tokens + 1] = table.concat(value)
        else error("invalid Steam inventory") end
    end
    local index = 1
    local function section(depth, nested)
        assert(depth <= 32, "Steam inventory nesting exceeds limit")
        local result = {}
        while index <= #tokens do
            local key = tokens[index]; index = index + 1
            if key == "}" then assert(nested, "unexpected closing brace"); return result end
            assert(key ~= "{" and tokens[index], "invalid Steam inventory key")
            local value = tokens[index]; index = index + 1
            assert(value ~= "}", "missing Steam inventory value")
            result[key] = value == "{" and section(depth + 1, true) or value
        end
        assert(not nested, "unclosed Steam inventory section")
        return result
    end
    return section(0, false)
end
return Vdf
