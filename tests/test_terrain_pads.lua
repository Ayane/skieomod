package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local world={IsValid=function() return true end,GetAddress=function() return 10 end}
package.loaded.UEHelpers={GetWorld=function() return world end}
local checks=0
package.loaded.compatibility={require=function(_,contract)
    assert(contract.classes['/Script/SkiResortSimulator.PlaceableActor'].TerraformPadComponents.offset==0x388)
    checks=checks+1
end}
local Native=require('native_terrain')
local writes,called,status={},0,nil
local oldopen,oldremove,oldload=io.open,os.remove,package.loadlib
io.open=function(path,mode)
    if mode=='wb' then return {write=function(_,data) writes[path]=data;return true end,close=function() return true end} end
    if path:match('native_terrain.status$') and status then return {read=function() return status end,close=function() return true end} end
end
os.remove=function(path) if path:match('native_terrain.status$') then status=nil end end
package.loadlib=function(_,name)
    assert(name=='skieo_refresh_placeable_pads')
    return function()
        called=called+1
        local data=writes['mod/SkiEO-CustomMaps/Scripts/native_pads.job']
        local magic,version,count,reserved,pos=string.unpack('<c4I4I4I4',assert(data))
        assert(magic=='SKPD' and version==1 and count==1 and reserved==0)
        local address,class,last=string.unpack('<I8I8',data,pos)
        assert(address==123 and class==456 and last==#data+1)
        status='ok: refreshed 1 native terrain pad owner(s)'
    end
end
local actor={IsValid=function() return true end,GetAddress=function() return 123 end,
    GetClass=function() return {GetAddress=function() return 456 end} end,
    GetWorld=function() return world end,IsA=function(_,path) return path=='/Script/SkiResortSimulator.PlaceableActor' end,
    IsActorBeingDestroyed=function() return false end}
assert(Native.refresh_placeable_pads({}) and checks==0 and called==0)
assert(Native.refresh_placeable_pads({actor}) and checks==1 and called==1)
actor.bIsPreview=true
assert(not pcall(Native.refresh_placeable_pads,{actor}) and called==1)
actor.bIsPreview=false;actor.GetWorld=function() return {IsValid=function() return true end,GetAddress=function() return 11 end} end
assert(not pcall(Native.refresh_placeable_pads,{actor}) and called==1)
io.open,os.remove,package.loadlib=oldopen,oldremove,oldload
print('Native terrain pads: current live actors, exact job ABI, empty scene and preview/foreign-world rejection OK')
