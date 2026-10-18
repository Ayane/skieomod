local file=assert(io.open('mod/SkiEO-CustomMaps/Scripts/main.lua','rb'))
local source=file:read('*a');file:close()
local prefix=assert(source:match('^(.-)local Runtime = require'))
local disabled='/game/ue4ss/Mods/SkiEO-CustomMaps/Scripts/'
local active='/game/Content/Paks/~mods/SkiEO-CustomMaps/Scripts/'
local env={debug={getinfo=function() return {source='main.lua'} end},
 package={path=disabled..'?.lua;'..active..'?.lua;other/?.lua'},
 io={open=function(path)
  if path==active..'main.lua' then return {close=function() end} end
 end}}
assert(load(prefix,'loader-path','t',env))()
assert(env.package.path:sub(1,#active+5)==active..'?.lua',
 'disabled legacy modules took precedence over the active installation')
print('Loader module paths: disabled entry skipped, active ~mods modules preferred')
