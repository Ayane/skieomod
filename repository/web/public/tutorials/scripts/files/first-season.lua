-- Starter scenario. Configure its economy in the visual map.ready trigger.
-- Paste this entire file into Project initialization • Lua, or use the sample ZIP.
return function(api)
    local state = api:state({status = 'active', balance = 250000, year = 2003, month = 11})
    local deadline_year, deadline_month, reserve = 2004, 4, 100000
    api:scenario({
        title = 'My first season', tracker_title = 'First season',
        briefing = 'Build a small resort. Reach April 2004 with at least 100,000 CHF left. A negative balance ends the scenario.',
        goal = 'Reach April 2004 with a cash reserve of 100,000 CHF.',
        deadline = 'April 2004',
        status = function() return state.status end,
        objectives = {
            {label = 'Keep a cash reserve', progress = function()
                return {value = string.format('%.0f / %d CHF', state.balance, reserve),
                    fraction = math.max(0, math.min(1, state.balance / reserve))}
            end},
            {label = 'Finish the first winter', progress = function()
                local months = (state.year - 2003) * 12 + state.month - 11
                return {value = string.format('%04d-%02d / 2004-04', state.year, state.month),
                    fraction = math.max(0, math.min(1, months / 5))}
            end}
        }
    })
    api:on('map.ready', function()
        local function check()
            local now = api.game:snapshot()
            state.balance, state.year, state.month = now.balance, now.year, now.month
            if state.status ~= 'active' then return end
            local deadline = now.year > deadline_year or now.year == deadline_year and now.month >= deadline_month
            if now.balance < 0 then state.status = 'failed'
            elseif deadline then state.status = now.balance >= reserve and 'completed' or 'failed' end
        end
        check()
        api:every(1000, check)
    end)
end
