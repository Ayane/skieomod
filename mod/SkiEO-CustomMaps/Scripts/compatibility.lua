-- Reflection checks precede private access and optional hooks. A failed
-- feature stays isolated; diagnostics never claim full game qualification.
local Json = require('json')
local Compat = {features={}, callbacks={}}
local function valid(o) return o and o:IsValid() end
local function copy(o) return Json.decode(Json.encode(o)) end

function Compat.record(feature, ok, detail)
    local previous=Compat.features[feature]
    local value={available=not not ok,detail=tostring(detail or (ok and 'ready' or 'unavailable'))}
    Compat.features[feature]=value
    if not ok and (not previous or previous.detail~=value.detail or previous.available) then
        print('[Custom Map compatibility] '..feature..': '..value.detail..'\n')
    end
    return ok,value.detail
end

function Compat.snapshot() return copy(Compat.features) end

local function properties(cls,inherited)
    local result,seen,order={},{},{}
    while valid(cls) and not seen[cls:GetAddress()] do
        seen[cls:GetAddress()]=true
        cls:ForEachProperty(function(p)
            local name=p:GetFName():ToString()
            if not result[name] then result[name]=p;order[#order+1]=name end
        end)
        if not inherited then break end
        cls=cls:GetSuperStruct()
    end
    return result,order
end

local function address(pointer)
    if type(pointer)=='number' then return pointer end
    local label=tostring(pointer)
    local hex=label:match('0x(%x+)$') or label:match('^userdata:%s*(%x+)$')
    return hex and tonumber(hex,16)
end

-- ContainerPtrToValuePtr uses UE4SS's reflected FProperty; it does not read
-- the property's value. This avoids guessing the engine's FProperty layout.
function Compat.field_offset(property,object)
    local pointer=assert(address(property:ContainerPtrToValuePtr(object,0)),
        'UE4SS did not expose a property address')
    local offset=pointer-object:GetAddress()
    assert(offset>=0 and offset%1==0 and offset<1024*1024,'invalid reflected field offset')
    return offset
end

function Compat.check(feature,contract)
    local ok,failure=pcall(function()
        for path,fields in pairs(contract.classes or {}) do
            local cls=StaticFindObject(path)
            assert(valid(cls),'missing class '..path)
            local observed=properties(cls,true)
            local cdo
            for name,expected in pairs(fields) do
                local field=assert(observed[name],'missing field '..path..'.'..name)
                local kind=type(expected)=='table' and expected.type or expected
                assert(field:GetClass():GetFName():ToString()==kind,'changed field type '..path..'.'..name)
                if type(expected)=='table' and expected.offset then
                    if not cdo then
                        cdo=StaticFindObject(path:gsub('%.([^%.]+)$','.Default__%1'))
                        assert(valid(cdo),'missing default object '..path)
                    end
                    assert(Compat.field_offset(field,cdo)==expected.offset,
                        'changed private layout anchor '..path..'.'..name)
                end
                if type(expected)=='table' and expected.struct then
                    local struct=field:GetStruct()
                    assert(valid(struct),'missing struct '..path..'.'..name)
                    local members=properties(struct,false)
                    for member,member_type in pairs(expected.struct) do
                        assert(members[member] and members[member]:GetClass():GetFName():ToString()==member_type,
                            'changed struct member '..path..'.'..name..'.'..member)
                    end
                end
            end
        end
        for path,expected in pairs(contract.functions or {}) do
            local fn=StaticFindObject(path)
            assert(valid(fn),'missing function '..path)
            if expected~=true then
                local observed,order=properties(fn,false)
                for name,kind in pairs(expected) do
                    assert(observed[name] and observed[name]:GetClass():GetFName():ToString()==kind,
                        'changed function parameter '..path..'.'..name)
                end
                for name in pairs(observed) do assert(expected[name],'new function parameter '..path..'.'..name) end
                local wanted=contract.function_order and contract.function_order[path]
                if wanted then
                    assert(#wanted==#order,'changed function parameter order '..path)
                    for i,name in ipairs(wanted) do assert(order[i]==name,'changed function parameter order '..path..'.'..name) end
                end
            end
        end
    end)
    return Compat.record(feature,ok,ok and 'reflected contract matched' or failure)
end

function Compat.require(feature,contract)
    local ok,detail=Compat.check(feature,contract)
    assert(ok,'incompatible game feature '..feature..': '..detail)
end

function Compat.hook(feature,path,phase,callback,parameters)
    if Compat.callbacks[feature] then
        local status=Compat.features[feature]
        return status.available,status.detail
    end
    local order
    if parameters and parameters.parameters then order=parameters.order;parameters=parameters.parameters end
    local ok,detail=Compat.check(feature,{functions={[path]=parameters or true},function_order=order and {[path]=order}})
    if not ok then return false,detail end
    local state={enabled=true}
    state.callback=function(...)
        if not state.enabled then return nil end
        local result=table.pack(pcall(callback,...))
        if not result[1] then
            state.enabled=false
            Compat.record(feature,false,'hook disabled after Lua error: '..tostring(result[2]))
            return nil
        end
        return table.unpack(result,2,result.n)
    end
    state.pre=function() return nil end
    ok,detail=pcall(function()
        assert(type(RegisterHook)=='function','UE4SS RegisterHook unavailable')
        if phase=='post' then RegisterHook(path,state.pre,state.callback)
        else RegisterHook(path,state.callback) end
    end)
    if ok then Compat.callbacks[feature]=state end -- retain UE4SS callbacks
    return Compat.record(feature,ok,ok and 'hook installed' or detail)
end

function Compat.startup(feature,callback)
    local ok,detail=pcall(callback)
    return Compat.record('startup.'..feature,ok,ok and 'installed' or detail)
end

function Compat.require_startup(feature)
    local status=Compat.features['startup.'..feature]
    assert(not status or status.available,'required loader feature unavailable: '..feature..': '..(status and status.detail or ''))
end

return Compat
