-- Pure presentation: only Steam-supplied fields appear on remote item cards.
local View = {}
function View.title(entry)
    return entry.__workshop and entry.__workshop.title or entry.metadata.name
end
function View.action(entry, state, busy)
    if not entry then return "Play", false end
    if state and (state.downloading or state.download_pending) then return "Downloading…", false end
    if entry.__featured then return "Play", true end
    if entry.__workshop then
        if state and state.unknown and entry.__unavailable then return "Unavailable", false end
        if state and state.needs_update then return "Update", true end
        if entry.__unavailable then return "Subscribe", true end
    end
    if entry.format and entry.format.name == "skieo-mod" then return "Installed", false end
    return "Play", true
end
function View.row(entry)
    return View.title(entry) .. (entry.__featured and "  [Featured]" or entry.__workshop and "  [Workshop]" or (entry.__web or entry.__remote) and "  [Web]" or "  [Local]")
end
function View.details(entry, state)
    if not entry then return "No maps or mods found. Refresh Workshop or build a local project." end
    local item, lines = entry.__workshop, {View.title(entry)}
    if item then
        lines[#lines + 1] = "Steam Workshop · " .. item.published_file_id
        if item.owner_name then lines[#lines + 1] = "Publisher: " .. item.owner_name
        elseif item.owner_steam_id then lines[#lines + 1] = "Publisher SteamID: " .. item.owner_steam_id end
        if item.updated_at then lines[#lines + 1] = "Updated: " .. os.date("!%Y-%m-%d %H:%M UTC", item.updated_at) end
        if item.votes_up ~= nil and item.votes_down ~= nil then lines[#lines + 1] = string.format("Votes: +%d / -%d", item.votes_up, item.votes_down) end
        if item.size_bytes then lines[#lines + 1] = string.format("Content: %.1f MiB", item.size_bytes / 1024^2) end
        if item.tags and #item.tags > 0 then lines[#lines + 1] = "Tags: " .. table.concat(item.tags, ", ") end
        if item.required_items and #item.required_items > 0 then lines[#lines + 1] = "Required Workshop items: " .. table.concat(item.required_items, ", ") end
        if state and state.bytes_total and state.bytes_total > 0 then lines[#lines + 1] = string.format("Download: %.0f%%", (state.bytes_downloaded or 0) * 100 / state.bytes_total) end
        if state and state.subscribed ~= nil then lines[#lines + 1] = state.subscribed and "Subscribed" or "Not subscribed" end
        if item.offline then lines[#lines + 1] = "Installed locally by Steam; live state unavailable" end
        lines[#lines + 1] = "\n" .. (item.description or entry.metadata.description or "")
    else
        lines[#lines + 1] = entry.__featured and "Featured · downloaded on Play" or (entry.__web or entry.__remote) and "Web · package " .. entry.metadata.version or "Local development · package " .. entry.metadata.version
        lines[#lines + 1] = "Credits: " .. table.concat(entry.metadata.authors or {}, ", ")
        lines[#lines + 1] = "\n" .. entry.metadata.description
    end
    -- Terrain is not part of UGC details: display only after loading a manifest.
    if entry.terrain then
        local size, elevation = entry.terrain.size_meters, entry.terrain.elevation_meters
        lines[#lines + 1] = string.format("\nTerrain: %.2f × %.2f km\nElevation: %.0f–%.0f m", size[1]/1000, size[2]/1000, elevation[1], elevation[2])
        if item then lines[#lines + 1] = "Installed package: " .. entry.metadata.version end
    end
    if entry.runtime == "ue4ss" and not entry.__ue4ss_installed then lines[#lines + 1] = "UE4SS startup registration required" end
    return table.concat(lines, "\n")
end
return View
