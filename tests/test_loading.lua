package.path = "mod/SkiEO-CustomMaps/Scripts/?.lua;" .. package.path
local world = { IsValid = function() return true end, GetAddress = function() return 1 end }
local controller = {
    IsValid = function() return true end, move = 0, look = 0,
    SetIgnoreMoveInput = function(self, value) self.move = self.move + (value and 1 or -1) end,
    SetIgnoreLookInput = function(self, value) self.look = self.look + (value and 1 or -1) end,
}
package.preload.UEHelpers = function() return {
    GetWorld = function() return world end,
    GetPlayerController = function() return controller end,
} end
-- This test isolates lifecycle/input handling; test_loading_view.lua covers
-- the reflected UMG and Slate-only presentation hosts.
package.preload.loading_view = function() return {
    build=function() return {} end, update=function() end,
} end
local widgets, timers = {}, {}
local function field()
    return { IsValid = function() return true end,
        SetText = function(self, text) self.text = text end }
end
local library = { IsValid = function() return true end }
function library:Create()
    local widget = {
        IsValid = function() return true end,
        IsInViewport = function(self) return self.visible end,
        AddToViewport = function(self) self.visible = true end,
        RemoveFromParent = function(self) self.visible = false end,
        SetVisibility = function() end,
        RootCanvas = { IsValid=function() return true end },
        TitleTextBlock = field(), StageTextBlock = field(), ProgressBar = field(),
    }
    widget.ProgressBar.SetFillColorAndOpacity = function() end
    widget.ProgressBar.SetIsMarquee = function() end
    widget.ProgressBar.SetPercent = function(self, value) self.percent = value end
    widgets[#widgets + 1] = widget
    return widget
end
StaticFindObject = function() return library end
FText = function(text) return text end
ExecuteInGameThread = function(callback) callback() end
ExecuteWithDelay = function(_, callback) timers[#timers + 1] = callback end
local Loading = require("loading")
Loading.show("Test map")
assert(widgets[1].visible and widgets[1].TitleTextBlock.text == "Test map")
assert(controller.move == 1 and controller.look == 1)
Loading.update("terrain", 0.5)
assert(widgets[1].ProgressBar.percent == 0.5)
assert(widgets[1].StageTextBlock.text == "terrain — 50 %")
-- Native travel may remove widgets; ClientRestart refresh restores ours.
widgets[1].visible = false
Loading.refresh()
assert(widgets[1].visible and #widgets == 1)
-- UE4SS may keep a valid wrapper whose old-world methods have retired.
widgets[1].visible = false
widgets[1].RemoveFromParent = function() error("retired old-world widget") end
world = { IsValid = function() return true end, GetAddress = function() return 2 end }
Loading.refresh()
assert(not widgets[1].visible and widgets[2].visible)
assert(controller.move == 1 and controller.look == 1)
Loading.hide()
assert(not widgets[2].visible and controller.move == 0 and controller.look == 0)
local before = #widgets
Loading.refresh()
assert(#widgets == before and not Loading.active)
-- A slowly advancing forest must finish even after five minutes of total
-- loading; stalled progress must still fail, and an old map must stop polling.
local queue, result, current_map = {}, nil, true
local api = {
    after=function(_,_,callback) queue[#queue+1]=callback end,
    _finish_loading=function(self,success,message)
        self._loading_finished=true;result={success,message}
    end,
}
Loading.watch_timeout(api,function() return current_map end)
local function poll() local callback=table.remove(queue,1);assert(callback);callback() end
for i=1,20 do Loading.update('forest',i/40);poll() end
assert(not result,'advancing load timed out after five minutes')
for _=1,10 do poll() end
assert(result and not result[1] and #queue==0,'stalled load did not fail')
api._loading_finished=false
Loading.watch_timeout(api,function() return current_map end)
current_map=false
poll()
assert(#queue==0,'an old map retained its loading watchdog')
print("Native loading lifecycle: OK")
