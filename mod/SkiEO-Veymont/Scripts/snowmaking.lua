-- Authored native snowmaking coverage; positions are not a historical inventory.
local Snowmaking={}
local function point(curve,t)
 local a,b,c=curve.start,curve.control,curve.finish;local u=1-t
 return{x=u*u*a.X+2*u*t*b.X+t*t*c.X,y=u*u*a.Y+2*u*t*b.Y+t*t*c.Y}
end
function Snowmaking.definitions(data)
 local result={}
 for _,trail in ipairs(data.trails)do if trail.name=='Bruyères'or trail.name=='Faisans'then
  local points={};local length=0
  for _,curve in ipairs(trail.curves)do for i=0,100 do
   local p=point(curve,i/100);local old=points[#points]
   if old then length=length+math.sqrt((p.x-old.x)^2+(p.y-old.y)^2)end
   p.s=length;points[#points+1]=p
  end end
  local index,next_s=0,1500
  for j=2,#points do local p,old=points[j],points[j-1]
   if p.s>=next_s and p.s<length-1000 then
    local dx,dy=p.x-old.x,p.y-old.y;local distance=math.sqrt(dx*dx+dy*dy)
    if distance>0 then
     index=index+1;local nx,ny=-dy/distance,dx/distance
     local side=index%2==0 and 1 or-1
     local offset=(trail.width or 2400)/2+100
     -- Native cone points along +X. Aim across and downhill, retaining the
     -- 90 m native throw; alternating edges cover the whole piste width.
     local ax,ay=dx/distance*3500-nx*side*offset,dy/distance*3500-ny*side*offset
     local key=(trail.name=='Bruyères'and'bruyeres'or'faisans')..'-snowgun-'..index
     result[#result+1]={id=key,kind='snowblower',
      class='/Game/Blueprints/Buildings/BP_Snowblower.BP_Snowblower_C',name=trail.name..' · '..index,
      position_cm={p.x+nx*side*offset,p.y+ny*side*offset},yaw=math.deg(math.atan(ay,ax)),offset_cm=20,
      guid={A=0x5647534E,B=trail.name=='Bruyères'and 1 or 2,C=0,D=index},hub={A=0,B=0,C=0,D=0}}
     next_s=next_s+6500
    end
   end
  end
 end end
 assert(#result>0,'Snowmaking pistes are missing')
 return result
end
function Snowmaking.install(api,data,definitions)
 local saved=api:state()
 if saved.veymont_snowmaking_version==1 then return end
 definitions=definitions or Snowmaking.definitions(data)
 -- One-time save migration. Existing stable IDs are reused; once installed,
 -- native saves own moves, automation changes and player removals.
 local world=require('UEHelpers').GetWorld()
 local seen={}
 for _,gun in ipairs(FindAllOf('SnowblowerActor')or{})do if gun:IsValid()and not gun.bIsPreview and not gun:IsActorBeingDestroyed()and gun:GetWorld():GetAddress()==world:GetAddress()then
  local ok,id=pcall(function()return gun.PlaceableComponent.PlaceableId end)
  if ok then seen[string.format('%08x:%d:%d:%d',id.A,id.B,id.C,id.D)]=true end
 end end
 local missing={};for _,d in ipairs(definitions)do local g=d.guid
  if not seen[string.format('%08x:%d:%d:%d',g.A,g.B,g.C,g.D)]then missing[#missing+1]=d end
 end
 local context=setmetatable({_restoring=false},{__index=api})
 local created=require('scene_objects').place(context,missing)
 for _,gun in ipairs(created)do
  gun:SetTargetDepthCm(60);gun:SetStartBelowTempC(-2);gun:SetAutomationEnabled(true)
 end
 saved.veymont_snowmaking_version=1
 api:log('Veymont snowmaking: '..#created..' native guns added on Les Bruyères and Les Faisans')
end
return Snowmaking
