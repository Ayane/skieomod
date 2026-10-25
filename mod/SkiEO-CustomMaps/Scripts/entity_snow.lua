-- Batched CPU cache access. No GPU readback or Unreal object mutation here.
local Snow={}
local directory=debug.getinfo(1,'S').source:match('^@(.*[/\\])[^/\\]+$')
local loader,cls
function Snow.sample_many(cache,points)
 if #points==0 then return{}end
 assert(#points<=64,'At most 64 snow samples per batch')
 if not directory or type(package.loadlib)~='function'then return{}end
 if loader==nil then loader=package.loadlib(directory..'skieo_native_terrain.dll','skieo_sample_snow')or false end
 if not loader then return{}end
 if not cls or not cls:IsValid()then cls=StaticFindObject('/Script/SkiResortSimulator.SnowStateCache')end
 if not cls or not cls:IsValid()then return{}end
 local rows={string.pack('<c4I4I8I8I4I4','SKSN',2,cache:GetAddress(),cls:GetAddress(),#points,0)}
 for _,p in ipairs(points)do rows[#rows+1]=string.pack('<dd',p.x,p.y)end
 local f=assert(io.open(directory..'native_entity_snow.job','wb'));f:write(table.concat(rows));f:close()
 os.remove(directory..'native_entity_snow.bin');loader()
 f=io.open(directory..'native_entity_snow.bin','rb');if not f then return{}end
 local bytes=f:read('*a');f:close();if #bytes~=#points*16 then return{}end
 local out={}
 for i=1,#points do
  local ready,packed,fresh,spacing=string.unpack('<ffff',bytes,1+(i-1)*16)
  out[i]=ready==1 and{total=packed+fresh,packed=packed,fresh=fresh,spacing=spacing}or false
 end
 return out
end
function Snow.sample(cache,x,y)
 local row=Snow.sample_many(cache,{{x=x,y=y}})[1]
 if row then return row.total,row.spacing,row.packed,row.fresh end
end
return Snow
