-- Bounded, complete uphill coverage. Unknown readback never reopens a lift.
local Snow={}
local function measured(value)return math.abs(value)<math.huge and value or nil end
function Snow.limits(item)
    local d=item.definition or{}
    local maximum=d.max_snow_cm or(d.kind=='fixed_platter'and 150 or 250)
    return 3,5,maximum,maximum-20
end
function Snow.scan(item,sample,budget)
    local low,reopen_low,high,reopen_high=Snow.limits(item)
    local scan=item.snow_scan or {index=1,minimum=math.huge,maximum=-math.huge,known=true}
    item.snow_scan=scan
    for _=1,budget do
        local p=item.route.points[scan.index]
        if not p then
            local complete=scan.known and scan.minimum>=reopen_low and scan.maximum<=reopen_high
            item.snow_scan=nil
            return complete and 'clear' or 'pending',measured(scan.minimum),true,nil,measured(scan.maximum)
        end
        local e=sample(p.x-p.nx*160,p.y-p.ny*160)
        if not e.snow_ready then scan.known=false
        else
            scan.minimum=math.min(scan.minimum,e.snow_cm)
            scan.maximum=math.max(scan.maximum,e.snow_cm)
            local reason=e.snow_cm<low and 'insufficient' or e.snow_cm>high and 'excess'
            if reason then
                scan.index=scan.index+1
                return 'blocked',scan.minimum,false,reason,scan.maximum
            end
        end
        scan.index=scan.index+1
    end
    return 'pending',measured(scan.minimum),false,nil,measured(scan.maximum)
end
return Snow
