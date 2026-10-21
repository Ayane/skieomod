local json,Archive,Versions=require('json'),require('archive'),require('versions')
local Repository=require('repository')
local Update={interval=600,current=require('loader_version'),message='Checking for a mod update…'}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local origin='https://skieomod.emillon.fr/downloads/'
local prefix='SkiEO-CustomMaps/'
local required={'Scripts/main.lua','Scripts/entry.lua','Scripts/skieo_repository.dll','Scripts/skieo_native_terrain.dll',
    'Scripts/skieo_updater.exe','Scripts/skieo_update_bootstrap.dll'}
local busy,next_check,next_status,started_at,preparing,callback=false,0,0,nil,nil,nil
local function read(path,limit)
    local f=io.open(path,'rb');if not f then return nil end
    local bytes=f:read((limit or 1024*1024)+1);f:close()
    assert(not bytes or #bytes<=(limit or 1024*1024),'update file exceeds its limit');return bytes
end
local function digest(value)return type(value)=='string' and #value==64 and value:match('^[0-9a-f]+$')end
local function managed(path)
    if not Archive.safe_path(path) then return false end
    for part in path:gmatch('[^/]+') do if part:sub(1,1)=='.' then return false end end
    return path=='LICENSE' or path=='LICENSE-miniz.txt' or path=='Scripts/skieo_updater.exe'
        or path:lower():match('%.lua$') or path:lower():match('%.dll$') or path:lower():match('%.md$')
        or path:match('^Examples/[^/]+%.skieomap$')
end
Update.managed=managed
local function validate_record(record,updater_required)
    assert(type(record)=='table' and record.format=='skieomod-loader' and record.version==1,'unsupported loader manifest')
    assert(type(record.release)=='string' and #record.release<=64 and record.release:match('^%d+%.%d+%.%d+$'),'unsupported loader version')
    Versions.compare(record.release,record.release)
    assert(type(record.files)=='table','missing loader files')
    local count,seen=0,{}
    for path,sha in pairs(record.files) do
        assert(managed(path) and digest(sha) and not seen[path:lower()],'invalid loader path or digest')
        count=count+1;seen[path:lower()]=true
    end
    assert(count>0 and count<=4095,'invalid loader file count')
    for _,path in ipairs(required) do
        if updater_required or path=='Scripts/main.lua' or path=='Scripts/skieo_repository.dll' or path=='Scripts/skieo_native_terrain.dll' then
            assert(record.files[path],'loader requires a newer installer')
        end
    end
    return record,count
end
Update.validate_record=validate_record
function Update.validate_feed(feed)
    assert(type(feed)=='table' and feed.format=='skieomod-loader-update' and feed.version==1,'unsupported update feed')
    local record=validate_record(feed.loader)
    assert(feed.release==record.release and feed.url==origin..'CustomMap-Mod-'..record.release..'.zip','invalid update URL')
    assert(digest(feed.sha256) and type(feed.size)=='number' and feed.size%1==0 and feed.size>0 and feed.size<=64*1024^2,'invalid update archive')
    assert(feed.minimum_updater==nil or feed.minimum_updater==1,'update requires the latest installer')
    return feed
end
local function equal(a,b)
    if type(a)~=type(b) then return false end
    if type(a)~='table' then return a==b end
    for k,v in pairs(a) do if not equal(v,b[k]) then return false end end
    for k in pairs(b) do if a[k]==nil then return false end end
    return true
end
local function binary_sha(hex)return (hex:gsub('..',function(pair)return string.char(tonumber(pair,16))end))end
local function native_call(symbol)
    assert(directory,'loader path unavailable')
    os.remove(directory..'update_bootstrap.status')
    local bridge=assert(package.loadlib(directory..'skieo_update_bootstrap.dll',symbol))
    bridge()
    local status=read(directory..'update_bootstrap.status',1024)
    assert(status=='ok',status or 'update helper unavailable')
end
local function failed(reason)
    if preparing then pcall(function()preparing:close()end);preparing=nil end
    os.remove(directory..'loader-update.bundle.part')
    busy,callback=false,nil;Update.ready=false;next_check=os.time()+Update.interval
    -- Technical details go to the log, not into a narrow UI card.
    print('[Custom Map] Automatic update: '..tostring(reason))
    Update.message='Unable to update Custom Map.'
end
-- Build a flat, bounded bundle; only the native worker creates target paths.
-- Yield between files so that ZIP processing does not hold up the browser.
function Update.prepare(path,feed,done,schedule)
    local archive=assert(Archive.open(path));local record_name=prefix..'loader-release.json'
    local record_bytes=assert(archive:read(record_name));assert(#record_bytes<=1024*1024,'loader manifest too large')
    local record,count=validate_record(json.decode(record_bytes),true);assert(equal(record,feed.loader),'archive differs from update feed')
    local names,total={},#record_bytes
    for name,entry in pairs(archive.entries) do
        assert(name==record_name or name:sub(1,#prefix)==prefix and record.files[name:sub(#prefix+1)],'unexpected archive member')
        assert(entry.size<=16*1024^2,'loader file too large');total=total+entry.size
    end
    assert(total<=128*1024^2,'expanded loader too large')
    local actual=0;for _ in pairs(archive.entries) do actual=actual+1 end
    assert(actual==count+1,'loader archive file count differs')
    for name in pairs(record.files) do assert(archive.entries[prefix..name],'missing loader file');names[#names+1]=name end
    table.sort(names)
    local obsolete={}
    local old_bytes=read(directory..'../loader-release.json')
    if old_bytes then
        local old=json.decode(old_bytes)
        if old.format=='skieomod-loader' and type(old.files)=='table' then
            for name,sha in pairs(old.files) do if not record.files[name] and managed(name) and digest(sha) then obsolete[#obsolete+1]={name,sha} end end
        end
    end
    assert(count+#obsolete<=4095,'too many obsolete loader files')
    preparing=assert(io.open(directory..'loader-update.bundle.part','wb'))
    assert(preparing:write(string.pack('<c4I4I4I4I4','SKUP',1,count,#obsolete,#record_bytes),record_bytes))
    local index=1
    callback=function()
        local ok,reason=pcall(function()
            local name=names[index]
            if name then
                local bytes=assert(archive:read(prefix..name))
                assert(preparing:write(string.pack('<I2',#name),name,binary_sha(record.files[name]),string.pack('<I4',#bytes),bytes))
                index=index+1;schedule(callback);return
            end
            for _,entry in ipairs(obsolete) do assert(preparing:write(string.pack('<I2',#entry[1]),entry[1],binary_sha(entry[2]))) end
            assert(preparing:close());preparing=nil
            os.remove(directory..'loader-update.bundle');assert(os.rename(directory..'loader-update.bundle.part',directory..'loader-update.bundle'))
            callback=nil;done()
        end)
        if not ok then failed(reason) end
    end
    schedule(callback)
end
local function schedule(fn)
    if type(ExecuteInGameThreadWithDelay)=='function' then ExecuteInGameThreadWithDelay(16,fn)
    else ExecuteWithDelay(16,function()ExecuteInGameThread(fn)end) end
end
local function check()
    busy=true;next_check=os.time()+Update.interval;Update.message='Checking for a mod update…'
    Repository.fetch(origin..'loader-latest.json',1024*1024,nil,function(path,error)
        if not path then failed(error);return end
        local ok,reason=pcall(function()
            local feed=Update.validate_feed(json.decode(assert(read(path))))
            if Versions.compare(feed.release,Update.current)<=0 then
                busy=false;Update.message='Custom Map is up to date.';return
            end
            Update.release=feed.release;Update.message='Downloading update…'
            Repository.fetch(feed.url,feed.size,feed.sha256,function(zip,failure)
                if not zip then failed(failure);return end
                local accepted,why=pcall(function()
                    local input=assert(io.open(zip,'rb'));assert(input:seek('end')==feed.size,'update download size mismatch');input:seek('set',0)
                    local output=assert(io.open(directory..'loader-update.zip','wb'))
                    while true do local block=input:read(65536);if not block then break end;assert(output:write(block)) end
                    input:close();assert(output:close())
                    Update.message='Preparing update…'
                    Update.prepare(directory..'loader-update.zip',feed,function()
                        native_call('skieo_update_begin');started_at=os.time()
                    end,schedule)
                end)
                if not accepted then failed(why) end
            end,function(fraction)Update.message=string.format('Downloading update… %d%%',math.floor(fraction*100))end)
        end)
        if not ok then failed(reason) end
    end)
end
local function menu_idle(runtime)
    return runtime and not runtime.active_api and not runtime.pending_play and not require('loading').active
end
function Update.poll(version,runtime)
    local now=os.time()
    if started_at and now>=next_status then
        next_status=now+1
        local ok,status=pcall(read,directory..'loader-update.status',1024)
        if not ok then failed(status)
        elseif status then
            local phase=status:match('^(%w+) ')
            if phase=='ready' then Update.ready=true;Update.message='Update ready. Restart the game to apply it.'
            elseif phase=='failed' then started_at=nil;failed(status)
            elseif phase=='staging' then Update.message='Preparing update…' end
        end
        if started_at and now-started_at>120 and not Update.ready then started_at=nil;failed('update worker timed out') end
    end
    if version.supported==false and not busy and now>=next_check and menu_idle(runtime) then check() end
    Update.can_restart=Update.ready and menu_idle(runtime) or false
    return Update
end
function Update.restart(runtime,owner)
    assert(Update.can_restart and menu_idle(runtime),'return to the main menu before restarting')
    native_call('skieo_update_restart')
    local library=assert(StaticFindObject('/Script/Engine.Default__KismetSystemLibrary'))
    library:QuitGame(owner,nil,0,false)
end
return Update
