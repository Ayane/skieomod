package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local function object() return {IsValid=function() return true end} end
local world,logo=object(),object()
local path='/Game/UI/Brand/T_SkiEOLogo.T_SkiEOLogo'
local loaded,imports,available=0,0,true
StaticFindObject=function(name)
    if name==path and available then return logo end
    if name=='/Script/Engine.Default__KismetRenderingLibrary' then
        return {IsValid=function() return true end,ImportFileAsTexture2D=function(_,context,file)
            assert(context==world)
            local f=assert(io.open(file,'rb'));local data=f:read('*a');f:close()
            assert(data==require('ui_logo'),'fallback PNG was altered')
            local width,height=require('map_presentation').png_header(data)
            assert(width==1000 and height==412)
            imports=imports+1;return logo
        end}
    end
end
LoadAsset=function(name) assert(name==path);loaded=loaded+1;return available and logo or nil end
FindAllOf=function() return {} end
local Assets=require('ui_assets')
assert(Assets.logo(world)==logo and loaded==0 and imports==0,'native texture was not preferred')
available=false
assert(Assets.logo(world)==logo and loaded==1 and imports==1,'supplied PNG fallback was not used')
assert(not io.open('mod/SkiEO-CustomMaps/Scripts/ui-logo.tmp.png','rb'),'logo staging file leaked')
assert(Assets.logo(nil)==nil and imports==1,'logo imported without a valid world')
print('UI logo: native texture priority, lossless supplied PNG fallback and staging cleanup OK')
