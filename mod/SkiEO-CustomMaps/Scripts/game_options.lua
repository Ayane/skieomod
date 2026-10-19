-- Reuse the game's option controls. Copy plain values before asynchronous
-- downloads, then stage the reviewed native request immediately before travel.
local Options={}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
function Options.validate(options)
    options=options or {seed=0,day_length=1,days_per_month=1,sandbox=false}
    assert(type(options)=='table','invalid game options')
    assert(type(options.seed)=='number' and options.seed%1==0 and options.seed>=-2147483648 and options.seed<=2147483647,'invalid seed')
    assert(type(options.day_length)=='number' and options.day_length>=0.05 and options.day_length<=64,'invalid day length')
    assert(type(options.days_per_month)=='number' and options.days_per_month%1==0 and options.days_per_month>=1 and options.days_per_month<=31,'invalid days per month')
    assert(type(options.sandbox)=='boolean','invalid sandbox option')
    return {seed=options.seed,day_length=options.day_length,days_per_month=options.days_per_month,sandbox=options.sandbox}
end
function Options.capture(owner)
    local function text(widget) return widget:GetText():ToString() end
    local seed=assert(tonumber(text(owner.SeedInput)),'invalid native seed')
    if seed>2147483647 and seed<=4294967295 then seed=seed-4294967296 end
    local sandbox=text(owner.SandboxStateText):lower()
    assert(sandbox=='on' or sandbox=='off','unrecognized native sandbox setting')
    local day_length=tonumber(((text(owner.DayLengthValueText):match('[%d.,]+') or ''):gsub(',','.')))
    local days=tonumber(text(owner.DaysPerMonthValueText))
    return Options.validate({seed=seed,day_length=day_length,days_per_month=days,sandbox=sandbox=='on'})
end
function Options.stage(session,options)
    options=Options.validate(options)
    require('compatibility').require('saves.session_layout',require('compatibility_contracts').session)
    local job,status=directory..'game_options.job',directory..'game_options.status'
    local file=assert(io.open(job,'wb'))
    assert(file:write(string.pack('<c4I4I8I8i4fI4I4','SKGO',1,session:GetAddress(),session:GetClass():GetAddress(),
        options.seed,options.day_length,options.days_per_month,options.sandbox and 1 or 0)))
    assert(file:close());os.remove(status)
    local helper=assert(package.loadlib(directory..'skieo_native_terrain.dll','skieo_stage_game_options'))
    local ok,message=pcall(helper)
    file=io.open(status,'rb');local result=file and file:read('*a');if file then file:close() end
    os.remove(job);os.remove(status)
    assert(ok,message)
    assert(result and result:sub(1,3)=='ok:',result or 'could not stage native game options')
end
return Options
