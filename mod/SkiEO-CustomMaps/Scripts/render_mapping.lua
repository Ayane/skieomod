local RenderMapping = {}
local NOT_READY = "error: supported terrain renderer settings were not found"

-- Cache completion and scene-extension registration run independently.
-- Retry only the missing-extension result, keeping all ownership checks in
-- the native helper. Invalid jobs and unsupported layouts fail immediately.
function RenderMapping.install(attempt, done, is_current, progress)
    local pending = {count=0}
    function pending:cancel()
        self.cancelled = true
        if self.handle and type(CancelDelayedAction) == "function" then
            pcall(CancelDelayedAction, self.handle)
        end
        self.handle, self.delay, self.game = nil, nil, nil
    end
    local function run()
        if pending.cancelled or (is_current and not is_current()) then return end
        pending.count = pending.count + 1
        local ok, message = attempt()
        if ok or message ~= NOT_READY or pending.count >= 40 then
            pending:cancel()
            done(ok, message)
            return
        end
        if progress then progress("Waiting for native terrain renderer", 0.15) end
        pending.game = function() pending.handle = nil; run() end
        pending.delay = function()
            if not pending.cancelled then ExecuteInGameThread(pending.game) end
        end
        if type(ExecuteInGameThreadWithDelay) == 'function' then
            pending.handle = ExecuteInGameThreadWithDelay(100, pending.game)
        else
            pending.handle = ExecuteWithDelay(100, pending.delay)
        end
    end
    run()
    return pending
end

return RenderMapping
