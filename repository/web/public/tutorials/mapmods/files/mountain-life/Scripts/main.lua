-- This mapmod writes field reports to the UE4SS log; it spawns no animals.
-- Its options, assets and saved counter belong to this package, not the map.
return function(api)
    local options = api:mapmod_options()
    if options.enabled == false then return end
    local label = type(options.label) == 'string' and options.label:sub(1, 80)
        or 'Mountain life'
    local welcome = api:read_asset('Data/welcome.txt'):gsub('%s+$', '')

    api:on('map.ready', function()
        local state = api:mod_state({reports = 0})
        api:log(label .. ': ' .. welcome)
        api:log('Saved field reports: ' .. state.reports)

        -- Timers follow the map session; explicitly respect the game's pause.
        api:every(30000, function()
            local environment = api:environment()
            if environment.paused or environment.ready == false then return end
            state.reports = state.reports + 1
            api:log(string.format('%s: field report %d, local hour %.1f',
                label, state.reports, environment.hour or 0))
        end)
    end)
end
