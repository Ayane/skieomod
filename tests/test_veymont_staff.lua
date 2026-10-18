package.path = "mod/SkiEO-Veymont/Scripts/?.lua;" .. package.path
local Staff = require("veymont_staff")
local function wrap(values)
    local result = {}
    for _, value in ipairs(values) do result[#result+1] = {get=function() return value end} end
    return result
end
local function actor(id, name)
    return {GetLiftId=function() return id end,GetBuildingId=function() return id end,
        GetFullName=function() return name end}
end
local lifts = {actor("lift-a","Lift A"),actor("lift-b","Lift B")}
local buildings = {actor("patrol","BP_SkiPatrolHut_C"),actor("garage","BP_SnowcatShed_C"),
    actor("ticket","BP_TicketOffice_C"),actor("cocoa","BP_HotCocoaCart_C")}
local roster = {{ID=1,Role=1,home='stock-lift',HomeBuildingId='stock-lift'},
    {ID=2,Role=2,home='stock-shed',HomeBuildingId='stock-shed'}}
local pool = {{ID=3,Role=0},{ID=4,Role=3}}
local roles = {['lift-a']=1,['lift-b']=1,patrol=0,garage=2}
local subsystem = {}
function subsystem:GetRoster() return wrap(roster) end
function subsystem:UnassignStaffFromBuilding(id)
    for _,m in ipairs(roster) do if m.ID==id then m.home=nil;m.HomeBuildingId=nil end end
end
function subsystem:GetUnassignedStaff()
    local result={};for _,m in ipairs(roster) do if not m.home then result[#result+1]=m end end
    return wrap(result)
end
function subsystem:GetHiringPool() return wrap(pool) end
function subsystem:GetStaffCountAtBuilding(id)
    local count=0;for _,m in ipairs(roster) do if m.home==id then count=count+1 end end
    return count
end
function subsystem:HireFromPool(id)
    for i,m in ipairs(pool) do if m.ID==id then table.remove(pool,i);roster[#roster+1]=m;return true end end
    return false
end
function subsystem:AssignStaffToBuilding(id,home)
    for _,m in ipairs(roster) do if m.ID==id then
        assert(m.Role==roles[home]);m.home=home;m.HomeBuildingId=home;return true
    end end
    return false
end
local refreshes, next_id = 0, 10
local function refresh()
    refreshes=refreshes+1
    pool={};for role=0,3 do pool[#pool+1]={ID=next_id,Role=role};next_id=next_id+1 end
end
local assigned,hired=Staff.assign(subsystem,lifts,buildings,refresh)
assert(assigned==8 and hired==6 and refreshes>0)
for id in pairs(roles) do assert(subsystem:GetStaffCountAtBuilding(id)==2) end
assert(subsystem:GetStaffCountAtBuilding('ticket')==0 and subsystem:GetStaffCountAtBuilding('cocoa')==0)
assigned,hired=Staff.assign(subsystem,lifts,buildings,refresh)
assert(assigned==0 and hired==0,'staff was duplicated instead of preserved')
local failure={GetStaffCountAtBuilding=function() return 0 end,
    GetRoster=function() return {} end,
    GetUnassignedStaff=function() return {} end,GetHiringPool=function() return {} end}
local calls=0
local ok,message=pcall(Staff.assign,failure,lifts,{},function() calls=calls+1 end)
assert(not ok and message:find('not enough applicants',1,true) and calls==20)
print('Veymont staff: roles, native hiring, existing roster, refreshes, idempotence and bounded failure OK')
