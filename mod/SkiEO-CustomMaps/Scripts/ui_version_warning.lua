local Theme = require('ui_theme')
local Version = require('game_version')
local Warning = {}

function Warning.create(screen,canvas,tree)
    local frame=Theme.construct('CanvasPanel',tree)
    -- New UMG widgets start visible. Hide the entire card before attaching it,
    -- including its background and shadow, while the version check is pending.
    frame:SetVisibility(1)
    screen.version_warning=frame
    Theme.place(canvas,frame,0,0,1200,72)
    local content=Theme.card(frame,tree,0,0,1200,72,Theme.color('FFF0CB'))
    -- Keep valid text even before the first result; the card is never empty.
    local initial=Version.classify(nil)
    screen.version_warning_title=Theme.label(content,tree,initial.title,screen.heading_style,18,Theme.color('804600'),20,8,1160,25)
    screen.version_warning_detail=Theme.label(content,tree,initial.detail,screen.text_style,14,Theme.color('604019'),20,34,1160,34)
    screen.version_warning_visible=false
end

function Warning.update(screen,version)
    local warning=version.supported==false
    if screen.version_warning_visible==warning then return end
    if warning then
        -- Populate and lay out while hidden. Showing the card is the final
        -- operation, so Slate cannot present an empty frame during the change.
        screen.version_warning:SetVisibility(2)
        screen.version_warning_title:SetText(FText(version.title))
        screen.version_warning_detail:SetText(FText(version.detail))
        screen.browser_body.Slot:SetPosition({X=0,Y=80})
        screen.browser_size:SetHeightOverride(670)
        screen.browser_size:ForceLayoutPrepass()
        screen.version_warning:SetVisibility(4)
    else
        screen.version_warning:SetVisibility(1)
        screen.browser_body.Slot:SetPosition({X=0,Y=0})
        screen.browser_size:SetHeightOverride(590)
    end
    screen.version_warning_visible=warning
end
return Warning
