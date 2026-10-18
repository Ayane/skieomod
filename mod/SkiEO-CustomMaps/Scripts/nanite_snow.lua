-- Visual snow on the new rock ledges. The native R16 collision, snowfall,
-- grooming and melt simulation remain authoritative.
local Snow = {}
local function valid(value) return value and value:IsValid() end
local function clamp(value, low, high) return math.max(low, math.min(high, value)) end
function Snow.is_coat(entry)
    return entry.layer=='snow_deposits' or entry.layer=='snow_transition'
end
function Snow.coverage(depth)
    if type(depth)~='number' or depth~=depth or depth<=.2 then return 0 end
    local t=clamp((depth-.2)/10,0,1)
    return t*t*t*(10+t*(-15+6*t))
end
function Snow.material(world,entry,load)
    local base=load(entry.coat_material)
    assert(valid(base) and base:GetBaseMaterial().bUsedWithNanite,'snow coat material lacks Nanite')
    local library=StaticFindObject('/Script/Engine.Default__KismetMaterialLibrary')
    local material=library:CreateDynamicMaterialInstance(world,base,FName('CliffSnow'),0)
    assert(valid(material),'snow coat material creation failed')
    for key,value in pairs({DitherThresholdHeight=10000000,FadeRange=10000000,
            WorldOffsetStrength=0,EmissiveStrength=0,UVScale=1,Roughness=.85}) do
        material:SetScalarParameterValue(FName(key),value)
    end
    material:SetVectorParameterValue(FName('Color'),{R=.80,G=.88,B=.95,A=1})
    return material
end
function Snow.refresh(world,coats,snow)
    assert(valid(snow) and valid(snow.CoarseMipReadbackFp16RT),'native snow readback unavailable')
    local rt=snow.CoarseMipReadbackFp16RT
    -- A single amount for the continuous cliff avoids weather seams at cache
    -- partitions. Sample its surroundings: the old heightfield cannot retain
    -- snow at the new ledges' own XY coordinates. Geometry supplies retention.
    local bounds={1,1,0,0}
    for _,coat in ipairs(coats) do
        local b=coat.entry.snow_uv_bounds
        bounds[1]=math.min(bounds[1],b[1][1]);bounds[2]=math.min(bounds[2],b[1][2])
        bounds[3]=math.max(bounds[3],b[2][1]);bounds[4]=math.max(bounds[4],b[2][2])
    end
    local k=StaticFindObject('/Script/Engine.Default__KismetRenderingLibrary')
    local total=0
    for y=0,2 do for x=0,2 do
        local u=bounds[1]+(bounds[3]-bounds[1])*x/2
        local v=bounds[2]+(bounds[4]-bounds[2])*y/2
        local color=k:ReadRenderTargetRawPixel(world,rt,
            clamp(math.floor(u*rt.SizeX),0,rt.SizeX-1),
            clamp(math.floor(v*rt.SizeY),0,rt.SizeY-1),false)
        assert(type(color.R)=='number' and color.R==color.R and math.abs(color.R)<1e6,
            'invalid native snow depth')
        total=total+math.max(0,color.R)
    end end
    local amount=Snow.coverage(total/9)
    local updated={}
    for _,coat in ipairs(coats) do
        if valid(coat.component) and valid(coat.material) then
            if not updated[coat.material] then
                coat.material:SetScalarParameterValue(FName('DitherThresholdHeight'),
                    10000000*(1-2*amount))
                updated[coat.material]=true
            end
            if coat.coverage==nil or (coat.coverage==0)~=(amount==0) then
                coat.component:SetVisibility(amount>0,false)
            end
            coat.coverage=amount
        end
    end
    return total/9,amount
end
function Snow.start(terrain,state,coats,schedule,log)
    if #coats==0 then return end
    local generation,world=terrain.generation,terrain.actor:GetWorld()
    local subsystem
    for _,object in ipairs(FindAllOf('SnowSimulationSubsystem') or {}) do
        if valid(object) and object:GetWorld():GetAddress()==world:GetAddress() then subsystem=object;break end
    end
    local reported=false
    local function update()
        if terrain.generation~=generation or terrain.active~=state or not valid(terrain.actor) then return end
        local ok,depth,coverage=pcall(Snow.refresh,world,coats,subsystem)
        if ok then
            state.nanite_snow_depth_cm=depth;state.nanite_snow_coverage=coverage
        else
            for _,coat in ipairs(coats) do
                coat.coverage=nil
                if valid(coat.component) then coat.component:SetVisibility(false,false) end
            end
            if not reported then log('Cliff snow postponed: '..tostring(depth));reported=true end
        end
        schedule(5000,update)
    end
    update()
end
return Snow
