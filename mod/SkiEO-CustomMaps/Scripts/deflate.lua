-- Bounded raw RFC 1951 reader. The Windows helper accelerates large members;
-- this implementation keeps format tests and small archives portable.
local Deflate = {}
local chars = {}
for value = 0, 255 do chars[value] = string.char(value) end

function Deflate.inflate(source, expected)
    assert(type(expected) == "number" and expected >= 0 and expected <= 1024^3, "invalid DEFLATE limit")
    local byte, bits, buffer = 1, 0, 0
    local function take(count)
        while bits < count do
            local value = source:byte(byte)
            assert(value, "truncated DEFLATE data")
            buffer = buffer + value * 2^bits
            bits, byte = bits + 8, byte + 1
        end
        local value = buffer % 2^count
        buffer, bits = math.floor(buffer / 2^count), bits - count
        return value
    end
    local function tree(lengths)
        local counts, codes, next_code = {}, {}, {}
        local maximum = 0
        for _, length in ipairs(lengths) do
            assert(length >= 0 and length <= 15, "invalid Huffman length")
            if length > 0 then counts[length] = (counts[length] or 0) + 1; maximum = math.max(maximum, length) end
        end
        local code, left = 0, 1
        for length = 1, 15 do
            left = left * 2 - (counts[length] or 0)
            assert(left >= 0, "oversubscribed Huffman tree")
            code = (code + (counts[length - 1] or 0)) * 2
            next_code[length], codes[length] = code, {}
        end
        for index, length in ipairs(lengths) do
            if length > 0 then
                local forward, reverse = next_code[length], 0
                next_code[length] = forward + 1
                for _ = 1, length do reverse = reverse * 2 + forward % 2; forward = math.floor(forward / 2) end
                codes[length][reverse] = index - 1
            end
        end
        return function()
            local value = 0
            for length = 1, maximum do
                value = value + take(1) * 2^(length - 1)
                local symbol = codes[length][value]
                if symbol ~= nil then return symbol end
            end
            error("invalid Huffman symbol", 0)
        end
    end
    local window, chunk, output, count = {}, {}, {}, 0
    local function emit(value)
        assert(count < expected, "DEFLATE exceeds declared size")
        window[count % 32768 + 1] = value
        count = count + 1
        chunk[#chunk + 1] = chars[value]
        if #chunk == 32768 then output[#output + 1] = table.concat(chunk); chunk = {} end
    end
    local lengths = {3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258}
    local length_bits = {0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0}
    local distances = {1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577}
    local distance_bits = {0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13}
    local final
    repeat
        final = take(1)
        local kind = take(2)
        if kind == 0 then
            take(bits % 8)
            local size, inverse = take(16), take(16)
            assert(size + inverse == 65535, "invalid DEFLATE stored block")
            for _ = 1, size do emit(take(8)) end
        else
            assert(kind ~= 3, "invalid DEFLATE block type")
            local literal_lengths, distance_lengths = {}, {}
            if kind == 1 then
                for symbol = 0, 287 do literal_lengths[symbol + 1] = symbol < 144 and 8 or symbol < 256 and 9 or symbol < 280 and 7 or 8 end
                for symbol = 1, 32 do distance_lengths[symbol] = 5 end
            else
                local literal_count, distance_count, code_count = take(5) + 257, take(5) + 1, take(4) + 4
                assert(literal_count <= 286, "invalid DEFLATE literal count")
                local order = {16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15}
                local code_lengths = {}
                for symbol = 1, 19 do code_lengths[symbol] = 0 end
                for index = 1, code_count do code_lengths[order[index] + 1] = take(3) end
                local decode, combined = tree(code_lengths), {}
                while #combined < literal_count + distance_count do
                    local symbol = decode()
                    if symbol < 16 then combined[#combined + 1] = symbol
                    else
                        local repeated, value
                        if symbol == 16 then assert(#combined > 0, "invalid DEFLATE repeat"); repeated, value = take(2) + 3, combined[#combined]
                        elseif symbol == 17 then repeated, value = take(3) + 3, 0
                        else repeated, value = take(7) + 11, 0 end
                        assert(#combined + repeated <= literal_count + distance_count, "DEFLATE repeat overflow")
                        for _ = 1, repeated do combined[#combined + 1] = value end
                    end
                end
                for index = 1, literal_count do literal_lengths[index] = combined[index] end
                for index = 1, distance_count do distance_lengths[index] = combined[literal_count + index] end
            end
            assert(literal_lengths[257] and literal_lengths[257] > 0, "DEFLATE end marker missing")
            local literal, distance = tree(literal_lengths), tree(distance_lengths)
            while true do
                local symbol = literal()
                if symbol < 256 then emit(symbol)
                elseif symbol == 256 then break
                else
                    local index = symbol - 256
                    assert(lengths[index], "invalid DEFLATE length")
                    local size = lengths[index] + take(length_bits[index])
                    local offset_symbol = distance() + 1
                    assert(distances[offset_symbol], "invalid DEFLATE distance")
                    local offset = distances[offset_symbol] + take(distance_bits[offset_symbol])
                    assert(offset <= math.min(count, 32768), "DEFLATE distance outside history")
                    for _ = 1, size do emit(window[(count - offset) % 32768 + 1]) end
                end
            end
        end
    until final == 1
    assert(count == expected, "DEFLATE size mismatch")
    assert(byte - math.floor(bits / 8) == #source + 1, "trailing DEFLATE data")
    output[#output + 1] = table.concat(chunk)
    return table.concat(output)
end
return Deflate
