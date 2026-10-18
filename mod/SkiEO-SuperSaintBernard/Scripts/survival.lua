-- Pure calendar-based model; no engine objects or wall-clock timers in saved state.
local Model={}
Model.efforts={
    {name='Minimum',annual_cost=24000,wear=1.10},
    {name='Preventive',annual_cost=60000,wear=0.46},
    {name='Intensive',annual_cost=120000,wear=0.20},
}
Model.projects={
    menouve={refit={cost=800000,months=3,condition=80,until_year=2013},renew={cost=10000000,months=8,condition=100}},
    plan_du_jeu={refit={cost=200000,months=2,condition=85,until_year=2013},renew={cost=2000000,months=5,condition=100}},
}
function Model.new()
    return {version=1,effort=2,status='active',assets={
        menouve={condition=67,built=1962,legacy=true,operating=180000},
        plan_du_jeu={condition=72,built=1962,legacy=true,operating=90000}},
        grant=0,investment=0,maintenance_paid=0,notice='Prepare the upgrades before the June 2010 inspection.'}
end
local legacy_notices={
    ["Préparez les travaux avant le contrôle de juin 2010."]="Prepare the upgrades before the June 2010 inspection.",
    ["Trésorerie insuffisante pour commander les travaux."]="Insufficient cash to order the works.",
    ["Travaux commandés. La remontée reste arrêtée jusqu’à la réception et au contrôle."]="Works ordered. The lift stays closed until completion and inspection.",
    ["500 000 F encaissés : contribution de sauvetage conditionnée aux travaux engagés."]="$500,000 rescue contribution received against the committed works.",
    ["Travaux réceptionnés et contrôle validé. L’entretien reste nécessaire."]="Works completed and approved. Maintenance is still required.",
    ["Contrôle OFT : aucune installation de 1962 sans travaux agréés ne pourra fonctionner en 2011."]="Transport authority inspection: unapproved 1962 lifts cannot operate in 2011.",
    ["La station ne peut plus financer son exploitation."]="The resort can no longer fund its operations.",
    ["La saison 2010–2011 est sauvée. La station dispose de remontées conformes et d’une trésorerie positive."]="The 2010–2011 season is saved: approved lifts and positive cash.",
    ["La station n’a pas assuré la saison 2010–2011 avec deux remontées conformes."]="The resort failed to operate the 2010–2011 season with two approved lifts.",
}
function Model.restore(state)
    state.notice=legacy_notices[state.notice] or state.notice
    return state
end
function Model.order(state,key,kind,now,pay)
    local asset=state.assets[key];local project=Model.projects[key] and Model.projects[key][kind]
    if state.status~='active' or not asset or not project or asset.project then return false end
    if kind=='refit' and (not asset.legacy or asset.authorized_until) then return false end
    if not pay(project.cost,0,false) then state.notice='Insufficient cash to order the works.';return false end
    asset.project={kind=kind,due=now.months+project.months,cost=project.cost}
    state.investment=state.investment+project.cost
    state.notice='Works ordered. The lift stays closed until completion and inspection.'
    return true
end
function Model.grant(state,now,credit)
    if state.status~='active' or state.grant>0 or now.year<2009 or state.investment<400000 then return false end
    -- Counterfactual matching contribution, inspired by the 500,000 CHF in
    -- historical pledges. It is not cash available at the 2003 takeover.
    credit(500000);state.grant=500000
    state.notice='$500,000 rescue contribution received against the committed works.'
    return true
end
function Model.blocked(asset,now,wind)
    return asset.project~=nil or asset.condition<30 or wind
        or asset.legacy and now.year>=2011 and (not asset.authorized_until or now.year>asset.authorized_until)
end
function Model.advance(state,now,pay)
    local previous_rides=state.last_rides or {}
    local previous_months=state.last_months
    local winter=now.year==2010 and now.month>=11 or now.year==2011 and now.month<=4
    local approved=true
    for _,key in ipairs({'menouve','plan_du_jeu'}) do
        local asset=state.assets[key]
        if asset.project or asset.condition<45 or asset.legacy and not asset.authorized_until then approved=false end
    end
    if winter and approved and state.rides_in_winter then
        state.winter_rides=state.winter_rides or {}
        for _,key in ipairs({'menouve','plan_du_jeu'}) do
            local total=(now.lift_rides or {})[key] or 0
            state.winter_rides[key]=(state.winter_rides[key] or 0)+math.max(0,total-(previous_rides[key] or total))
        end
    end
    state.rides_in_winter=winter and approved
    state.last_rides=now.lift_rides or {}
    if not state.last_months then state.last_months=now.months;state.start_fiscal_year=now.fiscal_year;return end
    local delta=now.months-state.last_months
    assert(delta>=-0.0001,'scenario calendar moved backwards without restoring its save')
    if delta<=0 then return end
    state.last_months=now.months
    if state.status~='active' then return end
    local effort=Model.efforts[state.effort]
    state.maintenance_fraction=(state.maintenance_fraction or 0)+delta*effort.annual_cost/12
    local cost=math.floor(state.maintenance_fraction)
    if cost>0 then pay(cost,1,true);state.maintenance_fraction=state.maintenance_fraction-cost;state.maintenance_paid=state.maintenance_paid+cost end
    local latest_completion=previous_months
    for key,asset in pairs(state.assets) do
        local due=asset.project and asset.project.due
        local wear=delta*effort.wear*(asset.legacy and 1 or 0.3)
        asset.condition=math.max(0,asset.condition-wear)
        if due and now.months>=due then
            local project=Model.projects[key][asset.project.kind]
            asset.condition=math.max(0,project.condition-math.max(0,now.months-due)*effort.wear*(asset.project.kind=='renew' and 0.3 or 1))
            asset.authorized_until=project.until_year
            latest_completion=math.max(latest_completion,due)
            if asset.project.kind=='renew' then asset.legacy=false;asset.built=now.year end
            asset.project=nil
            state.notice='Works completed and approved. Maintenance is still required.'
        end
    end
    if now.year==2010 and now.month>=6 and not state.inspection then
        state.inspection=true;state.notice='Transport authority inspection: unapproved 1962 lifts cannot operate in 2011.'
    end
    -- The snapshot predates this tick's mandatory maintenance debit.
    local cash=now.balance-cost
    if cash<0 then
        state.insolvent_months=(state.insolvent_months or 0)+delta
    else state.insolvent_months=0 end
    if state.insolvent_months>=3 then state.status='failed';state.notice='The resort can no longer fund its operations.' end
    if now.year>=2011 and state.status=='active' then
        local safe=true
        for _,key in ipairs({'menouve','plan_du_jeu'}) do
            local asset=state.assets[key]
            if Model.blocked(asset,now,false) or asset.condition<45 then safe=false end
        end
        local winter_start=(state.start_fiscal_year+7)*12+6
        if safe then
            state.compliant_winter_months=(state.compliant_winter_months or 0)+math.max(0,now.months-math.max(previous_months,winter_start,latest_completion))
        end
        local served=state.winter_rides and (state.winter_rides.menouve or 0)>0 and (state.winter_rides.plan_du_jeu or 0)>0
        if safe and served and cash>=0 and now.month>=4 and (state.compliant_winter_months or 0)>=3 then
            state.status='completed';state.notice='The 2010–2011 season is saved: approved lifts and positive cash.'
        elseif now.year>2011 or now.month>=4 then
            state.status='failed';state.notice='The resort failed to operate the 2010–2011 season with two approved lifts.'
        end
    end
end
function Model.condition_rows(asset,now)
    local status=asset.project and 'Works in progress' or Model.blocked(asset,now,false) and 'Mandatory closure'
        or asset.authorized_until and ('Approved until '..asset.authorized_until) or asset.legacy and 'Approval expires: end of 2010' or 'Renewed installation'
    return {{label='Installation condition',value=string.format('%.0f %%',asset.condition),fraction=asset.condition/100},
        {label='Commissioned',value=asset.built},{label='Approval',value=status}}
end
return Model
