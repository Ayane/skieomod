-- Pure geometry for the service descent and authored emergency exits.
local Routes={}
local function finite(n)return type(n)=='number'and n==n and math.abs(n)<1e7 end
local function length(a,b)return math.sqrt((a.x-b.x)^2+(a.y-b.y)^2+(a.z-b.z)^2)end
function Routes.validate(d)
    local exits=d.evacuation_routes
    if exits==nil then return end
    assert(type(exits)=='table'and #exits<=16,'At most 16 emergency routes per lift')
    local count=0
    for _,path in ipairs(exits)do
        assert(type(path)=='table'and #path>=2 and #path<=128,'Emergency routes need 2..128 points')
        count=count+#path;assert(count<=1024,'Emergency route point budget exceeded')
        for _,p in ipairs(path)do
            assert(type(p)=='table'and finite(p[1])and finite(p[2])and finite(p[3]),'Invalid emergency route point')
        end
    end
end
function Routes.dimensions(d)
    d=d or{}
    return(d.service_width_m or 5)*100,(d.service_offset_m or 3.5)*100
end
function Routes.service(route,d)
    local _,offset=Routes.dimensions(d);local points={}
    for i=#route.points,1,-1 do
        local p=route.points[i]
        if i==#route.points or i==1 or p.node~=route.points[i+1].node or i%15==1 then
            local x,y=p.x-p.nx*offset,p.y-p.ny*offset
            points[#points+1]={x=x,y=y,z=route.ground and assert(route.ground(x,y),'Service corridor is outside terrain')or p.z,distance=p.distance}
        end
    end
    return points
end
function Routes.curves(points,width)
    local curves={}
    local function point(p)return{X=p.x,Y=p.y,Z=p.z}end
    local previous=point(points[1])
    for i=2,#points do
        local next_point=point(points[i])
        if length(points[i-1],points[i])>.01 then
            curves[#curves+1]={StartPoint=previous,Endpoint=next_point,CorridorWidth=width,
                ControlPoint={X=(previous.X+next_point.X)*.5,Y=(previous.Y+next_point.Y)*.5,Z=(previous.Z+next_point.Z)*.5}}
            previous=next_point
        end
    end
    assert(#curves>0,'Empty service route');return curves
end
function Routes.build(route,d,ground,service_route,service_definition)
    Routes.validate(d)
    local G=require('surface_lift_geometry');local service=Routes.service(service_route or route,service_definition or d)
    local choices={{index=0,entry=0,length=0,points=service}}
    local _,offset=Routes.dimensions(d)
    for index,path in ipairs(d.evacuation_routes or{})do
        local distance=G.nearest(route,path[1][1],path[1][2]);local p=G.sample(route,distance)
        local entry={x=p.x-p.nx*offset,y=p.y-p.ny*offset,z=p.z,distance=distance}
        entry.z=assert(ground(entry.x,entry.y),'Emergency entrance is outside terrain')
        assert((entry.x-path[1][1])^2+(entry.y-path[1][2])^2<=1000^2,'Emergency route must start within 10 m of its service corridor')
        local points={}
        for _,v in ipairs(service)do if v.distance>distance+.01 then points[#points+1]=v end end
        points[#points+1]=entry
        local cost=0;local previous=entry
        for _,v in ipairs(path)do
            local z=assert(ground(v[1],v[2]),'Emergency route is outside the terrain')
            local next_point={x=v[1],y=v[2],z=z}
            -- Surveyed forest traverses have small bumps in the source DEM.
            -- They still need a lower exit and no substantial uphill section.
            assert(z<=previous.z+500,'Emergency route must descend (maximum 5 m local rise)')
            local step=length(previous,next_point)
            if step>1 then points[#points+1]=next_point;cost=cost+step;previous=next_point end
        end
        assert(cost>=100 and previous.z<entry.z,'Emergency route needs a lower safe exit')
        choices[#choices+1]={index=index,entry=distance,length=cost,points=points}
    end
    return choices
end
function Routes.choose(choices,distance)
    local selected,best=choices[1],distance
    for i=2,#choices do
        local route=choices[i]
        if route.entry<=distance+.01 then
            local cost=distance-route.entry+route.length
            if cost<=best+.01 then selected,best=route,cost end
        end
    end
    return selected,best
end
function Routes.near(points,x,y,radius)
    for i=2,#points do
        local a,b=points[i-1],points[i];local dx,dy=b.x-a.x,b.y-a.y
        local t=math.max(0,math.min(1,((x-a.x)*dx+(y-a.y)*dy)/math.max(.01,dx*dx+dy*dy)))
        if(x-a.x-t*dx)^2+(y-a.y-t*dy)^2<radius^2 then return true end
    end
    return false
end
return Routes
