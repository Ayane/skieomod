-- Keep the game's own loading widget over source terrain generation, which
-- continues after native level travel has already dismissed its loading UI.
local UEHelpers = require("UEHelpers")
local LoadingView = require("loading_view")
local Theme = require("ui_theme")
local Assets = require("ui_assets")
local Loading = { generation = 0, progress_revision = 0 }

local function valid(object) return object and object:IsValid() end

local function release_controller()
    if valid(Loading.controller) then
        pcall(function()
            Loading.controller:SetIgnoreMoveInput(false)
            Loading.controller:SetIgnoreLookInput(false)
        end)
    end
    Loading.controller = nil
end

function Loading.refresh()
    if not Loading.active then return end
    local world = UEHelpers.GetWorld()
    local controller = UEHelpers.GetPlayerController()
    if not valid(world) or not valid(controller) then return end
    local address = world:GetAddress()
    if Loading.world_address ~= address or not valid(Loading.widget) then
        if valid(Loading.widget) then pcall(function() Loading.widget:RemoveFromParent() end) end
        if valid(Loading.overlay) then pcall(function() Loading.overlay:RemoveFromParent() end) end
        release_controller()
        local library = StaticFindObject("/Script/UMG.Default__WidgetBlueprintLibrary")
        local widget_class = StaticFindObject("/Script/SkiResortSimulator.LoadingScreenWidget")
        assert(valid(library) and valid(widget_class), "native loading UI is unavailable")
        Loading.widget = library:Create(world, widget_class, controller)
        assert(valid(Loading.widget), "could not create native loading UI")
        Loading.world_address = address
        Loading.controller = controller
        local logo_ok,logo=pcall(Assets.logo,world)
        Loading.logo=logo_ok and logo or nil
        controller:SetIgnoreMoveInput(true)
        controller:SetIgnoreLookInput(true)
        Loading.view,Loading.overlay,Loading.view_attempted = nil,nil,false
    end
    local widget = Loading.widget
    if not widget:IsInViewport() then widget:AddToViewport(30000) end
    -- Visible, not HitTestInvisible: mouse clicks must not reach the world.
    widget:SetVisibility(0)
    -- Native UUserWidgets create their tree lazily when added to the viewport.
    if not Loading.view_attempted then
        Loading.view_attempted=true
        local decorated,view = pcall(function()
            local target=widget
            -- CL5545 draws the native loading screen directly in Slate. Its
            -- UMG tree has no root and its text/progress controls are private.
            -- Use a standard UMG host above it, with a root created before
            -- AddToViewport. Keep the native screen underneath as a fallback.
            if not valid(widget.RootCanvas) then
                if not valid(Loading.overlay) then
                    local library=StaticFindObject("/Script/UMG.Default__WidgetBlueprintLibrary")
                    Loading.overlay=library:Create(world,StaticFindObject("/Script/UMG.UserWidget"),controller)
                end
                assert(valid(Loading.overlay),"could not create loading card host")
                target=Loading.overlay
            end
            local result=LoadingView.build(target,Loading.map,world,Loading.title,Loading.logo,Loading.fonts)
            assert(result,"loading card host has no widget tree")
            if valid(Loading.overlay) then
                Loading.overlay:AddToViewport(30001)
                Loading.overlay:SetVisibility(0)
            end
            return result
        end)
        if decorated then Loading.view=view
        elseif not Loading.reported_view_error then
            Loading.reported_view_error=true
            print("[SkiEO-CustomMaps] loading card unavailable; using native UI: "..tostring(view).."\n")
        end
    end
    if valid(widget.TitleTextBlock) then widget.TitleTextBlock:SetText(FText(Loading.title)) end
    if valid(widget.StageTextBlock) then
        widget.StageTextBlock:SetText(FText(string.format("%s — %d %%", Loading.stage,
            math.floor(Loading.fraction * 100))))
    end
    if valid(widget.ProgressBar) then
        widget.ProgressBar:SetIsMarquee(false)
        widget.ProgressBar:SetFillColorAndOpacity(Theme.colors.coral)
        widget.ProgressBar:SetPercent(Loading.fraction)
    end
    LoadingView.update(Loading.view,Loading.stage,Loading.fraction)
end

local function safely_refresh()
    local ok, message = pcall(Loading.refresh)
    if not ok and not Loading.reported_error then
        Loading.reported_error = true
        print("[SkiEO-CustomMaps] loading UI failed: " .. tostring(message) .. "\n")
    end
end

function Loading.update(stage, fraction)
    fraction = math.max(0.0, math.min(1.0, fraction))
    if stage ~= Loading.stage or fraction ~= Loading.fraction then
        Loading.progress_revision = Loading.progress_revision + 1
    end
    Loading.stage = stage
    Loading.fraction = fraction
    safely_refresh()
end

-- A large portable forest can take longer in a background viewport. Fail
-- after five minutes without progress, rather than during an advancing load.
function Loading.watch_timeout(api, is_current)
    local revision, idle = Loading.progress_revision, 0
    local function check()
        if not is_current() or api._loading_finished then return end
        if revision == Loading.progress_revision then idle = idle + 1
        else revision, idle = Loading.progress_revision, 0 end
        if idle >= 10 then
            api:_finish_loading(false, "terrain/station initialization stopped progressing")
        else api:after(30000, check) end
    end
    api:after(30000, check)
end

function Loading.hide()
    Loading.active = false
    Loading.generation = Loading.generation + 1
    if valid(Loading.widget) then pcall(function() Loading.widget:RemoveFromParent() end) end
    if valid(Loading.overlay) then pcall(function() Loading.overlay:RemoveFromParent() end) end
    release_controller()
    Loading.widget, Loading.world_address = nil, nil
    Loading.view, Loading.overlay, Loading.map, Loading.logo, Loading.fonts = nil,nil,nil,nil,nil
    Loading.view_attempted=nil
end

function Loading.show(map)
    if Loading.active and type(map)=="table" and Loading.map and Loading.map.id==map.id then
        -- Acquisition and travel belong to the same load. Keep the native
        -- screen/input guard and replace only the card with verified artwork.
        if Loading.map~=map then
            if Loading.view and valid(Loading.view.root) then Loading.view.root:RemoveFromParent() end
            Loading.map,Loading.title=map,map.metadata.name
            Loading.view,Loading.view_attempted=nil,false
        end
        Loading.update("Opening map…",0.035)
        return
    end
    Loading.hide()
    Loading.map = type(map)=="table" and map or nil
    Loading.active, Loading.title, Loading.reported_error = true, Loading.map and Loading.map.metadata.name or map, false
    Loading.reported_view_error=false
    local fonts_ok,fonts=pcall(Assets.fonts)
    Loading.fonts=fonts_ok and fonts or nil
    Loading.update("Opening map…", 0.0)
    -- ClientRestart restores the widget after travel; tile progress refreshes
    -- it afterwards. Avoid an independent timer racing those game callbacks.
end

return Loading
