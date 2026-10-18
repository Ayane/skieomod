-- Data shared by the browser and loading screen. Remote cards use Steam's
-- title/description; installed terrain and counts come from the manifest.
local WorkshopView = require("workshop_view")
local Presentation = {}
local DIFFICULTIES = {"beginner","intermediate","advanced","expert"}
function Presentation.definition(entry)
    local value = entry and entry.extensions and entry.extensions["community.skieo.presentation"]
    return type(value)=="table" and value or {}
end
function Presentation.card(entry,state)
    if not entry then return {title="No map selected",subtitle="",description="Refresh Workshop or build a local project.",
        terrain="—",elevation="—",trails="—",lifts="—",difficulties={}} end
    local metadata,item=entry.metadata or {},entry.__workshop
    local definition=Presentation.definition(entry)
    local result={title=WorkshopView.title(entry),
        location=entry.location and entry.location.label or (entry.__featured and "Featured map" or item and "Steam Workshop" or (entry.__web or entry.__remote) and "Web map" or "Local map"),
        subtitle=entry.__featured and (entry.__read and "Featured · package "..(metadata.version or "") or "Featured · download on Play")
            or item and "Steam Workshop" or (entry.__web or entry.__remote) and (entry.__read and "Web · package "..(metadata.version or "") or "Web · download on Play") or "Local development · package "..(metadata.version or ""),
        credits=item and ("Publisher: "..(item.owner_name or item.owner_steam_id or "Steam community"))
            or "Credits: "..table.concat(metadata.authors or {},", "),
        description=item and item.description or metadata.description or "",
        terrain="—",elevation="—",trails="—",lifts="—",difficulties={},
        workshop_details=item and WorkshopView.details(entry,state) or nil}
    if entry.terrain then
        local size,elevation=entry.terrain.size_meters,entry.terrain.elevation_meters
        result.terrain=string.format("%.2f × %.2f km",size[1]/1000,size[2]/1000)
        result.elevation=string.format("%.0f – %.0f m",elevation[1],elevation[2])
        for _,key in ipairs({"trails","lifts"}) do
            local value=definition[key]
            if type(value)=="number" and value>=0 and value%1==0 then result[key]=tostring(value) end
        end
        for _,wanted in ipairs(DIFFICULTIES) do
            for _,name in ipairs(type(definition.difficulties)=="table" and definition.difficulties or {}) do
                if name==wanted then result.difficulties[#result.difficulties+1]=name;break end
            end
        end
    end
    if not item and entry.runtime=="ue4ss" and not entry.__ue4ss_installed then
        result.description=result.description.."\n\nUE4SS startup registration required"
    end
    return result
end
function Presentation.source_matches(entry,source)
    if not source or source=="all" then return true end
    if source=="local" then return not not entry.__read end
    if source=="web" then return not not (entry.__web or entry.__remote or entry.__featured) end
    if source=="workshop" then return entry.__workshop~=nil end
    return false
end
function Presentation.matches(entry,query,source)
    if not Presentation.source_matches(entry,source) then return false end
    if not query or query:match("^%s*$") then return true end
    local item,metadata=entry.__workshop,entry.metadata or {}
    local text=table.concat({WorkshopView.title(entry),entry.id or "",table.concat(metadata.authors or {}," "),metadata.description or "",
        item and item.description or "",entry.location and entry.location.label or "",
        table.concat(metadata.tags or {}," ")}," "):lower()
    for word in query:lower():gmatch("%S+") do if not text:find(word,1,true) then return false end end
    return true
end
function Presentation.preview_path(entry,purpose)
    local definition=Presentation.definition(entry)
    local path=purpose=="loading" and definition.loading_image or definition.image
    if type(path)~="string" or not path:lower():match("%.png$") then return nil end
    -- Only declared portable assets may reach the image importer.
    for _,asset in ipairs(entry.content and entry.content.assets or {}) do if asset==path then return path end end
end
function Presentation.png_header(bytes)
    if type(bytes)~="string" or #bytes<33 or #bytes>8*1024^2
        or bytes:sub(1,8)~="\137PNG\13\10\26\10" or bytes:sub(13,16)~="IHDR" then return nil end
    local width,height=string.unpack(">I4I4",bytes,17)
    if width<1 or height<1 or width>2048 or height>2048 or bytes:byte(25)~=8
        or (bytes:byte(26)~=2 and bytes:byte(26)~=6) then return nil end
    return width,height
end
return Presentation
