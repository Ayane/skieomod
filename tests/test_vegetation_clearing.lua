package.path='mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local Clearing=require('vegetation_clearing')
local points,removed={},{}
local c=Clearing.new(function(i)return points[i][1],points[i][2]end,
    function(slot)assert(not removed[slot],'tree cleared twice');removed[slot]=true end)
local function add(x,y)
    points[#points+1]={x,y};c:add(#points,#points-1,x,y)
    return #points-1
end
local function zone(x,y,r,dx,dy,outline)
    c:enqueue({x=x,y=y,radius=r,dx=dx or 0,dy=dy or 0,outline=outline})
end
local function drain()
    local work=0
    while c:pending()do local _,n=c:step(7);assert(n<=7);work=work+n;assert(work<10000)end
    return work
end
local center=add(-8192,0);local edge=add(-8192+100,0);local outside=add(-8192+101,0)
zone(-8192,0,100);drain()
assert(removed[center]and removed[edge]and not removed[outside],'circle/cell boundary mismatch')
zone(-8192,0,100);assert(drain()==0,'duplicate saved zones repeated spatial work')
local on_line=add(10000,10000);local on_cap=add(10000,9900);local off_line=add(10000,9899)
zone(10000,10000,100,1000,1000);drain()
assert(removed[on_line]and removed[on_cap]and not removed[off_line],'capsule mismatch')
local inside=add(20050,20050);local boundary=add(20000,20000);local off_polygon=add(19999,20000)
zone(20000,20000,0,0,0,{{x=20000,y=20000},{x=20100,y=20000},{x=20100,y=20100},{x=20000,y=20100}})
drain();assert(removed[inside]and removed[boundary]and not removed[off_polygon],'polygon mismatch')
zone(0,0,1e9)
assert(drain()<100,'large clearing iterated empty grid space')
for i=0,#points-1 do assert(removed[i],'large clearing missed tree')end
local empty=Clearing.new(function()error('empty forest queried')end,function()error('empty forest changed')end)
empty:enqueue({x=0,y=0,dx=0,dy=0,radius=1e12});local _,work=empty:step(10)
assert(not empty:pending()and work<10)
print('Portable clearing: circles, capsules, outlines, boundaries, stable slots and bounded work OK')
