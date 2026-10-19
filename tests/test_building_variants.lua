package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function()return {FindOrAddFName=function(value)return value end}end
local Variants=require('building_variants')
local function actor(ids,is_marker)
    local available={};for _,id in ipairs(ids)do available[id]=true end
    local actor={VariantId={ToString=function()return 'None'end}}
    actor.IsA=function()return is_marker end
    actor.Variants={ForEach=function(_,callback)
        for _,id in ipairs(ids)do callback(nil,{get=function()return {Id={ToString=function()return id end}}end})end
    end}
    actor.ApplyVariant=function(self,id)if available[id]then self.VariantId={ToString=function()return id end}end end
    return actor
end
for old,new in pairs({Beginner='GreenCircle',Intermediate='BlueSquare',Expert='BlackDiamond'})do
    local legacy=actor({'Beginner','Intermediate','Expert'},true)
    assert(Variants.apply(legacy,old)==old and legacy.VariantId:ToString()==old)
    local current=actor({'GreenCircle','BlueSquare','BlackDiamond'},true)
    assert(Variants.apply(current,old)==new and current.VariantId:ToString()==new)
    assert(Variants.apply(current,new)==new)
end
assert(not pcall(Variants.apply,actor({'BlueSquare'},true),'Expert'),'missing replacement variant was accepted')
assert(not pcall(Variants.apply,actor({'BlackDiamond'},false),'Expert'),'another building class was remapped')
assert(not pcall(Variants.apply,actor({'BlackDiamond'},true),'Unknown'),'unknown authored variant was accepted')
print('Building variants: old and new native IDs, class-scoped migration and unavailable variants checked')
