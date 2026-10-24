-- Collect snow samples incrementally; publish a whole coherent transport
-- profile only when it is ready. No partially rebuilt spline is exposed.
local G=require('surface_lift_geometry')
local Refresh={}
function Refresh.create(item)
    local job={groups={},queries={},profile={},index=1}
    local function group(name,points,closed)
        job.groups[#job.groups+1]={name=name,points=points,closed=closed}
        for i,p in ipairs(points)do job.queries[#job.queries+1]={p=p,profile=name=='CableSpline'and i or nil}end
    end
    group('CableSpline',G.transport(item.route,function()return 0 end),true)
    for _,name in ipairs({'StartLoopSpline','EndLoopSpline'})do
        local loop=item.splines[name];local points={}
        local terminal=name=='StartLoopSpline'and item.route.points[1]or item.route.points[#item.route.points]
        for _,p in ipairs(loop.points)do
            local x,y=p.X,p.Y
            if item.route.mirror==-1 then
                local nx,ny=-math.sin(terminal.yaw),math.cos(terminal.yaw)
                local side=(x-terminal.x)*nx+(y-terminal.y)*ny
                x=x-2*side*nx;y=y-2*side*ny
            end
            points[#points+1]={X=x,Y=y}
        end
        group(name,points,loop.closed)
    end
    local r=G.sample(item.route,200)
    job.marker={X=r.x+r.nx*160,Y=r.y+r.ny*160}
    job.queries[#job.queries+1]={p=job.marker}
    return job
end
function Refresh.step(job,sample,budget)
    for _=1,budget do
        local q=job.queries[job.index]
        if not q then return true end
        local z,ground=sample(q.p.X,q.p.Y)
        assert(z and ground,'Surface lift transport left the terrain')
        q.p.Z=z+3
        if q.profile then job.profile[q.profile]=z-ground end
        job.index=job.index+1
    end
    return job.index>#job.queries
end
return Refresh
