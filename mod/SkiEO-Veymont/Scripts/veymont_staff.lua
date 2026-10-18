local Staff = {}

local function members(values)
    local result = {}
    for _, value in ipairs(values) do result[#result + 1] = value:get() end
    return result
end

local function guid_key(id)
    if type(id) == 'string' then return id end
    if not id then return nil end
    if id.A == 0 and id.B == 0 and id.C == 0 and id.D == 0 then return nil end
    return table.concat({id.A,id.B,id.C,id.D}, ':')
end

-- Use the game's hiring and assignment lifecycle so wages, traits, movement
-- and SaveGame records stay native. This is called only for a new resort.
function Staff.assign(subsystem, lifts, buildings, refresh_pool, log)
    local targets, live_ids = {}, {}
    for _, lift in ipairs(lifts) do
        local id = lift:GetLiftId()
        live_ids[guid_key(id)] = true
        targets[#targets + 1] = {actor=lift,id=id,role=1,count=2}
    end
    for _, building in ipairs(buildings) do
        local id = building:GetBuildingId()
        live_ids[guid_key(id)] = true
        local name = building:GetFullName()
        local role = name:find("BP_SkiPatrolHut",1,true) and 0
            or (name:find("BP_SnowcatShed",1,true) and 2 or nil)
        if role then
            targets[#targets + 1] = {actor=building,id=id,role=role,count=2}
        end
    end

    -- Native new-game starters can refer to the stock starting lift/shed
    -- GUIDs even in Entry. Free those dangling assignments and reuse the
    -- employees instead of leaving an invisible, salaried starter roster.
    for _, member in ipairs(members(subsystem:GetRoster())) do
        local home = guid_key(member.HomeBuildingId)
        if home and not live_ids[home] then subsystem:UnassignStaffFromBuilding(member.ID) end
    end

    local hired, assigned, refreshes = 0, 0, 0
    for _, target in ipairs(targets) do
        while subsystem:GetStaffCountAtBuilding(target.id) < target.count do
            local available
            for _, member in ipairs(members(subsystem:GetUnassignedStaff())) do
                if member.Role == target.role then available=member;break end
            end
            if not available then
                local applicant
                for _, member in ipairs(members(subsystem:GetHiringPool())) do
                    if member.Role == target.role then applicant=member;break end
                end
                if not applicant then
                    assert(refreshes < 20, "not enough applicants to staff the new resort")
                    refresh_pool()
                    refreshes = refreshes + 1
                else
                    assert(subsystem:HireFromPool(applicant.ID), "native staff hire failed")
                    hired = hired + 1
                end
            else
                assert(subsystem:AssignStaffToBuilding(available.ID,target.id),
                    "native staff assignment failed for " .. target.actor:GetFullName())
                assigned = assigned + 1
            end
        end
    end
    if log then log(string.format("native staff assigned: %d employee(s), %d hire(s), %d hiring-pool refresh(es)",
        assigned,hired,refreshes)) end
    return assigned, hired
end

return Staff
