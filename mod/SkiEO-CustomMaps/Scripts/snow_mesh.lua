-- Bound vertex displacement around native terrain pads without adding source
-- detail absent from the collidable mesh. The base triangle plan is immutable.
local Mesh=require('terrain_mesh')
local Snow={}
function Snow.plan(state)
    local base=state.mesh_plan or Mesh.prepare(state)
    local step=state.sample_step
    local fine=step
    while fine*state.spacing_cm>400 and fine>step/16 do fine=fine/2 end
    fine=math.min(fine,base.fine_step)
    while math.ceil(step/fine)^2*(base.refined_count+1024)>524288 and fine<base.fine_step do fine=fine*2 end
    fine=math.min(fine,base.fine_step)
    local plan={columns=base.columns,rows=base.rows,width=base.width,height=base.height,
        fine_step=fine,refined={},refined_count=base.refined_count,added=0,
        maximum_added=math.min(16384,math.floor(524288/math.ceil(step/fine)^2)-base.refined_count)}
    for key in pairs(base.refined)do plan.refined[key]=true end
    return plan
end
function Snow.add_regions(state,plan,regions)
    local changed={};local size=state.sample_step*state.spacing_cm
    for _,region in ipairs(regions)do
        local x0=math.max(1,math.floor((region[1]-region[3]-state.origin_x)/size)+1)
        local x1=math.min(plan.width,math.floor((region[1]+region[3]-state.origin_x)/size)+1)
        local y0=math.max(1,math.floor((region[2]-region[3]-state.origin_y)/size)+1)
        local y1=math.min(plan.height,math.floor((region[2]+region[3]-state.origin_y)/size)+1)
        for y=y0,y1 do for x=x0,x1 do
            local key=(y-1)*plan.width+x
            if not plan.refined[key] and plan.added<plan.maximum_added then
                plan.refined[key]=true;plan.added=plan.added+1;plan.refined_count=plan.refined_count+1
                changed[#changed+1]={x,y}
            end
        end end
    end
    return changed
end
function Snow.sample(state,column,row)
    return Mesh.height_at(state,state.origin_x+column*state.spacing_cm,state.origin_y+row*state.spacing_cm)
end
return Snow
