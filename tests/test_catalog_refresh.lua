package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {} end
package.preload.catalog=function() return {} end
package.preload.terrain=function() return {} end
package.preload.loading=function() return {} end
ExecuteInGameThread=function(callback) callback() end
local R=require('runtime')
local time,requests,notifications=1000,0,0
os.time=function() return time end
local completion
R.featured.refresh=function(callback)
    requests=requests+1;R.featured.busy=true;completion=callback;return true
end
R.workshop.refresh=function(callback) callback();return true end
R.refresh=function() end
local function changed() notifications=notifications+1 end
assert(R.refresh_catalog_if_due(changed) and requests==1)
for _=1,100 do assert(not R.refresh_catalog_if_due(changed)) end
assert(requests==1 and notifications==0,'overlapping catalogue requests')
R.featured.busy=false;completion()
assert(notifications==1)
time=1299;assert(not R.refresh_catalog_if_due(changed))
time=1300;R.pending_play={}
assert(not R.refresh_catalog_if_due(changed),'catalogue competed with Play')
R.pending_play=nil;R.workshop.busy=true
assert(not R.refresh_catalog_if_due(changed),'catalogue competed with a download')
R.workshop.busy=false
assert(R.refresh_catalog_if_due(changed) and requests==2)
-- A failed request retains its cached entries and waits the same interval.
R.featured.message='offline';R.featured.busy=false;completion()
time=1599;assert(not R.refresh_catalog_if_due(changed))
time=1600;assert(R.refresh_catalog_if_due(changed) and requests==3)
print('Catalogue refresh: initial check, five-minute interval, no overlap, Play priority and bounded offline retries OK')
