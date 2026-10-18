package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local J=require('json')
local state={x=-5104.417813154512,y=134123.4571239841,heading=1.2345678901234567,seed=2147483646,large_integer=math.maxinteger}
local restored=J.decode(J.encode(state))
for k,n in pairs(state) do assert(restored[k]==n,'save JSON lost simulation precision for '..k) end
print('Save JSON: positions, headings and integer seeds retain full numeric precision OK')
