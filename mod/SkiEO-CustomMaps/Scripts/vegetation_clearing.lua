-- A spatial index over stable renderer slots. Native cleared zones are saved
-- by the game; this queue mirrors them without scanning the forest each frame.
local Clearing = {}
Clearing.__index = Clearing
local CELL = 8192
local function finite(n) return type(n)=='number' and n==n and math.abs(n)<math.huge end
local function key(x,y) return x..':'..y end
local function distance_squared(x,y,ax,ay,bx,by)
    local dx,dy=bx-ax,by-ay
    local length=dx*dx+dy*dy
    local t=length>0 and math.max(0,math.min(1,((x-ax)*dx+(y-ay)*dy)/length)) or 0
    return (x-ax-t*dx)^2+(y-ay-t*dy)^2
end
local function contains(z,x,y)
    if #z.outline<3 then
        return distance_squared(x,y,z.x,z.y,z.x+z.dx,z.y+z.dy)<=z.radius^2
    end
    local inside=false
    local previous=z.outline[#z.outline]
    for _,p in ipairs(z.outline)do
        if distance_squared(x,y,previous.x,previous.y,p.x,p.y)<0.000001 then return true end
        if (p.y>y)~=(previous.y>y) and x<(previous.x-p.x)*(y-p.y)/(previous.y-p.y)+p.x then
            inside=not inside
        end
        previous=p
    end
    return inside
end

function Clearing.new(point_at,remove)
    return setmetatable({point_at=point_at,remove=remove,grid={},cells={},queue={},seen={},head=1,tail=0},Clearing)
end

function Clearing:add(record,slot,x,y)
    local cx,cy=math.floor(x/CELL),math.floor(y/CELL)
    local name=key(cx,cy);local cell=self.grid[name]
    if not cell then
        cell={x=cx,y=cy,entries={}};self.grid[name]=cell;self.cells[#self.cells+1]=cell
    end
    local entries=cell.entries
    entries[#entries+1]=record;entries[#entries+1]=slot
end

function Clearing:enqueue(z)
    for _,name in ipairs({'x','y','dx','dy','radius'})do assert(finite(z[name]),'invalid native clearing '..name)end
    assert(z.radius>=0,'invalid native clearing radius')
    z.outline=z.outline or {}
    local minx,maxx=math.min(z.x,z.x+z.dx)-z.radius,math.max(z.x,z.x+z.dx)+z.radius
    local miny,maxy=math.min(z.y,z.y+z.dy)-z.radius,math.max(z.y,z.y+z.dy)+z.radius
    if #z.outline>=3 then
        minx,maxx,miny,maxy=math.huge,-math.huge,math.huge,-math.huge
        for _,p in ipairs(z.outline)do
            assert(finite(p.x)and finite(p.y),'invalid native clearing outline')
            minx,maxx=math.min(minx,p.x),math.max(maxx,p.x)
            miny,maxy=math.min(miny,p.y),math.max(maxy,p.y)
        end
    end
    -- Native trail reconstruction can append the same corridors on every
    -- restore. Their saved duplicates must not repeat the spatial work.
    local parts={string.pack('<ddddd',z.x,z.y,z.dx,z.dy,z.radius)}
    for _,p in ipairs(z.outline)do parts[#parts+1]=string.pack('<dd',p.x,p.y)end
    local signature=table.concat(parts)
    if self.seen[signature]then return end
    self.seen[signature]=true
    local job={zone=z,minx=math.floor(minx/CELL),maxx=math.floor(maxx/CELL),
        miny=math.floor(miny/CELL),maxy=math.floor(maxy/CELL)}
    job.x,job.y=job.minx,job.miny
    -- A very large clearing visits populated cells, never billions of empty
    -- grid coordinates. Both candidate lookup and removal consume the budget.
    if (job.maxx-job.minx+1)*(job.maxy-job.miny+1)>#self.cells*2 then job.scan=1 end
    self.tail=self.tail+1;self.queue[self.tail]=job
end

function Clearing:pending() return self.head<=self.tail end

function Clearing:step(budget)
    local removed,work=0,0
    while work<budget and self:pending()do
        local job=self.queue[self.head];work=work+1
        if job.cell then
            local entries=job.cell.entries
            if job.index>#entries then job.cell=nil
            else
                local i=job.index;job.index=i+2
                if entries[i+1]~=false then
                    local x,y=self.point_at(entries[i])
                    if contains(job.zone,x,y)then
                        self.remove(entries[i+1],x,y)
                        entries[i+1]=false;removed=removed+1
                    end
                end
            end
        else
            local cell,finished
            if job.scan then
                cell=self.cells[job.scan];job.scan=job.scan+1
                finished=not cell
                if cell and (cell.x<job.minx or cell.x>job.maxx or cell.y<job.miny or cell.y>job.maxy)then cell=nil end
            else
                finished=job.y>job.maxy
                if not finished then
                    cell=self.grid[key(job.x,job.y)]
                    job.x=job.x+1
                    if job.x>job.maxx then job.x=job.minx;job.y=job.y+1 end
                end
            end
            if finished then
                self.queue[self.head]=nil;self.head=self.head+1
            elseif cell then job.cell=cell;job.index=1 end
        end
    end
    if not self:pending()then self.queue={};self.head=1;self.tail=0 end
    return removed,work
end

return Clearing
