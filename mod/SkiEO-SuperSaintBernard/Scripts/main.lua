local Model,Data=require('survival'),require('station')
local Furnishings=require('furnishings')
local Json=require('json')
local function initialize(api)
    local state=api:state(Model.new())
    Model.restore(state)
    local weather=Json.decode(api:read_asset('Data/weather-2003-2011.json'))
    local daily={};for _,day in ipairs(weather.days) do daily[day.date]=day end
    local ready=false;local last_weather
    local function snapshot()
        local now=api.game:snapshot();local native=now.lift_rides or {};now.lift_rides={}
        for id,key in pairs(Data.asset_ids) do now.lift_rides[key]=native[id] or 0 end
        return now
    end
    local function pay(...) return api.game:charge(...) end
    api:scenario({title='Super Saint-Bernard — The Reprieve',tracker_title='Goals',deadline='Save the 2010–2011 season',
        goal='Keep two approved lifts running through 2010 and finish the winter with positive cash.',
        briefing='Late 2003. You take over Super Saint-Bernard for one symbolic franc, with 250,000 CHF and two lifts built in 1962.\n\nBalance maintenance against cash. Before the end of 2010, fund the safety upgrades: 1 million CHF and several months of closure. Survive the 2010–2011 winter with two approved lifts and positive cash. Historical weather and high winds can disrupt your plans.\n\nAll amounts represent Swiss francs; the game retains its $ symbol.',
        status=function() return state.status end,
        objectives={
            {label='Maintain the installations',progress=function()
                local c=math.min(state.assets.menouve.condition,state.assets.plan_du_jeu.condition)
                return {value=string.format('Minimum condition: %.0f%% / 45%%',c),fraction=c/45}
            end},
            {label='Obtain approval for 2011',progress=function()
                local n=0;for _,key in ipairs({'menouve','plan_du_jeu'}) do local asset=state.assets[key];if not asset.legacy or asset.authorized_until then n=n+1 end end
                return {value=n..' / 2 approved lifts',fraction=n/2}
            end},
            {label='Fund the rescue',progress=function()
                return {value='$'..state.investment..' / $1,000,000 committed',fraction=state.investment/1000000}
            end},
            {label='Save the 2010–2011 season',progress=function()
                return {value=state.status=='completed' and 'Season saved' or state.notice,fraction=state.status=='completed' and 1 or 0}
            end},
        }})
    api:building_properties(function(actor)
        local key=Data.asset_ids[actor.id]
        local asset=key and state.assets[key] or state.assets[actor.id]
        return asset and Model.condition_rows(asset,snapshot()) or {}
    end)
    local actions={}
    for _,key in ipairs({'menouve','plan_du_jeu'}) do
        for _,kind in ipairs({'refit','renew'}) do
            local project=Model.projects[key][kind]
            actions[#actions+1]={label=(kind=='refit' and 'Safety upgrade: ' or 'Replace: ')..Data.names[key]..' — $'..project.cost..' ('..project.months..' months)',
                enabled=function() local a=state.assets[key];return state.status=='active' and not a.project and (kind=='renew' or a.legacy and not a.authorized_until) end,
                run=function() if ready then Model.order(state,key,kind,snapshot(),pay) end end}
        end
    end
    actions[#actions+1]={label='Claim the rescue contribution — $500,000',
        enabled=function() return ready and state.status=='active' and snapshot().year>=2009 and state.grant==0 and state.investment>=400000 end,
        run=function() Model.grant(state,snapshot(),function(amount) api.game:record_revenue(amount);state.revenue_seen=snapshot().revenue end) end}
    api:resort_panel({title='Super Saint-Bernard maintenance and renewal',
        properties=function()
            return {{label='Annual maintenance budget',value='$'..Model.efforts[state.effort].annual_cost},
                {label='Maintenance paid',value='$'..state.maintenance_paid},
                {label='Works committed',value='$'..state.investment},
                {label='Status',value=state.notice}}
        end,
        controls={{id='maintenance',label='Maintenance effort',options={'Minimum · $24,000/year','Preventive · $60,000/year','Intensive · $120,000/year'},
            get=function() return state.effort end,set=function(index) state.effort=index end}},actions=actions})
    api:on('map.ready',function(event)
        -- Triggers/triggers.json configures the session before this handler.
        api.game:place_resort(Data.objects,Data.trails)
        api:place_objects(Furnishings(Data))
        ready=true
        local function tick()
            local now=snapshot()
            api.game:set_hub_names(Data.hub_names)
            Model.advance(state,now,pay)
            local date=string.format('%04d-%02d-%02d',now.year,now.month,math.min(now.day,Data.month_days(now.year,now.month)))
            if date~=last_weather then
                local measured=daily[date]
                if measured then
                    api.game:set_weather(measured.weather,measured.temperature+3.2) -- GSB 2472m -> base 1932m, 0.6 C/100m
                    state.wind_closed=measured.wind_max_ms~=Json.null and measured.wind_max_ms>=20
                    last_weather=date
                end
            end
            for _,actor in ipairs(api.game:placeables()) do
                -- Native decorative buildings do not need an installation
                -- condition, maintenance budget or concession in this scenario.
                if not actor.class:find('/Blueprints/Decorations/',1,true) then
                    local key=Data.asset_ids[actor.id] or actor.id
                    if not state.assets[key] then
                        state.assets[key]={condition=100,built=now.year,legacy=false,operating=actor.lift and 120000 or 18000}
                    end
                    local asset=state.assets[key]
                    local wind=state.wind_closed and actor.lift
                    api.game:set_installation(actor.id,{operating_cost=math.floor(asset.operating/((actor.lift and 5 or 12)*now.days_per_month)),disabled=Model.blocked(asset,now,wind),no_refund=Data.asset_ids[actor.id]~=nil})
                end
            end
            -- One rendered visitor represents twelve day visitors. Extra
            -- revenue is recorded in the native accounts, with no recursive scaling.
            if state.revenue_fiscal_year~=now.fiscal_year then state.revenue_fiscal_year=now.fiscal_year;state.revenue_seen=0 end
            local delta=now.revenue-(state.revenue_seen or now.revenue)
            if delta>0 then
                local extra=math.floor(delta*11)
                api.game:record_revenue(extra);state.revenue_seen=now.revenue+extra
            else state.revenue_seen=now.revenue end
        end
        tick();api:every(1000,tick)
    end)
end
return initialize
