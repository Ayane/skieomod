local UEHelpers = require("UEHelpers")
local VeymontData = require("veymont_data")
local VeymontStaff = require("veymont_staff")
local Furnishings = require("furnishings")
local Climate = require("climate")
local Snowmaking = require("snowmaking")
local SNOWMAKING_DEFINITIONS = Snowmaking.definitions(VeymontData)
local NativeTerrain = require("native_terrain")
local Vegetation = require("vegetation")

local MOD_NAME = "SkiEO-Veymont"
local LIFT_PACKAGE = "/Game/Blueprints/Lifts/BP_FixedChair1"
local LIFT_ASSET = LIFT_PACKAGE .. ".BP_FixedChair1"
local LIFT_CLASS = LIFT_PACKAGE .. ".BP_FixedChair1_C"
local TICKET_PACKAGE = "/Game/Blueprints/Buildings/BP_TicketOffice"
local TICKET_ASSET = TICKET_PACKAGE .. ".BP_TicketOffice"
local TICKET_CLASS = TICKET_PACKAGE .. ".BP_TicketOffice_C"
local SNOWCAT_SHED_PACKAGE = "/Game/Blueprints/Buildings/BP_SnowcatShed"
local SNOWCAT_SHED_ASSET = SNOWCAT_SHED_PACKAGE .. ".BP_SnowcatShed"
local SNOWCAT_SHED_CLASS = SNOWCAT_SHED_PACKAGE .. ".BP_SnowcatShed_C"
local AMENITY_ASSETS = {
    ski_patrol_hut = {
        asset = "/Game/Blueprints/Buildings/BP_SkiPatrolHut.BP_SkiPatrolHut",
        class = "/Game/Blueprints/Buildings/BP_SkiPatrolHut.BP_SkiPatrolHut_C",
        token = "BP_SkiPatrolHut"
    },
    hot_cocoa_cart = {
        asset = "/Game/Blueprints/Buildings/BP_HotCocoaCart.BP_HotCocoaCart",
        class = "/Game/Blueprints/Buildings/BP_HotCocoaCart.BP_HotCocoaCart_C",
        token = "BP_HotCocoaCart"
    },
    waffle_stand = {
        asset = "/Game/Blueprints/Buildings/BP_WaffleStand.BP_WaffleStand",
        class = "/Game/Blueprints/Buildings/BP_WaffleStand.BP_WaffleStand_C",
        token = "BP_WaffleStand"
    },
    warming_hut = {
        asset = "/Game/Blueprints/Buildings/BP_WarmingHut.BP_WarmingHut",
        class = "/Game/Blueprints/Buildings/BP_WarmingHut.BP_WarmingHut_C",
        token = "BP_WarmingHut"
    }
}
local GUID_LIBRARY = "/Script/Engine.Default__KismetGuidLibrary"
local SKI_FUNCTION_LIBRARY =
    "/Script/SkiResortSimulator.Default__SkiResortFunctionLibrary"
local FRONT_BRIDGE_PREFIX = "Front hub technical link"
local install_station_lift_overrides

-- Veymont is intentionally ordinary portable-map content. The code below is
-- only the station reconstruction layer that the generic loader invokes after
-- terrain readiness. Every placeable is spawned through the same preview ->
-- initialize -> finalize lifecycle as the Build tool, then explicitly entered
-- into the world registries because those subsystems were initialized before
-- this late source-map build. This ordering is why lifts, rectangular terminal
-- hubs, trail endpoints and guests now agree instead of being independent
-- visual approximations.

-- Native hub geometry is rebuilt from lift terminals, but the visualization
-- subsystem assigns an English random name when it first spawns each actor.
-- Anchor those transient labels to the authentic local place names. Several
-- lift terminals may intentionally merge into one rectangular hub.
local HUB_NAME_ANCHORS = {
    { name = "Les Alleyrons", X = 44750.520, Y = -9813.690 },
    { name = "Crête du Brisou", X = 853.010, Y = 101304.630 },
    { name = "Les Bessards", X = -17558.815, Y = -83637.235 },
    { name = "Le Blanchon", X = -61747.000, Y = -64493.340 },
    { name = "Le Blavet", X = 33641.070, Y = -24792.340 },
    { name = "Pierre Blanche", X = -57017.770, Y = -81045.400 },
    { name = "Sommet de Pierre Blanche", X = -144405.940, Y = -55181.950 },
    { name = "Les Pras", X = -80655.575, Y = -107044.530 },
    { name = "Pré Levé", X = -56834.650, Y = -97967.970 },
    { name = "Sous le Pas de la Ville", X = -148786.450, Y = -107737.290 },
    { name = "Champ de l'Herse", X = 9326.215, Y = -75288.278 },
}

local function log(message)
    print(string.format("[%s] %s\n", MOD_NAME, message))
end

local function log_hub_lifecycle(label)
    local ok, message = NativeTerrain.probe_hubs()
    log(string.format("hub lifecycle %s: %s %s",
        label, tostring(ok), tostring(message)))
end

local function belongs_to_current_world(object)
    if not object or not object:IsValid() then
        return false
    end

    local current_world = UEHelpers.GetWorld()
    if not current_world or not current_world:IsValid() then
        return false
    end

    local ok, object_world = pcall(function()
        return object:GetWorld()
    end)
    return ok and object_world and object_world:IsValid()
        and object_world:GetAddress() == current_world:GetAddress()
end

-- FindFirstOf can return a still-live subsystem from a previously unloaded
-- map. Every gameplay object must instead belong to the world
-- currently owned by the player controller.
local function find_in_current_world(class_name)
    for _, object in ipairs(FindAllOf(class_name) or {}) do
        if belongs_to_current_world(object) then
            return object
        end
    end
    return nil
end

local function rename_hub_labels()
    local renamed = 0
    for _, hub in ipairs(FindAllOf("HubActor") or {}) do
        if belongs_to_current_world(hub) then
            local ok = pcall(function()
                local location = hub:K2_GetActorLocation()
                local nearest, nearest_distance = nil, math.huge
                for _, anchor in ipairs(HUB_NAME_ANCHORS) do
                    local dx, dy = location.X - anchor.X, location.Y - anchor.Y
                    local distance = dx * dx + dy * dy
                    if distance < nearest_distance then
                        nearest, nearest_distance = anchor, distance
                    end
                end
                if nearest and hub.NameLabel and hub.NameLabel:IsValid() then
                    hub.NameLabel:K2_SetText(FText(nearest.name))
                    renamed = renamed + 1
                end
            end)
            if not ok then return renamed end
        end
    end
    return renamed
end

-- Clearing the template station briefly emits the stock skiability event.
-- Its call-to-action can remain queued behind our loading screen even though
-- the completed source station already has a valid native hub graph. Dismiss
-- only that stale message; every other call-to-action remains untouched.
local function dismiss_transient_ski_run_warning()
    local operations = find_in_current_world('ResortOperationsSubsystem')
    if not operations or not operations:IsValid()
        or not operations:IsSkiingAvailable() or not operations:AreArrivalsAllowed() then
        return 0
    end
    local dismissed = 0
    for _, widget in ipairs(FindAllOf("CallToActionWidget") or {}) do
        if widget and widget:IsValid() then
            local ok, headline = pcall(function()
                if not widget:IsInViewport()
                    or not widget.HeadlineText
                    or not widget.HeadlineText:IsValid() then
                    return nil
                end
                return widget.HeadlineText:GetText():ToString()
            end)
            if ok and (headline == "No Complete Ski Run"
                or headline == "No Way Back to the Ticket Office"
                or headline == "Nothing reaches the Ticket Office") then
                local closed = pcall(function()
                    widget:OnContinueClicked()
                    if widget:IsInViewport() then widget:RemoveFromParent() end
                end)
                if closed then dismissed = dismissed + 1 end
            end
        end
    end
    if dismissed > 0 then
        log(string.format(
            "%d stale incomplete-network warning(s) dismissed",
            dismissed))
    end
    return dismissed
end

local function position_is_near(first, second, tolerance)
    local dx = first.X - second.X
    local dy = first.Y - second.Y
    local dz = first.Z - second.Z
    return dx * dx + dy * dy + dz * dz <= tolerance * tolerance
end

local function station_definition_for_lift(lift)
    if not lift or not lift:IsValid() or not belongs_to_current_world(lift) then
        return nil
    end
    local destroying_ok, destroying = pcall(function()
        return lift:IsActorBeingDestroyed()
    end)
    if destroying_ok and destroying then
        return nil
    end
    local ok, bottom, top = pcall(function()
        return lift:GetBottomTerminalLocation(), lift:GetTopTerminalLocation()
    end)
    if not ok then
        return nil
    end
    for _, definition in ipairs(VeymontData.lifts) do
        if position_is_near(bottom, definition.bottom, 500.0)
            and position_is_near(top, definition.top, 500.0) then
            return definition
        end
    end
    return nil
end

local function log_current_lifts(label)
    local count = 0
    for _, lift in ipairs(FindAllOf("LiftActor") or {}) do
        if station_definition_for_lift(lift) then
            count = count + 1
            local ok, message = pcall(function()
                local bottom = lift:GetBottomTerminalLocation()
                local top = lift:GetTopTerminalLocation()
                log(string.format(
                    "%s lift %d: 0x%X, bottom %.0f %.0f %.0f, top %.0f %.0f %.0f, %s",
                    label, count, lift:GetAddress(),
                    bottom.X, bottom.Y, bottom.Z, top.X, top.Y, top.Z,
                    lift:GetFullName()))
            end)
            if not ok then
                log(label .. " lift could not be inspected: " .. tostring(message))
            end
        end
    end
    log(string.format("%s: %d lift actor(s) in the current world", label, count))
end

local function remove_prototype_trails(trail_map, keep)
    local trail_ids = {}
    trail_map.RegisteredTrails:ForEach(function(key)
        local trail_id = key:get()
        local nested_ok, nested = pcall(function() return trail_id:get() end)
        if nested_ok then trail_id = nested end
        trail_id = tonumber(trail_id)
        if trail_id then trail_ids[#trail_ids + 1] = trail_id end
    end)
    local removed = 0
    for _, trail_id in ipairs(trail_ids) do
        if not keep or not keep[trail_id] then
            local ok, did_remove = pcall(function()
                return trail_map:UnregisterTrail(trail_id)
            end)
            if ok and did_remove then
                removed = removed + 1
            end
        end
    end
    log(string.format(
        "%d/%d old template trail(s) removed",
        removed, #trail_ids))
    return removed
end

local function snap_station_trail_endpoints(definition)
    local first = definition.curves[1]
    local last = definition.curves[#definition.curves]
    if not first or not last then
        return
    end

    local nearest_top = nil
    local nearest_top_distance = math.huge
    local nearest_bottom = nil
    local nearest_bottom_distance = math.huge
    for _, lift in ipairs(VeymontData.lifts) do
        local top_dx = first.start.X - lift.top.X
        local top_dy = first.start.Y - lift.top.Y
        local top_distance = top_dx * top_dx + top_dy * top_dy
        if top_distance < nearest_top_distance then
            nearest_top_distance = top_distance
            nearest_top = lift.top
        end

        local bottom_dx = last.finish.X - lift.bottom.X
        local bottom_dy = last.finish.Y - lift.bottom.Y
        local bottom_distance = bottom_dx * bottom_dx + bottom_dy * bottom_dy
        if bottom_distance < nearest_bottom_distance then
            nearest_bottom_distance = bottom_distance
            nearest_bottom = lift.bottom
        end
    end

    -- Hub coverage is deliberately conservative. Exact OSM endpoints are
    -- snapped to the terminal centre only when they are already within 100 m;
    -- trails intended to join another trail remain geometrically untouched.
    local maximum_snap_distance_squared = 10000.0 * 10000.0
    if nearest_top and nearest_top_distance <= maximum_snap_distance_squared then
        first.start = {
            X = nearest_top.X, Y = nearest_top.Y, Z = nearest_top.Z
        }
    end
    if nearest_bottom and nearest_bottom_distance <= maximum_snap_distance_squared then
        last.finish = {
            X = nearest_bottom.X, Y = nearest_bottom.Y, Z = nearest_bottom.Z
        }
    end
end

local function curve_for_game(curve, width)
    return {
        StartPoint = curve.start,
        ControlPoint = curve.control,
        Endpoint = curve.finish,
        CorridorWidth = width
    }
end

local function quadratic_point(curve, t)
    local inverse = 1.0 - t
    return {
        X = inverse * inverse * curve.start.X
            + 2.0 * inverse * t * curve.control.X
            + t * t * curve.finish.X,
        Y = inverse * inverse * curve.start.Y
            + 2.0 * inverse * t * curve.control.Y
            + t * t * curve.finish.Y,
        Z = inverse * inverse * curve.start.Z
            + 2.0 * inverse * t * curve.control.Z
            + t * t * curve.finish.Z,
    }
end

-- The template level's BakedObstacleData remains useful as the engine-side
-- obstacle index, but its positions belong to the template map. Clear every
-- source corridor before the trail graph is notified: visual trees are rebuilt
-- separately from forest.skxy, whose source mask already contains the same
-- piste, lift and base-area clearings.
local function clear_source_corridors()
    local obstacles = find_in_current_world("ObstacleDataManager")
    if not obstacles or not obstacles:IsValid() then
        log("obstacle data manager is unavailable")
        return 0, 0
    end

    local cleared, operations = 0, 0
    local function clear_line(first, last, half_width)
        local ok, result = pcall(function()
            return obstacles:ClearObstaclesAlongLine(
                first, last, half_width, false)
        end)
        operations = operations + 1
        if ok then cleared = cleared + (tonumber(result) or 0) end
    end

    for _, definition in ipairs(VeymontData.trails) do
        local half_width = definition.width * 0.5 + 250.0
        for _, curve in ipairs(definition.curves) do
            local previous = curve.start
            for sample = 1, 4 do
                local point = quadratic_point(curve, sample / 4.0)
                clear_line(previous, point, half_width)
                previous = point
            end
        end
    end
    for _, lift in ipairs(VeymontData.lifts) do
        local route = lift.route or {lift.bottom, lift.top}
        for i = 1, #route - 1 do clear_line(route[i], route[i + 1], 1500.0) end
        for _, endpoint in ipairs({ lift.bottom, lift.top }) do
            local ok, result = pcall(function()
                return obstacles:ClearObstaclesInRadius(
                    endpoint, 3500.0, false)
            end)
            operations = operations + 1
            if ok then cleared = cleared + (tonumber(result) or 0) end
        end
    end

    log(string.format(
        "source corridors cleared: %d operation(s), %d obstacle(s)",
        operations, cleared))
    return operations, cleared
end

local function refresh_hub_visualization()
    local visualization = find_in_current_world("HubVisualizationSubsystem")
    if visualization and visualization:IsValid() then
        pcall(function() visualization:HandleHubsRebuilt() end)
    end
    local controller = find_in_current_world("SkiResortPlayerController")
    if controller and controller:IsValid() then
        pcall(function() controller:RefreshHubRadiiVisibility() end)
    end
end

local function log_hub_registration(lifts, guid_library)
    local registry = find_in_current_world("PlaceableRegistrySubsystem")
    if registry and registry:IsValid() then
        local ok, message = pcall(function()
            log(string.format(
                "native registry: %d lift(s), %d building(s)",
                registry.Lifts:GetArrayNum(), registry.Buildings:GetArrayNum()))
        end)
        if not ok then
            log("native registry could not be inspected: " .. tostring(message))
        end
    end

    for index, lift in ipairs(lifts) do
        local ok, message = pcall(function()
            log(string.format(
                "lift hub %d: preview=%s, bottom radius=%.0f, top radius=%.0f, bottom id=%s, top id=%s",
                index, tostring(lift.bIsPreview), lift.BuildingRadius,
                lift.TopBuildingRadius,
                tostring(guid_library:IsValid_Guid(lift.HubId)),
                tostring(guid_library:IsValid_Guid(lift.TopHubId))))
        end)
        if not ok then
            log("lift hub diagnostics failed: " .. tostring(message))
        end
    end

    ExecuteWithDelay(1000, function()
        ExecuteInGameThread(function()
            local count = 0
            for _, hub_actor in ipairs(FindAllOf("HubActor") or {}) do
                local destroying_ok, destroying = pcall(function()
                    return hub_actor:IsActorBeingDestroyed()
                end)
                if belongs_to_current_world(hub_actor)
                    and (not destroying_ok or not destroying) then
                    count = count + 1
                end
            end
            log(string.format("native graph: %d hub(s)", count))
        end)
    end)
end

local function collect_preloaded_station()
    local registry = find_in_current_world("PlaceableRegistrySubsystem")
    if not registry or not registry:IsValid() then
        return nil
    end

    local registry_ok, lift_count, building_count = pcall(function()
        return registry.Lifts:GetArrayNum(), registry.Buildings:GetArrayNum()
    end)
    if not registry_ok then
        return nil
    end
    log(string.format(
        "inspecting loaded resort: registry=%d lift(s), %d building(s)",
        lift_count, building_count))

    local lifts = {}
    for _, lift in ipairs(FindAllOf("LiftActor") or {}) do
        if station_definition_for_lift(lift) then
            table.insert(lifts, lift)
        end
    end
    if #lifts ~= #VeymontData.lifts then
        return nil
    end

    local buildings = {}
    local bridge_buildings = {}
    local generated_bridge_count = 0
    local ticket_office = nil
    for _, building in ipairs(FindAllOf("BuildingActor") or {}) do
        if belongs_to_current_world(building) then
            local destroying_ok, destroying = pcall(function()
                return building:IsActorBeingDestroyed()
            end)
            if not destroying_ok or not destroying then
                local full_name = building:GetFullName()
                local instance_name = "?"
                pcall(function()
                    instance_name = building:GetInstanceName():ToString()
                end)
                log(string.format(
                    "loaded building: %s, radius=%.0f m (%s)",
                    instance_name, building.BuildingRadius / 100.0, full_name))
                local managed = string.find(
                    full_name, "BP_TicketOffice", 1, true)
                    or string.find(full_name, "BP_SnowcatShed", 1, true)
                if string.find(full_name, "BP_TicketOffice", 1, true) then
                    building:SetInstanceName(FText("Gresse Ticket Office"))
                elseif string.find(full_name, "BP_SnowcatShed", 1, true) then
                    building:SetInstanceName(FText("Gresse Snowcat Garage"))
                end
                local is_generated_bridge = string.find(
                    instance_name, FRONT_BRIDGE_PREFIX, 1, true) == 1
                local is_bridge = is_generated_bridge
                    or instance_name == "Liaison du front de neige"
                for kind, asset in pairs(AMENITY_ASSETS) do
                    if string.find(full_name, asset.token, 1, true) then
                        if is_bridge then
                            table.insert(bridge_buildings, building)
                            if is_generated_bridge then
                                generated_bridge_count = generated_bridge_count + 1
                            end
                        else
                            managed = true
                        end
                        if not is_bridge then
                            for _, definition in ipairs(VeymontData.amenities) do
                                if definition.kind == kind then
                                    building:SetInstanceName(FText(definition.name))
                                    break
                                end
                            end
                        end
                    end
                end
                if managed then
                    table.insert(buildings, building)
                    if string.find(full_name, "BP_TicketOffice", 1, true) then
                        ticket_office = building
                    end
                end
            end
        end
    end
    if #lifts ~= #VeymontData.lifts or #buildings ~= 5 or not ticket_office then
        log(string.format(
            "native resort is incomplete: %d/%d lift(s), %d/5 managed building(s), ticket office=%s",
            #lifts, #VeymontData.lifts, #buildings,
            tostring(ticket_office ~= nil)))
        return nil
    end

    return {
        registry = registry,
        lifts = lifts,
        buildings = buildings,
        bridge_buildings = bridge_buildings,
        generated_bridge_count = generated_bridge_count,
        ticket_office = ticket_office
    }
end

local function get_registered_trail_count()
    local trail_map = find_in_current_world("TrailMapSubsystem")
    if not trail_map or not trail_map:IsValid() then
        return 0
    end
    local ok, count = pcall(function()
        return #trail_map.RegisteredTrails
    end)
    if ok then
        return count
    end
    return 0
end

local function register_station_trails()
    local trail_map = find_in_current_world("TrailMapSubsystem")
    if not trail_map or not trail_map:IsValid() or not trail_map:IsInitialized() then
        log("trail subsystem is unavailable; trail creation was skipped")
        return 0
    end
    remove_prototype_trails(trail_map)
    local hub_connectivity = find_in_current_world("HubConnectivitySubsystem")

    local registered = 0
    local station_trail_ids = {}
    for _, definition in ipairs(VeymontData.trails) do
        snap_station_trail_endpoints(definition)
        local first = definition.curves[1]
        if first then
            local ok, trail_id = pcall(function()
                return trail_map:RegisterTrailFromCurve(
                    curve_for_game(first, definition.width))
            end)
            if ok and trail_id then
                local numeric_id = tonumber(trail_id)
                if numeric_id then station_trail_ids[numeric_id] = true end
                local complete = true
                for index = 2, #definition.curves do
                    local extended_ok, extended = pcall(function()
                        return trail_map:ExtendTrailWithCurve(
                            trail_id,
                            curve_for_game(definition.curves[index], definition.width))
                    end)
                    if not extended_ok or not extended then
                        complete = false
                        log(string.format(
                            "segment %d of %s was rejected", index, definition.name))
                        break
                    end
                end
                pcall(function()
                    trail_map:SetTrailDisplayName(trail_id, FText(definition.name))
                    trail_map:SetTrailDifficulty(trail_id, definition.difficulty)
                    trail_map:SetTrailGroomed(trail_id, true)
                    trail_map:SetTrailNightSkiing(trail_id, false)
                    -- ExtendTrailWithCurve changes the final endpoint after
                    -- RegisterTrailFromCurve has already emitted its event.
                    -- Re-register the completed geometry so both endpoint hubs
                    -- are included in the connectivity graph.
                    trail_map:RegisterOrUpdateTrail(trail_id)
                end)
                if hub_connectivity and hub_connectivity:IsValid() then
                    -- The first curve registers before the rest of the OSM
                    -- geometry exists. Replace that provisional hub member by
                    -- one computed from the completed top-to-bottom trail.
                    pcall(function()
                        hub_connectivity:HandleTrailUnregistered(trail_id)
                        hub_connectivity:HandleTrailRegistered(trail_id)
                    end)
                end
                if complete then
                    registered = registered + 1
                end
            else
                log("could not create " .. definition.name .. ": " .. tostring(trail_id))
            end
        end
    end

    -- Some template trails finish registering during the same frame in which
    -- the station is built. A second pass keeps the 20 source trails and
    -- removes any late template entries instead of accumulating them on each
    -- load.
    remove_prototype_trails(trail_map, station_trail_ids)
    clear_source_corridors()

    local notified, notification_error = pcall(function()
        for trail_id in pairs(station_trail_ids) do
            trail_map:SetTrailGroomed(trail_id, true)
            trail_map:RegisterOrUpdateTrail(trail_id)
        end
        trail_map:DetectIntersections()
        trail_map:NotifyPaintComplete()
    end)
    if notified then
        log("trail graph notified after creation")
    else
        log("trail graph notification failed: " .. tostring(notification_error))
    end

    refresh_hub_visualization()
    local visualization = find_in_current_world("TrailVisualizationSubsystem")
    if visualization and visualization:IsValid() then
        pcall(function() visualization:SetVisualizationEnabled(true) end)
    end

    log(string.format("%d/%d OSM trails registered", registered, #VeymontData.trails))
    return registered
end

local report_lift_status

local function activate_veymont_winter()
    local ok, message = pcall(function()
        local game_mode = find_in_current_world("SkiResortGameMode")
        if game_mode and game_mode:IsValid() then
            game_mode:OpenSeason()
            game_mode.bIsOperatingSeason = true
            log("operating season opened by GameMode: " ..
                tostring(game_mode.bIsOperatingSeason))
        end

        -- The loader initializes December and a fresh native snowpack before
        -- map.ready. Keep that state; notify SnowSimulation only if a script
        -- changed the month. Calendar notification would open a month report.
        local time = find_in_current_world("TimeSubsystem")
            or FindFirstOf("TimeSubsystem")
        local month_changed = false
        if time and time:IsValid() then
            local previous_month = tonumber(time:GetCurrentMonth())
            local game_time = time.GameTime
            game_time.Month = 5
            game_time.MonthPhase = 0.50
            time.GameTime = game_time
            month_changed = previous_month ~= 5
            log(string.format(
                "time restored: month=%s, hour=%.1f",
                tostring(time:GetCurrentMonth()), time:GetTimeOfDayHours()))
        end

        local snow = find_in_current_world("SnowSimulationSubsystem")
            or FindFirstOf("SnowSimulationSubsystem")
        if snow and snow:IsValid() then
            -- Preserve the source world's initialized snow layer.
            if month_changed then snow:HandleMonthChanged(5) end
            log(string.format(
                "source snow initialized: grid=%d", snow:GetGridResolution()))
        end


    end)
    log("Veymont winter activation: " ..
        tostring(ok) .. " " .. tostring(message))

end

report_lift_status = function(lift)
    ExecuteWithDelay(5000, function()
        ExecuteInGameThread(function()
            if not lift or not lift:IsValid() then
                return
            end
            local definition = station_definition_for_lift(lift)
            local ok, message = pcall(function()
                local status = lift:GetStatusText()
                log(string.format(
                    "%s: cable %.0f m, running=%s, skiing=%s, status=%s",
                    definition and definition.name or "Veymont lift",
                    lift:GetCableLength() / 100.0,
                    tostring(lift:IsLiftRunning()),
                    tostring(lift:IsLiftAvailableForSkiing()),
                    status and status:ToString() or "?"))
            end)
            if not ok then
                log("lift status is unavailable: " .. tostring(message))
            end
        end)
    end)
end

local function clear_saved_station_objects()
    local removed = 0
    local seen = {}
    for _, class_name in ipairs({
        "PlaceableActor", "LiftActor", "BuildingActor", "SnowblowerActor"
    }) do
        for _, actor in ipairs(FindAllOf(class_name) or {}) do
            if belongs_to_current_world(actor) then
                local address = actor:GetAddress()
                if not seen[address] then
                    seen[address] = true
                    local ok = pcall(function() actor:K2_DestroyActor() end)
                    if ok then removed = removed + 1 end
                end
            end
        end
    end
    log(string.format(
        "%d template-level placeable(s) removed", removed))
end

local function actor_transform(position, yaw)
    local half_yaw = math.rad(yaw or 0.0) * 0.5
    return {
        Rotation = {
            X = 0.0, Y = 0.0,
            Z = math.sin(half_yaw), W = math.cos(half_yaw)
        },
        Translation = position,
        Scale3D = { X = 1.0, Y = 1.0, Z = 1.0 }
    }
end

-- Native construction first spawns a preview, fills its geometry and only
-- then finalizes it. A normal SpawnActor runs BeginPlay too early: the hub
-- subsystem sees an empty lift before its terminals and radii exist. Deferred
-- spawning lets Veymont follow the same lifecycle as the Build menu.
local function spawn_placeable_preview(
    world, gameplay_statics, actor_class, position, yaw)
    local transform = actor_transform(position, yaw)
    local actor = gameplay_statics:BeginDeferredActorSpawnFromClass(
        world, actor_class, transform, 1, nil, 0)
    if not actor or not actor:IsValid() then
        error("deferred actor spawn was rejected")
    end
    actor.bIsPreview = true
    actor = gameplay_statics:FinishSpawningActor(actor, transform, 0)
    if not actor or not actor:IsValid() then
        error("deferred actor finalization was rejected")
    end
    actor:SetPreviewMode(true, true)
    return actor
end

local function spawn_ticket_office(
    world, gameplay_statics, ticket_class, base_hub_id)
    local office = spawn_placeable_preview(
        world, gameplay_statics, ticket_class,
        VeymontData.ticket_office, VeymontData.ticket_office_yaw)
    office.PlaceableComponent:GenerateNewId()
    office.HubId = base_hub_id
    office:SetInstanceName(FText("Gresse Ticket Office"))
    office:SetOperatingHours(0.0, 24.0)
    office:SetOpen(true)
    office:FinalizePlacement()
    log_hub_lifecycle("after Ticket Office")
    log("Ticket Office created at the real base area")
    return office
end

local function spawn_snowcat_shed(
    world, gameplay_statics, shed_class, base_hub_id)
    local shed = spawn_placeable_preview(
        world, gameplay_statics, shed_class,
        VeymontData.snowcat_shed.position, VeymontData.snowcat_shed.yaw)
    shed.PlaceableComponent:GenerateNewId()
    shed.HubId = base_hub_id
    shed:SetInstanceName(FText("Gresse Snowcat Garage"))
    shed:SetOperatingHours(0.0, 24.0)
    shed:SetOpen(true)
    shed:FinalizePlacement()
    log_hub_lifecycle("after snowcat garage")
    log("snowcat garage created on the OSM building between Bessards and Pras")
    return shed
end

local function spawn_amenity(
    world, gameplay_statics, building_class, base_hub_id, definition)
    local building = spawn_placeable_preview(
        world, gameplay_statics, building_class,
        definition.position, definition.yaw)
    building.PlaceableComponent:GenerateNewId()
    building.HubId = base_hub_id
    building:SetInstanceName(FText(definition.name))
    building:SetOperatingHours(0.0, 24.0)
    building:SetOpen(true)
    building:FinalizePlacement()
    log_hub_lifecycle("after amenity " .. definition.name)
    log(string.format("amenity created: %s (%s)",
        definition.name, definition.kind))
    return building
end

local function ground_height(function_library, world, x, y, fallback_z)
    local ok, height = pcall(function()
        return function_library:GetGroundHeightAtLocation(world, x, y)
    end)
    if ok and height and height > 0.0 then
        return height
    end
    return fallback_z
end

-- A hub is not only a shared GUID. Native connectivity clusters overlapping
-- member footprints, then the visualization subsystem builds its composite
-- actor (ring, label and click box) from that cluster. These closed warming
-- huts bridge the gaps between Gresse's ticket office and lower terminals in
-- exactly the same way as the proven cooked Veymont initial save.
local function create_front_hub_bridges(
    world, gameplay_statics, warming_class, hub_id)
    local function_library = StaticFindObject(SKI_FUNCTION_LIBRARY)
    if not function_library or not function_library:IsValid() then
        log("ground-height library is unavailable; hub bridges were not created")
        return {}
    end

    local segments = {
        { VeymontData.ticket_office, VeymontData.lifts[2].bottom, 2 },
        { VeymontData.lifts[2].bottom, VeymontData.lifts[7].bottom, 1 },
        { VeymontData.lifts[2].bottom, VeymontData.lifts[4].bottom, 2 },
        { VeymontData.ticket_office, VeymontData.lifts[5].bottom, 2 },
    }
    local bridges = {}
    for segment_index, segment in ipairs(segments) do
        local first = segment[1]
        local second = segment[2]
        local dx = second.X - first.X
        local dy = second.Y - first.Y
        local count = segment[3]
        for bridge_index = 1, count do
            local alpha = bridge_index / (count + 1)
            local x = first.X + dx * alpha
            local y = first.Y + dy * alpha
            local fallback_z = first.Z + (second.Z - first.Z) * alpha
            local position = {
                X = x,
                Y = y,
                Z = ground_height(function_library, world, x, y, fallback_z)
            }
            local bridge = spawn_placeable_preview(
                world, gameplay_statics, warming_class, position, 0.0)
            bridge.PlaceableComponent:GenerateNewId()
            bridge.HubId = hub_id
            bridge:SetInstanceName(FText(string.format(
                "%s %d-%02d", FRONT_BRIDGE_PREFIX,
                segment_index, bridge_index)))
            bridge:SetOperatingHours(0.0, 24.0)
            bridge:SetOpen(false)
            bridge:FinalizePlacement()
            log_hub_lifecycle(string.format(
                "after bridge %d-%02d", segment_index, bridge_index))
            table.insert(bridges, bridge)
        end
    end
    return bridges
end

-- Hub membership is normally computed while a native SaveGame is
-- deserialized. Preserve the cooked-map migration path by adding the same
-- bridge actors to the next save; source-only maps call the helper directly
-- and register the bridge actors with the rest of their station.
local function seed_front_hub_bridges(
    preloaded, world, gameplay_statics, warming_class)
    if preloaded.generated_bridge_count > 0 then
        log(string.format(
            "%d native base-hub bridge(s) already loaded",
            preloaded.generated_bridge_count))
        return 0
    end

    local bridges = create_front_hub_bridges(
        world, gameplay_statics, warming_class,
        preloaded.ticket_office.HubId)

    local all_buildings = {}
    for _, building in ipairs(preloaded.buildings) do
        table.insert(all_buildings, building)
    end
    for _, bridge in ipairs(preloaded.bridge_buildings) do
        local instance_name = bridge:GetInstanceName():ToString()
        if instance_name == "Liaison du front de neige" then
            pcall(function() bridge:K2_DestroyActor() end)
            log("old isolated bridge removed from the next save")
        else
            table.insert(all_buildings, bridge)
        end
    end
    for _, bridge in ipairs(bridges) do
        table.insert(all_buildings, bridge)
    end
    preloaded.registry.Buildings = all_buildings
    preloaded.bridge_buildings = bridges
    log(string.format(
        "%d Warming Hut bridge(s) created and registered; they become native after save and reload",
        #bridges))
    return #bridges
end

local function register_station_placeables(lifts, buildings)
    local registry = find_in_current_world("PlaceableRegistrySubsystem")
    if not registry or not registry:IsValid() then
        error("native placeable registry is unavailable")
    end

    -- Actors spawned after WorldSubsystem initialization are not appended to
    -- these arrays by FinalizePlacement. Gameplay (operations, staff, saves and
    -- guest routing) reads these arrays rather than FindAllOf, so populate them
    -- exactly as the native Build menu does.
    registry.Lifts = lifts
    registry.Buildings = buildings
    log(string.format(
        "native registry populated: %d lift(s), %d building(s)",
        registry.Lifts:GetArrayNum(), registry.Buildings:GetArrayNum()))

    for _, subsystem_name in ipairs({
        "GuestSimulationSubsystem", "MilestoneObjectiveSubsystem",
        "RoofSnowSubsystem", "TutorialChecklistSubsystem", "WalkNavSubsystem"
    }) do
        local subsystem = find_in_current_world(subsystem_name)
        if subsystem and subsystem:IsValid() then
            pcall(function() subsystem:HandlePlaceableRegistered() end)
        end
    end
end

local function spawn_station_lift(
    world, gameplay_statics, lift_class, guid_library, base_hub_id, definition)
    if definition.real_type == 'chair_lift' then
        local path = '/Game/Blueprints/Lifts/BP_FixedChair2.BP_FixedChair2_C'
        lift_class = StaticFindObject(path)
        if not lift_class or not lift_class:IsValid() then lift_class = LoadAsset(path) end
        assert(lift_class and lift_class:IsValid(), 'Blanchon two-seat lift class unavailable')
        NativeTerrain.retain_texture(lift_class)
    end
    local lift = spawn_placeable_preview(
        world, gameplay_statics, lift_class, definition.bottom, 0.0)
    lift.PlaceableComponent:GenerateNewId()
    lift:SetInstanceName(FText(definition.name))
    lift:Initialize(definition.bottom, definition.top)
    if definition.route and #definition.route > 2 then
        local waypoints = {}
        for i, point in ipairs(definition.route) do
            waypoints[#waypoints + 1] = {position=point,
                bIsTerminal=i==1 or i==#definition.route, bIsAngleStation=false}
        end
        lift.Waypoints = waypoints
    end
    if definition.real_type == 'chair_lift' then
        -- Blanchon: fixed two-seater, 2 m/s, 900 passengers/hour.
        lift.Capacity = 2
        lift.OperatingSpeed = 200
        lift.DispatchIntervalSeconds = 8
    end
    -- Every lower terminal is a member of Gresse's base hub. The Ticket Office
    -- uses this same HubId, so native connectivity no longer treats it as an
    -- isolated building and the guest spawner can use it as an entrance/exit.
    -- Initialize sets up both terminal footprints, so their hub IDs must be
    -- assigned afterwards and before FinalizePlacement registers the members.
    lift.HubId = base_hub_id
    lift.TopHubId = guid_library:NewGuid()
    lift:GenerateTowers()
    lift:Finalize()
    lift:FinalizePlacement()
    log_hub_lifecycle("after lift " .. definition.name)
    lift:SetOperatingHours(0.0, 24.0)
    lift:SetSpeedSetting(2)
    -- Detailed snow tiles stream independently.  The visual snow remains
    -- authoritative, while this tolerance prevents a transient 0 cm sample
    -- from closing one of the prebuilt real-world axes.
    lift.MinOperatingSnowDepthCm = -1.0
    return lift
end

local function activate_guest_arrivals(ticket_office)
    local guests = find_in_current_world("GuestSimulationSubsystem")
    local operations = find_in_current_world("ResortOperationsSubsystem")
    if not guests or not guests:IsValid() then
        log("guest simulation is unavailable")
        return
    end

    local ok, message = pcall(function()
        -- FinalizePlacement registers the office. Refresh the two guest caches
        -- once more after all lifts and trails exist, then enable the native
        -- spawner. This avoids preserving the empty caches of the prototype
        -- save without manufacturing visitors through SpawnGuests.
        guests:HandlePlaceableRegistered()
        guests:HandleHubsRebuilt()
        guests:SetSimulationEnabled(true)
        local spawner = guests:GetSpawner()
        if spawner and spawner:IsValid() then
            spawner:SetSpawningEnabled(true)
        end

        log(string.format(
            "ticket office: open=%s, operations=%s, skiing block=%s, guests=%d, spawning=%s",
            tostring(ticket_office and ticket_office:IsOperating()),
            tostring(operations and operations:IsSkiingAvailable()),
            tostring(operations and operations:GetSkiingBlockReason()),
            guests:GetGuestCount(),
            tostring(spawner and spawner:IsSpawningEnabled())))
    end)
    if not ok then
        log("guest activation failed: " .. tostring(message))
        return
    end

    ExecuteWithDelay(8000, function()
        ExecuteInGameThread(function()
            if not guests:IsValid() then
                return
            end
            local diagnostics_ok, diagnostics = pcall(function()
                return string.format(
                    "ski network: available=%s, block=%s; arrivals: allowed=%s, block=%s, guests=%d, %s",
                    tostring(operations and operations:IsSkiingAvailable()),
                    tostring(operations and operations:GetSkiingBlockReason()),
                    tostring(operations and operations:AreArrivalsAllowed()),
                    tostring(operations and operations:GetArrivalBlockReason()),
                    guests:GetGuestCount(), guests:GetDebugStats())
            end)
            if diagnostics_ok then
                log(diagnostics)
            else
                log("guest diagnostics failed: " .. tostring(diagnostics))
            end
        end)
    end)
end

local function build_veymont_station(done, source_only)
    done = done or function() end
    ExecuteInGameThread(function()
        -- Load generated classes explicitly in the fresh source world. The _C
        -- path directly when needed, so the fallback also returns a UClass.
        local function load_class(path)
            local class = StaticFindObject(path)
            if not class or not class:IsValid() then class = LoadAsset(path) end
            -- Lua wrappers do not own UClasses. Keep generated classes/CDOs
            -- alive across the deferred station build and its render updates.
            if class and class:IsValid() then NativeTerrain.retain_texture(class) end
            return class
        end
        local lift_ok, lift_loaded_class = pcall(function() return load_class(LIFT_CLASS) end)
        local ticket_ok, ticket_loaded_class = pcall(function() return load_class(TICKET_CLASS) end)
        local shed_ok, shed_loaded_class = pcall(function()
            return load_class(SNOWCAT_SHED_CLASS)
        end)
        local loaded_amenity_classes = {}
        local amenities_ok = true
        for kind, asset in pairs(AMENITY_ASSETS) do
            local ok, class = pcall(function() return load_class(asset.class) end)
            amenities_ok = amenities_ok and ok
            loaded_amenity_classes[kind] = class
        end
        if not lift_ok or not ticket_ok or not shed_ok or not amenities_ok then
            log("resort assets are unavailable: " ..
                tostring(lift_loaded_class) .. " / " .. tostring(ticket_loaded_class) ..
                " / " .. tostring(shed_loaded_class))
            done("resort assets are unavailable")
            return
        end

        ExecuteWithDelay(1500, function()
            ExecuteInGameThread(function()
                local world = UEHelpers.GetWorld()
                local gameplay_statics = UEHelpers.GetGameplayStatics()
                local lift_class = StaticFindObject(LIFT_CLASS)
                local ticket_class = StaticFindObject(TICKET_CLASS)
                local shed_class = StaticFindObject(SNOWCAT_SHED_CLASS)
                local amenity_classes = {}
                if (not lift_class or not lift_class:IsValid())
                    and lift_loaded_class and lift_loaded_class:IsValid() then
                    lift_class = lift_loaded_class
                end
                if (not ticket_class or not ticket_class:IsValid())
                    and ticket_loaded_class and ticket_loaded_class:IsValid() then
                    ticket_class = ticket_loaded_class
                end
                if (not shed_class or not shed_class:IsValid())
                    and shed_loaded_class and shed_loaded_class:IsValid() then
                    shed_class = shed_loaded_class
                end
                local amenity_classes_valid = true
                for kind, asset in pairs(AMENITY_ASSETS) do
                    local building_class = StaticFindObject(asset.class)
                    local loaded_class = loaded_amenity_classes[kind]
                    if (not building_class or not building_class:IsValid())
                        and loaded_class and loaded_class:IsValid() then
                        building_class = loaded_class
                    end
                    amenity_classes[kind] = building_class
                    amenity_classes_valid = amenity_classes_valid
                        and building_class and building_class:IsValid()
                end
                local guid_library = StaticFindObject(GUID_LIBRARY)
                if not world or not world:IsValid()
                    or not gameplay_statics or not gameplay_statics:IsValid()
                    or not lift_class or not lift_class:IsValid()
                    or not ticket_class or not ticket_class:IsValid()
                    or not shed_class or not shed_class:IsValid()
                    or not amenity_classes_valid
                    or not guid_library or not guid_library:IsValid() then
                    log("resort classes or GUID library are unavailable")
                    done("resort classes are unavailable")
                    return
                end

                -- A station serialized in the initial SaveGame is loaded
                -- before the world subsystems initialize. In that case its
                -- placeables, hub members and trails already followed the
                -- complete native lifecycle; preserve them instead of
                -- destroying and recreating them after initialization.
                -- Source maps must replace template objects even when their
                -- coordinates happen to match a previous Veymont initial save.
                local preloaded = not source_only and collect_preloaded_station()
                if preloaded then
                    local bridge_count = seed_front_hub_bridges(
                        preloaded, world, gameplay_statics,
                        amenity_classes.warming_hut)
                    for _, lift in ipairs(preloaded.lifts) do
                        lift:SetOperatingHours(0.0, 24.0)
                        lift:SetSpeedSetting(2)
                        lift.MinOperatingSnowDepthCm = -1.0
                    end
                    for _, building in ipairs(preloaded.buildings) do
                        building:SetOperatingHours(0.0, 24.0)
                        building:SetOpen(true)
                    end
                    activate_veymont_winter()
                    activate_guest_arrivals(preloaded.ticket_office)
                    refresh_hub_visualization()
                    log_hub_registration(preloaded.lifts, guid_library)
                    log(string.format(
                        "native Veymont resort preserved: %d lifts, %d buildings, %d bridges added, %d trails",
                        #preloaded.lifts, #preloaded.buildings,
                        bridge_count,
                        get_registered_trail_count()))
                    log_current_lifts("native resort")
                    if preloaded.lifts[1] then
                        report_lift_status(preloaded.lifts[1])
                    end
                    done()
                    return
                end

                -- Source-only maps have no cooked InitialSave asset. Rebuild
                -- their placeables after the loader has generated the terrain.
                -- Keep operations closed while the template graph is removed:
                -- otherwise the transient empty graph raises the stock
                -- "No Complete Ski Run" dialog before our hubs and trails
                -- have even been registered.
                local operations = find_in_current_world(
                    "ResortOperationsSubsystem")
                if operations and operations:IsValid() then
                    pcall(function() operations:SetOperatingStatus(2) end)
                end
                clear_saved_station_objects()
                local base_hub_id = guid_library:NewGuid()
                local buildings = {}
                local ticket_office = nil
                local ticket_created, ticket_error = pcall(function()
                    ticket_office = spawn_ticket_office(
                        world, gameplay_statics, ticket_class, base_hub_id)
                end)
                if not ticket_created then
                    log("Ticket Office creation failed: " .. tostring(ticket_error))
                elseif ticket_office then
                    table.insert(buildings, ticket_office)
                end

                local snowcat_shed = nil
                local shed_created, shed_error = pcall(function()
                    snowcat_shed = spawn_snowcat_shed(
                        world, gameplay_statics, shed_class, base_hub_id)
                end)
                if not shed_created then
                    log("snowcat garage creation failed: " .. tostring(shed_error))
                elseif snowcat_shed then
                    table.insert(buildings, snowcat_shed)
                end

                local amenity_count = 0
                for _, definition in ipairs(VeymontData.amenities) do
                    local ok, building_or_error = pcall(function()
                        return spawn_amenity(
                            world, gameplay_statics,
                            amenity_classes[definition.kind],
                            base_hub_id, definition)
                    end)
                    if ok and building_or_error then
                        table.insert(buildings, building_or_error)
                        amenity_count = amenity_count + 1
                    else
                        log("amenity creation failed: " .. tostring(building_or_error))
                    end
                end

                local lifts = {}
                for _, definition in ipairs(VeymontData.lifts) do
                    local ok, lift_or_error = pcall(function()
                        return spawn_station_lift(
                            world, gameplay_statics, lift_class, guid_library,
                            base_hub_id, definition)
                    end)
                    if ok and lift_or_error then
                        table.insert(lifts, lift_or_error)
                        log(string.format(
                            "%s created on the real %s alignment",
                            definition.name,
                            definition.real_type == "chair_lift"
                                and "chairlift" or "surface-lift"))
                    else
                        log("could not create " .. definition.name .. ": " .. tostring(lift_or_error))
                    end
                end

                local bridge_count = 0
                local bridges_ok, bridges_or_error = pcall(function()
                    return create_front_hub_bridges(
                        world, gameplay_statics,
                        amenity_classes.warming_hut, base_hub_id)
                end)
                if bridges_ok then
                    for _, bridge in ipairs(bridges_or_error) do
                        table.insert(buildings, bridge)
                        bridge_count = bridge_count + 1
                    end
                    log(string.format(
                        "%d spatial bridge(s) added to the base hub",
                        bridge_count))
                else
                    log("base-hub bridge creation failed: " ..
                        tostring(bridges_or_error))
                end

                log_hub_lifecycle("after placeable finalization")

                local registry_ok, registry_error = pcall(function()
                    register_station_placeables(lifts, buildings)
                end)
                if not registry_ok then
                    log("registry population failed: " ..
                        tostring(registry_error))
                end
                log_hub_lifecycle("after registry population")

                local staff_ok, staff_error = pcall(function()
                    local staff = find_in_current_world("StaffSubsystem")
                    assert(staff and staff:IsValid(), "native staff subsystem is unavailable")
                    VeymontStaff.assign(staff,lifts,buildings,function()
                        NativeTerrain.refresh_staff_pool(staff)
                    end,log)
                end)
                if not staff_ok then log("staff initialization failed: " .. tostring(staff_error)) end

                local hubs_ok, hubs_message =
                    NativeTerrain.register_placeable_hubs(lifts, buildings)
                log("native hub registration: " ..
                    tostring(hubs_ok) .. " " .. tostring(hubs_message))

                local trail_count = register_station_trails()
                log_hub_lifecycle("after trail creation")
                activate_veymont_winter()
                if operations and operations:IsValid() then
                    pcall(function() operations:SetOperatingStatus(0) end)
                end
                activate_guest_arrivals(ticket_office)
                refresh_hub_visualization()
                rename_hub_labels()
                log_hub_registration(lifts, guid_library)
                log(string.format(
                    "Veymont resort active: %d/%d lifts, %d/%d trails, Ticket Office=%s, snowcat garage=%s, amenities=%d/%d, bridges=%d, registry=%s",
                    #lifts, #VeymontData.lifts, trail_count, #VeymontData.trails,
                    tostring(ticket_created), tostring(shed_created),
                    amenity_count, #VeymontData.amenities, bridge_count,
                    tostring(registry_ok)))
                log_current_lifts("final resort")
                if lifts[1] then
                    report_lift_status(lifts[1])
                end
                if #lifts == #VeymontData.lifts
                    and #buildings == 2 + #VeymontData.amenities + bridge_count
                    and trail_count == #VeymontData.trails and registry_ok
                    and hubs_ok and staff_ok then
                    done()
                else
                    done("the resort could not be created completely")
                end
            end)
        end)
    end)
end

local function prepare_veymont_view()
    ExecuteInGameThread(function()
        local world = UEHelpers.GetWorld()
        if world and world:IsValid() then
            log("active world: " .. world:GetFullName())
        end

        log("Veymont source terrain and procedural collision are active")

        local player = UEHelpers.GetPlayer()
        if player and player:IsValid() then
            -- Place the opening camera over Gresse's real base area and frame
            -- the Brisou lift alignments. This transform is intentionally a
            -- world-space view, not an offset inherited from Sugar Bowl.
            local location = { X = 70000.0, Y = -125000.0, Z = 210000.0 }
            local rotation = { Pitch = -43.0, Yaw = 145.0, Roll = 0.0 }
            NativeTerrain.set_camera_rotation(player, rotation)
            player:K2_SetActorLocationAndRotation(location, rotation, false, {}, true)
            -- The native free camera owns its view on FollowCamera. Rotating
            -- only the pawn leaves that component looking away from the resort.
            local camera = player.FollowCamera
            if camera and camera:IsValid() then
                camera:K2_SetWorldRotation(rotation, false, {}, true)
            end
            local controller = UEHelpers.GetPlayerController()
            if controller and controller:IsValid() then
                controller:SetControlRotation(rotation)
            end
            log("camera positioned over the Gresse-en-Vercors base area")
        else
            log("player pawn is unavailable; camera kept its source-level position")
        end
    end)

end

local function override_station_lift_boolean(context)
    local lift = context:get()
    if station_definition_for_lift(lift) then
        local surface=require('surface_lifts')
        if surface.is_adapted(lift) then return nil end
        return true
    end
    return nil
end

local function override_station_lift_status(context)
    if require('surface_lifts').is_adapted(context:get()) then return nil end
    if override_station_lift_boolean(context) == true then
        return FText("Operating")
    end
    return nil
end

local function install_station_lift_override(function_name, callback)
    local path = "/Script/SkiResortSimulator.LiftActor:" .. function_name
    local ok, pre_id, post_id = pcall(function()
        return RegisterHook(
            path,
            function(_) return nil end,
            callback)
    end)
    if ok then
        log(string.format(
            "%s override installed (%s/%s)",
            function_name, tostring(pre_id), tostring(post_id)))
    else
        log("could not install " .. function_name .. " override: " .. tostring(pre_id))
    end
end

local station_lift_overrides_installed = false
install_station_lift_overrides = function()
    if station_lift_overrides_installed then return end
    station_lift_overrides_installed = true
    install_station_lift_override(
        "IsLiftAvailableForSkiing", override_station_lift_boolean)
    install_station_lift_override(
        "IsLiftAvailableForTransportation", override_station_lift_boolean)
    install_station_lift_override(
        "IsLiftAvailableForHomeboundTransport", override_station_lift_boolean)
    install_station_lift_override("IsLiftRunning", override_station_lift_boolean)
    install_station_lift_override("HasOperatingLifties", override_station_lift_boolean)
    install_station_lift_override("IsWithinOperatingHours", override_station_lift_boolean)
    install_station_lift_override("IsOpenForBusiness", override_station_lift_boolean)
    install_station_lift_override("GetStatusText", override_station_lift_status)
end

log("loaded through the custom-map API")

return {
    on_event = function(event_name, event, api)
        if event_name == "map.unloading" then
            -- Release renderers before native save travel starts allocating
            -- the next world, and cancel insertion into the previous forest.
            Vegetation.unload()
        elseif event_name == "map.before_load" then
            install_station_lift_overrides()
            Vegetation.unload()
        elseif event_name == "map.ready" then
            api.game:set_trail_rating_system({colors = {
                beginner = '#008000', intermediate = '#0080FF',
                expert = '#FF0000', extreme = '#000000',
            }})
            local vegetation_done = api:hold_loading()
            if not event.restored then
                local station_done = api:hold_loading()
                prepare_veymont_view()
                build_veymont_station(function(message)
                    if message then station_done(message);return end
                    local ok,failure=pcall(function() Climate.apply(api,false);api:place_objects(Furnishings(VeymontData));Snowmaking.install(api,VeymontData,SNOWMAKING_DEFINITIONS) end)
                    station_done(not ok and tostring(failure) or nil)
                end, true)
            else
                log("saved resort preserved; rebuilding portable forest only")
                Climate.apply(api,true)
                Snowmaking.install(api,VeymontData,SNOWMAKING_DEFINITIONS)
            end
            api:every(500, function()
                rename_hub_labels()
                return true
            end)
            local source_ok, source_or_message = pcall(function()
                return api:read_asset("Vegetation/forest.skxy")
            end)
            if not source_ok then
                vegetation_done(tostring(source_or_message))
                return
            end
            -- Let lifts, trails and hubs settle before allocating the forest.
            -- Rebuild every portable source point. The full OSM density is
            -- needed at normal gameplay zoom; even distribution-preserving
            -- subsampling leaves the eight-kilometre terrain visibly empty.
            api:after(10000, function()
                Vegetation.load_skxy(source_or_message, api, {
                    mesh = "/Game/Meshes/Mountain/SM_Spruce_15m.SM_Spruce_15m",
                    stride = 1,
                    batch_size = 512,
                    cull_distance = 650000,
                    minimum_scale = 0.80,
                    maximum_scale = 1.20,
                }, function(message, created, source_count)
                    if message then
                        log("vegetation reconstruction failed: " .. tostring(message))
                        vegetation_done("vegetation could not be reconstructed")
                    else
                        log(string.format(
                            "portable forest reconstructed: %d/%d trees",
                            created, source_count))
                        vegetation_done()
                        -- Native finalization still runs after this callback.
                        -- Wait for the loading screen to disappear, then allow
                        -- queued stock warnings a few frames to surface.
                        local checks = 0
                        api:every(250, function()
                            for _, widget in ipairs(FindAllOf('LoadingScreenWidget') or {}) do
                                if widget and widget:IsValid() and widget:IsInViewport() then
                                    return true
                                end
                            end
                            dismiss_transient_ski_run_warning()
                            checks = checks + 1
                            return checks < 8
                        end)
                    end
                end)
            end)
        end
    end
}
