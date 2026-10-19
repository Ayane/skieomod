-- Preserve authored trail-marker IDs across the native 26040817 rename.
local Helpers=require('UEHelpers')
local Variants={}
local marker_class='/Game/Blueprints/Decorations/BP_TrailMarkers.BP_TrailMarkers_C'
local renamed={Beginner='GreenCircle',Intermediate='BlueSquare',Expert='BlackDiamond'}
function Variants.apply(actor,id)
    local resolved=id
    if actor:IsA(marker_class) and renamed[id] then
        local available={}
        actor.Variants:ForEach(function(_,wrapped)
            local variant=wrapped:get()
            available[variant.Id:ToString()]=true
        end)
        if not available[id] and available[renamed[id]] then resolved=renamed[id] end
    end
    actor:ApplyVariant(Helpers.FindOrAddFName(resolved))
    assert(actor.VariantId:ToString()==resolved,'Scene variant unavailable: '..id)
    return resolved
end
return Variants
