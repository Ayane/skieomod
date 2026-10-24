local models={chair_head='Assets/chair-head.skpm',chair_tower='Assets/chair-tower.skpm',motor='Assets/motor.skpm',guide_wheel='Assets/guide-wheel.skpm',return_support='Assets/return-support.skpm',return_angle='Assets/return-angle.skpm',fixed_return_support='Assets/fixed-return-support.skpm',inclined_wheel='Assets/inclined-wheel.skpm',poles_bundle='Assets/poles-bundle.skpm',palette='Assets/palette.png',platter='Assets/platter.skpm',tower='Assets/tower.skpm',
    platter_upper='Assets/platter-upper.skpm',platter_shaft='Assets/platter-shaft.skpm',platter_lower='Assets/platter-lower.skpm',
    angle_tower='Assets/angle-tower.skpm',drive='Assets/poma-drive.skpm',covered='Assets/pre-leve-drive.skpm',
    return_station='Assets/floating-return.skpm',release='Assets/release-return.skpm',fixed='Assets/fixed-drive.skpm',modern='Assets/pras-drive.skpm',
    lattice='Assets/lattice-return.skpm',chair_drive='Assets/blanchon-drive.skpm',chair_return='Assets/blanchon-return.skpm'}
return function(api)
    local options=api:mapmod_options()
    local started=false
    api:on('map.ready',function()
        if started then return end;started=true
        -- The map can build its resort asynchronously. Attach only after all
        -- of its loading holds have completed, including native save restore.
        api:every(500,function()
            if not api:environment().ready then return true end
            local definitions={}
            for _,d in ipairs(options.lifts or {}) do definitions[#definitions+1]=d end
            for _,d in ipairs(options.chairlifts or {}) do definitions[#definitions+1]=d end
            local lifts=api:configure_surface_lifts(definitions,models)
            api:log('Remontées prêtes : '..#lifts:snapshot())
            return false
        end)
    end)
end
