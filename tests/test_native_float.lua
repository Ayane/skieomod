package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function()return {}end
local N=require('native_terrain')
local expected=372000.017
local rounded=string.unpack('<f',string.pack('<f',expected))
assert(math.abs(rounded-expected)>0.01,'fixture does not exercise high-altitude float precision')
assert(N.float32_matches(rounded,expected),'valid high-altitude FloatProperty was rejected')
assert(not N.float32_matches(rounded+0.03125,expected),'a changed native altitude was accepted')
assert(N.float32_matches(0,0) and N.float32_matches(476.19049072266,960000/2016))
print('Native terrain floats: binary32 altitude/spacing validation and changed-cache rejection OK')
