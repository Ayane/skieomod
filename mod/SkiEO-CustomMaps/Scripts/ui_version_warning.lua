local Theme = require('ui_theme')
local Version = require('game_version')
local Warning = {}

function Warning.create(screen,canvas,tree)
    local frame=Theme.construct('CanvasPanel',tree)
    -- Construct hidden with populated labels; never expose an empty card.
    frame:SetVisibility(1)
    screen.version_warning=frame
    Theme.place(canvas,frame,0,0,1200,104)
    local content=Theme.card(frame,tree,0,0,1200,104,Theme.color('FFF0CB'))
    local initial=Version.classify(nil)
    screen.version_warning_title=Theme.label(content,tree,initial.title,screen.heading_style,18,Theme.color('804600'),20,8,1160,25)
    screen.version_warning_detail=Theme.label(content,tree,initial.detail,screen.text_style,14,Theme.color('604019'),20,34,1160,34)
    screen.version_warning_update=Theme.label(content,tree,'Checking for a mod update…',screen.text_style,14,Theme.color('604019'),20,74,950,24)
    local restart=Theme.button(tree,'Restart game',screen.button_style,screen.text_style,Theme.colors.row,16,Theme.color('604019'))
    restart:SetVisibility(1)
    Theme.place(content,restart,990,66,190,32)
    screen.version_warning_restart=restart
    screen.version_warning_visible=false
end

function Warning.update(screen,version,update)
    if not screen.version_warning then return end
    local warning=version.supported==false
    update=update or {message='Checking for a mod update…'}
    local key=table.concat({tostring(warning),version.title or '',version.detail or '',update.message or '',tostring(update.can_restart)},'\n')
    if screen.version_warning_key==key then return end
    if warning then
        screen.version_warning:SetVisibility(2)
        screen.version_warning_title:SetText(FText(version.title))
        screen.version_warning_detail:SetText(FText(version.detail))
        screen.version_warning_update:SetText(FText(update.message))
        screen.version_warning_restart:SetVisibility(update.can_restart and 0 or 1)
        screen.browser_body.Slot:SetPosition({X=0,Y=112})
        screen.browser_size:SetHeightOverride(702)
        screen.browser_size:ForceLayoutPrepass()
        screen.version_warning:SetVisibility(4)
    else
        screen.version_warning:SetVisibility(1)
        screen.browser_body.Slot:SetPosition({X=0,Y=0})
        screen.browser_size:SetHeightOverride(590)
    end
    screen.version_warning_visible,screen.version_warning_key=warning,key
end
return Warning
