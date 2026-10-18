local Json, Helpers = require('json'), require('UEHelpers')
local Ratings = {}
local directory = debug.getinfo(1, 'S').source:match('^@(.*[/\\])[^/\\]+$')
local native, owner
local styles = {north_american=1, european=2, japanese=3}
local levels = {beginner=1, intermediate=2, expert=3, extreme=4}

local function finite(value)
    return type(value)=='number' and value==value and math.abs(value)<math.huge
end
local function copy(value) return value and Json.decode(Json.encode(value)) end

function Ratings.validate(options)
    assert(type(options)=='table','trail rating system must be a table or nil to reset')
    for key in pairs(options) do
        assert(key=='style' or key=='thresholds_degrees' or key=='thresholds_percent' or key=='colors',
            'unknown trail rating option: '..tostring(key))
    end
    assert(options.style==nil or styles[options.style],
        'trail rating style must be european, north_american or japanese')
    for _,key in ipairs({'thresholds_degrees','thresholds_percent'}) do
        assert(options[key]==nil or type(options[key])=='table',key..' must be an array')
    end
    assert(not (options.thresholds_degrees and options.thresholds_percent),
        'choose thresholds_degrees or thresholds_percent, not both')
    local values=options.thresholds_degrees or options.thresholds_percent
    local mask,colors=0,{0,0,0,0}
    if options.colors~=nil then
        assert(type(options.colors)=='table','trail rating colors must be a table')
        for level,color in pairs(options.colors) do
            local index=levels[level]
            assert(index,'unknown trail rating color level: '..tostring(level))
            assert(type(color)=='string' and color:match('^#%x%x%x%x%x%x$'),
                'trail rating color '..level..' must use #RRGGBB')
            colors[index]=tonumber(color:sub(2),16)
            mask=mask | (1 << (index-1))
        end
        assert(mask~=0,'trail rating colors must define at least one level')
    end
    assert(options.style or values or mask~=0,'choose a trail rating style, colors or slope thresholds')
    local degrees={0,0,0}
    local count=0
    if values then
        assert(type(values)=='table' and (#values==2 or #values==3),
            'slope thresholds need two or three increasing values')
        count=#values
        for key in pairs(values) do
            assert(type(key)=='number' and key%1==0 and key>=1 and key<=count,
                'slope thresholds must be an array')
        end
        for i,value in ipairs(values) do
            assert(finite(value) and value>0 and (i==1 or value>values[i-1]),
                'slope thresholds must be finite, positive and strictly increasing')
            local angle=options.thresholds_percent and math.deg(math.atan(value/100)) or value
            assert(angle<=90 and angle>0 and (i==1 or angle>degrees[i-1]),
                'slope thresholds must be distinct angles at most 90 degrees')
            degrees[i]=angle
        end
    end
    return {options=copy(options),style=styles[options.style] or -1,count=count,degrees=degrees,
        color_mask=mask,colors=colors}
end

local function apply(configuration)
    assert(directory,'trail rating helper path is unavailable')
    if not native then
        local failure
        native,failure=package.loadlib(directory..'skieo_trail_ratings.dll','skieo_trail_ratings')
        assert(native,'trail rating helper unavailable: '..tostring(failure)..'; update Custom Map')
    end
    local path=directory..'native_trail_ratings.'
    local file=assert(io.open(path..'job','wb'))
    local c=configuration or {style=-1,count=0,degrees={0,0,0},color_mask=0,colors={0,0,0,0}}
    assert(file:write(string.pack('<c4I4I4i4I4fffI4I4I4I4I4','SKRT',2,configuration and 1 or 0,
        c.style,c.count,c.degrees[1],c.degrees[2],c.degrees[3],c.color_mask,
        c.colors[1],c.colors[2],c.colors[3],c.colors[4])))
    assert(file:close());os.remove(path..'status')
    native()
    file=io.open(path..'status','rb')
    local result=file and file:read(256)
    if file then file:close() end
    assert(result=='ok',result or 'native trail rating helper did not respond')
end

local function valid(object) return object and object:IsValid() end
local function refresh()
    local world=Helpers.GetWorld()
    if not valid(world) then return end
    for _,visualization in ipairs(FindAllOf('TrailVisualizationSubsystem') or {}) do
        if valid(visualization) and not visualization:GetFullName():find('Default__',1,true) then
            local current=visualization:GetWorld()
            if valid(current) and current:GetAddress()==world:GetAddress() then
                -- Re-register visuals, preserving each trail's player rating,
                -- geometry, grooming, traffic and native save data.
                local map=visualization.TrailMapSubsystem
                if valid(map) then
                    map.RegisteredTrails:ForEach(function(key)
                        visualization:OnTrailRegistered(key:get())
                    end)
                end
                visualization:RefreshLabels()
            end
        end
    end
    local Terrain=require('terrain')
    if Terrain.active and valid(Terrain.actor) then Terrain.rebuild_trail_visuals(true) end
end

function Ratings.set(api,options)
    local configuration=options~=nil and Ratings.validate(options) or nil
    assert(not owner or owner==api,'another map owns the trail rating system')
    if not configuration and not owner then return end
    apply(configuration)
    owner=configuration and api or nil
    api._trail_rating_system=configuration and configuration.options or nil
    if configuration and not api._trail_rating_cleanup then
        api._trail_rating_cleanup=true
        api._cleanups=api._cleanups or {}
        api._cleanups[#api._cleanups+1]=function()
            if owner==api then
                apply(nil);owner=nil;api._trail_rating_system=nil
            end
            api._trail_rating_cleanup=nil
        end
        api:on('map.ready',function() if owner==api then refresh() end end)
    end
    refresh()
    return copy(api._trail_rating_system)
end

function Ratings.get(api) return copy(api._trail_rating_system) end

function Ratings.capabilities()
    local ok,result=pcall(function()
        assert(directory,'trail rating helper path is unavailable')
        local inspect=assert(package.loadlib(directory..'skieo_trail_ratings.dll','skieo_trail_ratings_capabilities'))
        local path=directory..'native_trail_ratings.capabilities.json'
        os.remove(path);inspect()
        local f=assert(io.open(path,'rb'),'native trail rating capability probe did not respond')
        local source=f:read(16385);f:close()
        assert(#source<=16384,'oversized native capability report')
        local value=Json.decode(source)
        assert(type(value)=='table','invalid native capability report')
        assert(value.detail==nil or type(value.detail)=='string','invalid native capability detail')
        for _,name in ipairs({'thresholds','style','colors'}) do
            assert(type(value[name])=='boolean','invalid native capability '..name)
        end
        return value
    end)
    if not ok then result={thresholds=false,style=false,colors=false,detail=tostring(result)} end
    local Compat=require('compatibility')
    for _,name in ipairs({'thresholds','style','colors'}) do
        Compat.record('trails.'..name,result[name],result[name] and 'native contract matched' or result.detail or 'native contract unavailable')
    end
    -- Addresses stay in the local diagnostic file; map authors need booleans.
    return {thresholds=result.thresholds,style=result.style,colors=result.colors,detail=result.detail}
end
return Ratings
