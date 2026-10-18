package.path = 'mod/SkiEO-CustomMaps/Scripts/?.lua;' .. package.path
local delayed_id, game_id = 0, 0
local delayed, game = setmetatable({}, {__mode='v'}), setmetatable({}, {__mode='v'})
ExecuteWithDelay=function(ms,callback) assert(ms==100);delayed_id=delayed_id+1;delayed[delayed_id]=callback;return delayed_id end
ExecuteInGameThread=function(callback) game_id=game_id+1;game[game_id]=callback end
CancelDelayedAction=function() end
local Mapping=require('render_mapping')
local missing='error: supported terrain renderer settings were not found'
local calls,done=0,0
local pending=Mapping.install(function()
 calls=calls+1;if calls<3 then return false,missing end;return true,'ok: renderer ready'
end,function(ok,status) assert(ok and status=='ok: renderer ready');done=done+1 end,function() return true end)
for i=1,2 do collectgarbage('collect');assert(delayed[i]);delayed[i]();collectgarbage('collect');assert(game[i]);game[i]() end
assert(calls==3 and done==1 and pending.cancelled)
local failed=0
Mapping.install(function() return false,'error: invalid job' end,function(ok,status) assert(not ok and status=='error: invalid job');failed=failed+1 end)
assert(failed==1,'unsupported layout retried')
delayed,game={},{};delayed_id,game_id=0,0;calls=0
pending=Mapping.install(function() calls=calls+1;return false,missing end,function(ok,status) assert(not ok and status==missing);failed=failed+1 end)
for i=1,39 do delayed[i]();game[i]() end
assert(calls==40 and failed==2,'missing renderer did not stop at retry budget')
delayed,game={},{};delayed_id,game_id=0,0;calls=0
pending=Mapping.install(function() calls=calls+1;return false,missing end,function() error('cancelled mapping completed') end)
local callback=delayed[1];pending:cancel();callback();assert(calls==1 and #game==0)
local current=true
pending=Mapping.install(function() calls=calls+1;return false,missing end,function() error('old world mapping completed') end,function() return current end)
current=false;delayed[#delayed]();game[#game]();assert(calls==2)

local native={}
ExecuteInGameThreadWithDelay=function(ms,callback) assert(ms==100);native[#native+1]=callback;return #native end
calls,done=0,0
local async_before,game_before=delayed_id,game_id
pending=Mapping.install(function()
 calls=calls+1;return calls==3,calls==3 and 'ok: renderer ready' or missing
end,function(ok,status) assert(ok and status=='ok: renderer ready');done=done+1 end)
for i=1,2 do collectgarbage('collect');assert(native[i]);native[i]() end
assert(calls==3 and done==1 and pending.cancelled)
assert(delayed_id==async_before and game_id==game_before,'native timer dispatched to async thread')
print('Render mapping: async registration, callback retention, bounded failure and cancellation OK')
