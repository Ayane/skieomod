package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local qualified=require('supported_game_builds')
local digest,build=next(qualified)
assert(#digest==64 and build.build:match('^%d+$'))
local original_open,original_remove,original_loadlib,original_time=io.open,os.remove,package.loadlib,os.time
local response,calls,now=nil,0,100
io.open=function(path,mode)
    assert(path:match('game_identity%.status$') and mode=='rb')
    if not response then return nil end
    return {read=function(_,limit) assert(limit==256);return response end,close=function()end}
end
os.remove=function(path) assert(path:match('game_identity%.status$'));response=nil;return true end
os.time=function()return now end
package.loadlib=function(path,entry)
    assert(path:match('skieo_repository%.dll$') and entry=='skieo_game_identity')
    return function()calls=calls+1 end
end
local function fresh()package.loaded.game_version=nil;return require('game_version')end
local version=fresh()
assert(version.poll().checking and calls==1)
response='ok '..digest;now=now+1
local known=version.poll()
assert(known.supported and known.build==build.build)
response='ok '..string.rep('0',64);now=now+1
assert(version.poll()==known and calls==1,'executable hashed more than once')
version=fresh();assert(version.poll().checking)
response='ok '..string.rep('0',64);now=now+1
local unknown=version.poll()
assert(unknown.supported==false and unknown.title=='Unsupported game version')
assert(unknown.detail:find(build.build,1,true) and unknown.detail:find('skieomod.emillon.fr',1,true))
version=fresh();assert(version.poll().checking)
now=now+31
assert(version.poll().supported==false and version.poll().title=='Game version could not be verified')
package.loadlib=function()return nil,'missing helper'end
version=fresh();assert(version.poll().supported==false,'missing helper treated as supported')
response='ok '..digest
os.remove=function()return nil,'read-only directory'end
version=fresh();assert(version.poll().supported==false,'stale result reused after failed removal')
for _,bad in ipairs({'ok abc','ok '..digest..' trailing','error: read failed',''})do
    assert(version.classify(bad).supported==false)
end
io.open,os.remove,package.loadlib,os.time=original_open,original_remove,original_loadlib,original_time
print('Game version: qualified/unknown executable, stale result, single worker, timeout and missing helper OK')
