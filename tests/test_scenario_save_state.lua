package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
package.preload.UEHelpers=function() return {FindOrAddFName=function(s) return {ToString=function() return s end} end} end
local J,S=require('json'),require('saves')
local function names(values)
 local array={}
 for _,v in ipairs(values) do array[#array+1]={ToString=function() return v end} end
 array.ForEach=function(self,f) for i,n in ipairs(self) do f(i,{get=function() return n end}) end end
 return array
end
local map={id='community.super-saint-bernard'}
local save={ScenarioData=setmetatable({CompletedObjectives=names({'stock.objective'})},{__newindex=function(self,k,v)rawset(self,k,v)end})}
S.store_state(save,map,{effort=3,condition=32.5,project={due=104,cost=800000},note=string.rep('é',1000)})
local written=save.ScenarioData.CompletedObjectives
assert(#written>3 and written[1]:ToString()=='stock.objective')
written.ForEach=function(self,f) for i,n in ipairs(self) do f(i,{get=function() return n end}) end end
local result=S.read_state(save,map)
assert(result.effort==3 and result.condition==32.5 and result.project.cost==800000 and result.project.due==104)
assert(not pcall(S.read_state,save,{id='test.other'}),'another map reused scenario state')
S.store_state(save,map,{effort=1})
written=save.ScenarioData.CompletedObjectives;assert(#written==2,'old chunks survived overwrite')
written.ForEach=function(self,f)for i,n in ipairs(self)do f(i,{get=function()return n end})end end
assert(S.read_state(save,map).effort==1)
local old={ScenarioData={CompletedObjectives=names({'stock.objective'})}}
assert(S.read_state(old,map)==nil,'stock objectives were decoded as script state')
local corrupted={ScenarioData={CompletedObjectives=names({'SkiEO.ScriptState.v1.002.7b7d'})}}
assert(not pcall(S.read_state,corrupted,map),'a missing save chunk was accepted')
assert(not pcall(S.store_state,old,map,{note=string.rep('x',32768)}),'oversized state was accepted')
print('Script state: per-save native serialization, Unicode chunks, stock objectives, corruption and map isolation OK')
