local Theme = require("ui_theme")
local Presentation = require("map_presentation")
local Assets = {}
local DIRECTORY = debug.getinfo(1,"S").source:match("^@(.*[/\\])[^/\\]+$")

function Assets.preview(map,world,purpose)
    local path=map and Presentation.preview_path(map,purpose)
    if not path or type(map.__read)~="function" or not DIRECTORY then return nil end
    local ok,texture=pcall(function()
        local bytes=map.__read(path)
        if not Presentation.png_header(bytes) then return nil end
        local rendering=StaticFindObject("/Script/Engine.Default__KismetRenderingLibrary")
        if not Theme.valid(rendering) then return nil end
        -- Staging works for directory maps and .skieomap archives alike.
        local staged=DIRECTORY.."ui-preview.tmp.png"
        local file=io.open(staged,"wb")
        if not file then return nil end
        file:write(bytes);file:close()
        local imported,result=pcall(function() return rendering:ImportFileAsTexture2D(world,staged) end)
        os.remove(staged)
        if imported and Theme.valid(result) then return result end
    end)
    return ok and texture or nil
end

function Assets.picture(canvas,tree,texture,x,y,width,height,stretch)
    if not Theme.valid(texture) then return nil end
    local clip=Theme.construct("Border",tree)
    clip:SetPadding({Left=0,Top=0,Right=0,Bottom=0})
    clip:SetClipping(1)
    clip:SetVisibility(4)
    if width then Theme.place(canvas,clip,x,y,width,height)
    else Theme.anchor(canvas,clip,0,0,1,1) end
    local scale=Theme.construct("ScaleBox",tree)
    scale:SetStretch(stretch or 5) -- ScaleToFill: cover the frame while preserving proportions.
    clip:AddChild(scale)
    local image=Theme.construct("Image",tree)
    image:SetBrushFromTexture(texture,true)
    image:SetVisibility(4)
    scale:AddChild(image)
    return image,clip
end

function Assets.logo(world)
    local path="/Game/UI/Brand/T_SkiEOLogo.T_SkiEOLogo"
    for _,lookup in ipairs({StaticFindObject,LoadAsset}) do
        local ok,texture=pcall(lookup,path)
        if ok and Theme.valid(texture) then return texture end
    end
    for _,owner in ipairs(FindAllOf("MainMenuWidget") or {}) do
        local ok,texture=pcall(function() return owner.LogoTexture end)
        if ok and Theme.valid(texture) then return texture end
    end
    -- The supplied PNG is embedded in Lua so older update clients can still
    -- install this release. It stays byte-identical to the author's artwork.
    if not Theme.valid(world) or not DIRECTORY then return nil end
    local ok,texture=pcall(function()
        local rendering=StaticFindObject("/Script/Engine.Default__KismetRenderingLibrary")
        if not Theme.valid(rendering) then return nil end
        local staged=DIRECTORY.."ui-logo.tmp.png"
        local file=io.open(staged,"wb")
        if not file then return nil end
        local bytes=require("ui_logo")
        file:write(bytes);file:close()
        local imported,result=pcall(function() return rendering:ImportFileAsTexture2D(world,staged) end)
        os.remove(staged)
        if imported and Theme.valid(result) then return result end
    end)
    return ok and texture or nil
end

function Assets.fonts()
    local function snapshot(text)
        if not Theme.valid(text) then return nil end
        local font=text.Font
        local result={Size=font.Size,TypefaceFontName=font.TypefaceFontName}
        if Theme.valid(font.FontObject) then result.FontObject=font.FontObject end
        if Theme.valid(font.FontMaterial) then result.FontMaterial=font.FontMaterial end
        return result
    end
    for _,owner in ipairs(FindAllOf("NewGameDialogWidget") or {}) do
        if Theme.valid(owner) then
            local heading,body=snapshot(owner.KeyTitleText),snapshot(owner.DescriptionText)
            if heading and body then return {heading=heading,body=body} end
        end
    end
end
return Assets
