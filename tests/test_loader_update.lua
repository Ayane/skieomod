package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local json=require('json')
local now=10000;os.time=function()return now end
local requests={}
package.loaded.repository={fetch=function(url,maximum,sha,callback,progress)
    requests[#requests+1]={url=url,maximum=maximum,sha=sha,callback=callback,progress=progress}
end}
package.loaded.loading={active=false}
local U=require('loader_update')
local function copy(value)return json.decode(json.encode(value))end
local record={format='skieomod-loader',version=1,release='1.25.0',files={}}
for _,p in ipairs({'main.lua','entry.lua','skieo_repository.dll','skieo_native_terrain.dll','skieo_updater.exe','skieo_update_bootstrap.dll'}) do record.files['Scripts/'..p]=string.rep('a',64) end
local feed={format='skieomod-loader-update',version=1,release=record.release,loader=record,
    url='https://skieomod.emillon.fr/downloads/CustomMap-Mod-1.25.0.zip',sha256=string.rep('b',64),size=123}
assert(U.validate_feed(feed)==feed)
for _,path in ipairs({'Scripts/../evil.lua','Scripts/config.json','Scripts/arbitrary.exe','.hidden/code.lua','Scripts/CON.lua','/absolute.lua','Scripts/a\\b.lua','Scripts/a.lua.'}) do
    assert(not U.managed(path),path)
    local bad=copy(feed);bad.loader.files[path]=string.rep('a',64);assert(not pcall(U.validate_feed,bad),path)
end
for _,mutation in ipairs({function(f)f.url='https://example.com/evil.zip'end,function(f)f.size=64*1024^2+1 end,
    function(f)f.size=0/0 end,function(f)f.sha256=string.rep('x',64)end,function(f)f.loader.files['Scripts/MAIN.lua']=string.rep('a',64)end,
    function(f)f.minimum_updater=2 end,function(f)f.release='1.26.0'end,function(f)f.loader.release='1.25.0-beta'end}) do
    local bad=copy(feed);mutation(bad);assert(not pcall(U.validate_feed,bad),'unsafe feed accepted')
end
local runtime={}
-- No check on a supported build or while playing/loading; one immediate check at the menu.
U.poll({supported=true},runtime);assert(#requests==0)
runtime.active_api={};U.poll({supported=false},runtime);assert(#requests==0)
runtime.active_api=nil;runtime.pending_play=true;U.poll({supported=false},runtime);assert(#requests==0)
runtime.pending_play=nil;package.loaded.loading.active=true;U.poll({supported=false},runtime);assert(#requests==0)
package.loaded.loading.active=false;U.poll({supported=false},runtime);assert(#requests==1)
for _=1,100 do U.poll({supported=false},runtime)end;assert(#requests==1,'parallel update checks')
requests[1].callback(nil,'offline');assert(U.message=='Unable to update Custom Map.')
now=now+599;U.poll({supported=false},runtime);assert(#requests==1)
now=now+1;U.poll({supported=false},runtime);assert(#requests==2,'periodic retry absent')
local path=os.tmpname();local file=assert(io.open(path,'wb'))
local old=copy(feed);old.release=U.current;old.loader.release=U.current;old.url='https://skieomod.emillon.fr/downloads/CustomMap-Mod-'..U.current..'.zip'
-- Old published feeds do not have the new updater files: no download/downgrade.
old.loader.files['Scripts/entry.lua']=nil;old.loader.files['Scripts/skieo_updater.exe']=nil;old.loader.files['Scripts/skieo_update_bootstrap.dll']=nil
file:write(json.encode(old));file:close();requests[2].callback(path);os.remove(path)
assert(#requests==2 and U.message=='Custom Map is up to date.')
assert(not U.message:find('minute',1,true))
now=now+600;U.poll({supported=false},runtime);assert(#requests==3)
file=assert(io.open(path,'wb'));file:write(json.encode(feed));file:close();requests[3].callback(path);os.remove(path)
assert(#requests==4 and requests[4].url==feed.url and requests[4].sha==feed.sha256 and requests[4].maximum==feed.size)
requests[4].progress(.25);assert(U.message:find('25%%'))
requests[4].callback(nil,'checksum mismatch');assert(not U.ready)
assert(not pcall(U.restart,runtime),'restart without verified prepared update')
print('In-game updates: canonical feed, path/digest/size validation, old-feed compatibility, menu gating, ten-minute retry, no parallel checks or downgrade OK')
-- Bundle staging is incremental and rejects extra/missing/oversized entries
-- before the worker is called. All temporary files live outside the source tree.
local temp=os.tmpname();os.remove(temp)
assert(os.execute('mkdir -p '..string.format('%q',temp..'/Scripts')))
local archive_data={}
local archive={entries={}}
function archive:read(name)return archive_data[name]end
local real_archive=package.loaded.archive
package.loaded.archive={safe_path=real_archive.safe_path,open=function()return archive end}
local env=setmetatable({debug={getinfo=function()return {source='@'..temp..'/Scripts/loader_update.lua'}end}},{__index=_G})
local B=assert(loadfile('mod/SkiEO-CustomMaps/Scripts/loader_update.lua','t',env))()
local prefix='SkiEO-CustomMaps/'
archive_data[prefix..'loader-release.json']=json.encode(record)
archive.entries[prefix..'loader-release.json']={size=#archive_data[prefix..'loader-release.json']}
for name in pairs(record.files) do archive_data[prefix..name]='bytes '..name;archive.entries[prefix..name]={size=#archive_data[prefix..name]} end
local queue,done={},false
B.prepare('fixture.zip',feed,function()done=true end,function(fn)queue[#queue+1]=fn end)
assert(not done and #queue==1,'bundle processing blocks the UI')
while #queue>0 do table.remove(queue,1)()end
assert(done)
local bundled=assert(io.open(temp..'/Scripts/loader-update.bundle','rb'));local bytes=bundled:read('*a');bundled:close()
local magic,version,count,obsolete,length,position=string.unpack('<c4I4I4I4I4',bytes)
assert(magic=='SKUP' and version==1 and count==6 and obsolete==0 and bytes:sub(position,position+length-1)==json.encode(record))
position=position+length
for _=1,count do
    local n;n,position=string.unpack('<I2',bytes,position);local name=bytes:sub(position,position+n-1);position=position+n
    local sha=bytes:sub(position,position+31);position=position+32
    local size;size,position=string.unpack('<I4',bytes,position)
    assert(sha==string.rep(string.char(0xaa),32) and bytes:sub(position,position+size-1)==archive_data[prefix..name]);position=position+size
end
assert(position==#bytes+1)
archive.entries[prefix..'Scripts/settings.json']={size=1}
assert(not pcall(B.prepare,'fixture.zip',feed,function()error('unexpected completion')end,function()end))
archive.entries[prefix..'Scripts/settings.json']=nil
archive.entries[prefix..'Scripts/main.lua'].size=16*1024^2+1
assert(not pcall(B.prepare,'fixture.zip',feed,function()end,function()end))
archive.entries[prefix..'Scripts/main.lua'].size=10
local different=copy(feed);different.loader.files['Scripts/main.lua']=string.rep('c',64)
assert(not pcall(B.prepare,'fixture.zip',different,function()end,function()end))
package.loaded.archive=real_archive
os.remove(temp..'/Scripts/loader-update.bundle');os.remove(temp..'/Scripts/loader-update.bundle.part')
assert(os.execute('rmdir '..string.format('%q',temp..'/Scripts')..' '..string.format('%q',temp)))
print('In-game update bundle: incremental staging, exact manifest, member whitelist, expanded limit and flat binary contents OK')
