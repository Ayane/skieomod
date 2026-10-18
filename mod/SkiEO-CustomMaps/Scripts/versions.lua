local Versions = {}
local function parts(value)
    assert(type(value) == "string", "version must be a string")
    local core = value:match("^([^+]+)")
    local major, minor, patch, tail = core:match("^(%d+)%.(%d+)%.(%d+)(.*)$")
    assert(major and (tail == "" or tail:match("^%-[A-Za-z0-9.-]+$")), "invalid semantic version: " .. value)
    local result = {tonumber(major), tonumber(minor), tonumber(patch)}
    local pre = {}
    if tail ~= "" then for token in tail:sub(2):gmatch("[^.]+") do pre[#pre + 1] = token end end
    return result, pre
end
function Versions.compare(a, b)
    local ac, ap = parts(a); local bc, bp = parts(b)
    for index = 1, 3 do if ac[index] ~= bc[index] then return ac[index] > bc[index] and 1 or -1 end end
    if #ap == 0 or #bp == 0 then return #ap == #bp and 0 or #ap == 0 and 1 or -1 end
    for index = 1, math.min(#ap, #bp) do
        if ap[index] ~= bp[index] then
            local an, bn = tonumber(ap[index]), tonumber(bp[index])
            if an and bn then return an > bn and 1 or -1 end
            if an or bn then return an and -1 or 1 end
            return ap[index] > bp[index] and 1 or -1
        end
    end
    return #ap == #bp and 0 or #ap > #bp and 1 or -1
end
function Versions.matches(version, range)
    range = range or "*"
    assert(type(range) == "string" and #range > 0 and #range <= 120, "invalid dependency range")
    if range == "*" then return not version:match("^([^+]+)"):find("-", 1, true) end
    local compatible, prerelease = true, false
    for token in range:gmatch("%S+") do
        local operator, expected = token:match("^([><=~^]+)(.+)$")
        if not operator then operator, expected = "=", token end
        local compared = Versions.compare(version, expected)
        prerelease = prerelease or expected:match("^([^+]+)"):find("-", 1, true) ~= nil
        if operator == "^" or operator == "~" then
            local core = parts(expected)
            local major, minor, patch = core[1], core[2], core[3]
            local upper
            if operator == "~" then upper = string.format("%d.%d.0", major, minor + 1)
            elseif major > 0 then upper = string.format("%d.0.0", major + 1)
            elseif minor > 0 then upper = string.format("0.%d.0", minor + 1)
            else upper = string.format("0.0.%d", patch + 1) end
            compatible = compatible and compared >= 0 and Versions.compare(version, upper) < 0
        else
            assert(operator == "=" or operator == ">=" or operator == "<=" or operator == ">" or operator == "<", "unsupported version operator")
            local match = operator == "=" and compared == 0 or operator == ">=" and compared >= 0 or operator == "<=" and compared <= 0 or operator == ">" and compared > 0 or operator == "<" and compared < 0
            compatible = compatible and match
        end
    end
    return compatible and (not version:match("^([^+]+)"):find("-", 1, true) or prerelease)
end
function Versions.dependencies(manifest)
    local seen = {}
    assert(manifest.dependencies == nil or type(manifest.dependencies) == "table", "dependencies must be an array")
    assert(#(manifest.dependencies or {}) <= 32, "too many dependencies")
    for _, dep in ipairs(manifest.dependencies or {}) do
        assert(type(dep) == "table" and type(dep.id) == "string" and dep.id:match("^[a-z0-9]+[._-][a-z0-9._-]+$"), "invalid dependency id")
        assert(dep.id ~= manifest.id and not seen[dep.id], "duplicate or self dependency")
        seen[dep.id] = true
        if dep.workshop_id ~= nil then
            local value = dep.workshop_id
            assert(type(value) == "string" and value:match("^[1-9]%d*$") and (#value < 20 or (#value == 20 and value < "18446744073709551615")), "invalid dependency Workshop ID")
        end
        Versions.matches("1.0.0", dep.version)
        assert(dep.optional == nil or type(dep.optional) == "boolean", "dependency.optional must be boolean")
    end
end
function Versions.resolve(manifest, mods)
    local by_id, ordered, selected, visiting, steps = {}, {}, {}, {}, 0
    for _, mod in ipairs(mods or {}) do by_id[mod.id] = by_id[mod.id] or {}; table.insert(by_id[mod.id], mod) end
    for _, candidates in pairs(by_id) do table.sort(candidates, function(a,b)
        local compared = Versions.compare(a.metadata.version, b.metadata.version)
        if compared == 0 then return a.__ue4ss_installed and not b.__ue4ss_installed or false end
        return compared > 0
    end) end
    local function search(pending, chosen, edges)
        steps = steps + 1; assert(steps <= 10000, "dependency graph too complex")
        if #pending == 0 then
            local active, done = {}, {}
            local function acyclic(id)
                if active[id] then return false end
                if done[id] then return true end
                active[id] = true
                for _, child in ipairs(edges[id] or {}) do if not acyclic(child) then return false end end
                active[id] = nil; done[id] = true; return true
            end
            for id in pairs(chosen) do if not acyclic(id) then return nil end end
            return chosen, edges
        end
        local dep = pending[1]
        local rest = {}; for i = 2, #pending do rest[#rest + 1] = pending[i] end
        if chosen[dep.id] then
            if Versions.matches(chosen[dep.id].metadata.version, dep.version) and (not dep.workshop_id or chosen[dep.id].__workshop and chosen[dep.id].__workshop.published_file_id == dep.workshop_id) then return search(rest, chosen, edges) end
            return nil
        end
        for _, mod in ipairs(by_id[dep.id] or {}) do
            if Versions.matches(mod.metadata.version, dep.version) and (not dep.workshop_id or mod.__workshop and mod.__workshop.published_file_id == dep.workshop_id) then
                local next_chosen, next_edges, next_pending = {}, {}, {}
                for id, value in pairs(chosen) do next_chosen[id] = value end
                for id, value in pairs(edges) do next_edges[id] = value end
                next_chosen[mod.id], next_edges[mod.id] = mod, {}
                for _, child in ipairs(mod.dependencies or {}) do
                    if not child.optional then next_pending[#next_pending + 1] = child; table.insert(next_edges[mod.id], child.id) end
                end
                for _, child in ipairs(rest) do next_pending[#next_pending + 1] = child end
                local result, graph = search(next_pending, next_chosen, next_edges)
                if result then return result, graph end
            end
        end
    end
    local pending = {}; for _, dep in ipairs(manifest.dependencies or {}) do if not dep.optional then pending[#pending + 1] = dep end end
    local graph
    selected, graph = search(pending, {}, {})
    assert(selected, "required mods are missing, conflicting or cyclic; install them before starting")
    local function visit(id)
        if visiting[id] then return end
        visiting[id] = true
        for _, child in ipairs(graph[id] or {}) do visit(child) end
        ordered[#ordered + 1] = selected[id]
    end
    for _, dep in ipairs(pending) do visit(dep.id) end
    return ordered
end
return Versions
