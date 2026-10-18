package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Staff=require('resort_staff')
local function wrap(values)
    local result={}
    for _,value in ipairs(values) do result[#result+1]={get=function()return value end} end
    return result
end
local function actor(id,name)
    return {GetLiftId=function()return id end,GetBuildingId=function()return id end,
        GetFullName=function()return name end}
end
local lifts={actor('menouve','BP_Gondola_C'),actor('plan','BP_FixedChair1_C')}
local buildings={actor('patrol','BP_SkiPatrolHut_C'),actor('garage','BP_SnowcatShed_C'),
    actor('workshop','BP_Maintenance_C'),actor('ticket','BP_TicketOffice_C')}
-- EStaffRole in the game: SkiPatrol=0, Liftie=1, Groomer=2, Maintenance=3.
local roles={menouve=1,plan=1,patrol=0,garage=2,workshop=3}
local roster={{ID=1,Role=1,HomeBuildingId='old-lift'},
    {ID=2,Role=2,HomeBuildingId='old-garage'},
    {ID=3,Role=3,HomeBuildingId='old-workshop'}}
local pool={{ID=4,Role=0},{ID=5,Role=3}}
local subsystem={}
function subsystem:GetRoster()return wrap(roster)end
function subsystem:UnassignStaffFromBuilding(id)
    for _,member in ipairs(roster)do if member.ID==id then member.HomeBuildingId=nil end end
end
function subsystem:GetUnassignedStaff()
    local result={}
    for _,member in ipairs(roster)do if not member.HomeBuildingId then result[#result+1]=member end end
    return wrap(result)
end
function subsystem:GetHiringPool()return wrap(pool)end
function subsystem:GetStaffCountAtBuilding(id)
    local count=0
    for _,member in ipairs(roster)do if member.HomeBuildingId==id then count=count+1 end end
    return count
end
function subsystem:HireFromPool(id)
    for i,member in ipairs(pool)do
        if member.ID==id then table.remove(pool,i);roster[#roster+1]=member;return true end
    end
    return false
end
function subsystem:AssignStaffToBuilding(id,home)
    for _,member in ipairs(roster)do
        if member.ID==id then
            assert(member.Role==roles[home],'employee assigned to the wrong profession')
            member.HomeBuildingId=home;return true
        end
    end
    return false
end
local refreshes,next_id=0,10
local function refresh()
    refreshes=refreshes+1;pool={}
    for role=0,3 do pool[#pool+1]={ID=next_id,Role=role};next_id=next_id+1 end
end
local assigned,hired=Staff.assign(subsystem,lifts,buildings,refresh)
assert(assigned==10 and hired==7 and #roster==10 and refreshes>0,
    'starting employees were not reused through native hiring')
for id in pairs(roles)do assert(subsystem:GetStaffCountAtBuilding(id)==2)end
assert(subsystem:GetStaffCountAtBuilding('ticket')==0)
local former_mechanic=roster[3]
assert(former_mechanic.HomeBuildingId=='workshop','the existing maintenance employee was left on an absent building')
local pool_refreshes=refreshes
assigned,hired=Staff.assign(subsystem,lifts,buildings,refresh)
assert(assigned==0 and hired==0 and #roster==10 and refreshes==pool_refreshes,
    'repeated initialization hired duplicate salaried employees')
print('Resort staff: two patrollers, two mechanics, groomers, lifties, native hiring, starter reuse and idempotence OK')
