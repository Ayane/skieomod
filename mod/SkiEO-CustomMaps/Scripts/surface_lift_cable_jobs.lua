-- Small pure-Lua batches and one complete span publication per frame. Static
-- return ropes and station arcs never rebuild when uphill passenger loads move.
local G=require('surface_lift_geometry')
local Jobs={}
function Jobs.step(state,seconds,clock)
 clock=clock or os.clock
 local deadline=clock()+.0015;local tasks={}
 for _,item in ipairs(state.items)do if not item.disposed and item.loads then
  for _,section in ipairs(item.cable_sections or{item})do
   local parts,loads={},{}
   for _,p in ipairs(item.loads)do if not section.range or not p.lo or(p.lo<section.range.high and p.hi>section.range.low)then
    parts[#parts+1]=math.floor(p.distance/10)..':'..math.floor(p.sag/2)
    loads[#loads+1]=p
   end end
   local key=table.concat(parts,';')
   if not section.cable_job and key~=section.cable_key and seconds-(section.cable_updated or -1)>.2 then
    local snapshot={};for i,p in ipairs(loads)do local copy={};for k,v in pairs(p)do copy[k]=v end;snapshot[i]=copy end
    section.cable_job={key=key,thread=coroutine.create(function()
     return G.cable_mesh(item.route,item.supports,snapshot,nil,function()coroutine.yield()end,section.range)
    end)}
   end
   if section.cable_job then tasks[#tasks+1]={item=item,section=section}end
  end
 end end
 local cursor=state.cable_cursor or 0
 for offset=1,#tasks do
  local index=(cursor+offset-1)%#tasks+1;local task=tasks[index]
  local item,section=task.item,task.section;local job=section.cable_job
  repeat
   local ok,mesh=coroutine.resume(job.thread);assert(ok,mesh)
   if coroutine.status(job.thread)=='dead'then
    item.cable_component:CreateMeshSection(section.section or 0,mesh.vertices,mesh.triangles,mesh.normals,mesh.uv,{},{},false)
    section.cable_key=job.key;section.cable_updated=seconds;section.cable_job=nil
    state.cable_cursor=index
    return -- Bound the native mesh conversion/upload as well as Lua geometry.
   end
  until clock()>=deadline
  state.cable_cursor=index
  if clock()>=deadline then return end
 end
end
return Jobs
