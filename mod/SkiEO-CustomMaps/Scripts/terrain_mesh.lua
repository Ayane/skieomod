local Heightmap = require('heightmap')
local Mesh = {}

-- Keep the coarse grid on ordinary slopes. Spend a bounded number of extra
-- cells on cliffs, never on a globally dense second copy of the heightmap.
local MAX_REFINED_CELLS = 16384

local function indices(first, last, step)
    local result = {}
    for index = first, last - 1, step do result[#result + 1] = index end
    result[#result + 1] = last
    return result
end

function Mesh.sampled_indices(length, step)
    return indices(0, length - 1, step)
end

local function height(state, column, row)
    if column % 1 == 0 and row % 1 == 0 then
        return Heightmap.sample_grid_cm(state, column, row)
    end
    return Heightmap.height_at(state, state.origin_x + column * state.spacing_cm,
        state.origin_y + row * state.spacing_cm)
end

local function normal_at(state, column, row, step)
    local x0, x1 = math.max(0, column - step), math.min(state.width - 1, column + step)
    local y0, y1 = math.max(0, row - step), math.min(state.height - 1, row + step)
    local nx = -(height(state, x1, row) - height(state, x0, row))
        / (math.max(1, x1 - x0) * state.spacing_cm)
    local ny = -(height(state, column, y1) - height(state, column, y0))
        / (math.max(1, y1 - y0) * state.spacing_cm)
    local length = math.sqrt(nx * nx + ny * ny + 1)
    return {X=nx / length, Y=ny / length, Z=1 / length}
end

function Mesh.plan(state, step, budget)
    local columns = Mesh.sampled_indices(state.width, step)
    local rows = Mesh.sampled_indices(state.height, step)
    local plan = {columns=columns, rows=rows, width=#columns-1, height=#rows-1,
        fine_step=math.max(1, math.ceil(step / 4)), refined={}, refined_count=0}
    if plan.fine_step >= step then return plan end
    local candidates = {}
    for y = 1, plan.height do
        for x = 1, plan.width do
            local x0, x1, y0, y1 = columns[x], columns[x+1], rows[y], rows[y+1]
            local a, b = height(state,x0,y0), height(state,x0,y1)
            local c, d = height(state,x1,y0), height(state,x1,y1)
            local dx = math.abs((c+d-a-b) / (2 * (x1-x0) * state.spacing_cm))
            local dy = math.abs((b+d-a-c) / (2 * (y1-y0) * state.spacing_cm))
            local slope = math.max(dx,dy)
            if slope > 1 and (x1-x0 > plan.fine_step or y1-y0 > plan.fine_step) then
                candidates[#candidates+1] = {key=(y-1)*plan.width+x, slope=slope}
            end
        end
    end
    -- Refine the steepest cells first if another map exceeds the budget.
    table.sort(candidates, function(a,b)
        if a.slope == b.slope then return a.key < b.key end
        return a.slope > b.slope
    end)
    plan.refined_count = math.min(#candidates, budget or MAX_REFINED_CELLS)
    for index = 1, plan.refined_count do
        plan.refined[candidates[index].key] = true
    end
    return plan
end

local function refined(plan, x, y)
    return plan and x >= 1 and y >= 1 and x <= plan.width and y <= plan.height
        and plan.refined[(y-1)*plan.width+x] or false
end

local function stitched(plan, x, y)
    return refined(plan,x-1,y) or refined(plan,x+1,y)
        or refined(plan,x,y-1) or refined(plan,x,y+1)
end

-- Share the fan perimeter with height queries, including partial last cells.
local function perimeter(plan, x, y, x0, x1, y0, y1)
    local points = {}
    local function edge(xs,ys,reverse)
        local count = math.max(#xs,#ys)
        for i = 1, count-1 do
            local j = reverse and count-i+1 or i
            points[#points+1] = {xs[#xs==1 and 1 or j],ys[#ys==1 and 1 or j]}
        end
    end
    edge({x0},indices(y0,y1,refined(plan,x-1,y) and plan.fine_step or y1-y0))
    edge(indices(x0,x1,refined(plan,x,y+1) and plan.fine_step or x1-x0),{y1})
    edge({x1},indices(y0,y1,refined(plan,x+1,y) and plan.fine_step or y1-y0),true)
    edge(indices(x0,x1,refined(plan,x,y-1) and plan.fine_step or x1-x0),{y0},true)
    return points
end

local function quad_height(state, gx, gy, x0, x1, y0, y1)
    local tx,ty = (gx-x0)/(x1-x0),(gy-y0)/(y1-y0)
    local b,c = height(state,x0,y1),height(state,x1,y0)
    -- The mesh diagonal runs from (x0,y1) to (x1,y0), not bilinearly
    -- through the four corners or through unsampled heightmap vertices.
    if tx+ty <= 1 then
        return height(state,x0,y0)*(1-tx-ty)+b*ty+c*tx
    end
    return c*(1-ty)+b*(1-tx)+height(state,x1,y1)*(tx+ty-1)
end

function Mesh.height_at(state, x, y)
    if type(x)~='number' or type(y)~='number' or x~=x or y~=y then return nil end
    local gx,gy = (x-state.origin_x)/state.spacing_cm,(y-state.origin_y)/state.spacing_cm
    if gx<0 or gy<0 or gx>state.width-1 or gy>state.height-1 then return nil end
    local step = state.sample_step or math.max(1,math.floor(state.runtime.sample_step or 4))
    local ix = math.min(math.floor(gx/step),math.ceil((state.width-1)/step)-1)
    local iy = math.min(math.floor(gy/step),math.ceil((state.height-1)/step)-1)
    local x0,x1 = ix*step,math.min((ix+1)*step,state.width-1)
    local y0,y1 = iy*step,math.min((iy+1)*step,state.height-1)
    local plan = state.mesh_plan
    if refined(plan,ix+1,iy+1) then
        local fine = plan.fine_step
        -- At an outer edge, choose the actual final subdivision start.
        x0 = ix*step+math.min(math.floor((gx-ix*step)/fine),math.ceil((x1-ix*step)/fine)-1)*fine
        y0 = iy*step+math.min(math.floor((gy-iy*step)/fine),math.ceil((y1-iy*step)/fine)-1)*fine
        return quad_height(state,gx,gy,x0,math.min(x0+fine,x1),y0,math.min(y0+fine,y1))
    end
    if stitched(plan,ix+1,iy+1) then
        local cx,cy = (x0+x1)/2,(y0+y1)/2
        local center = height(state,cx,cy)
        local points = perimeter(plan,ix+1,iy+1,x0,x1,y0,y1)
        for i,a in ipairs(points) do
            local b = points[i % #points+1]
            local ax,ay,bx,by = a[1]-cx,a[2]-cy,b[1]-cx,b[2]-cy
            local determinant = ax*by-ay*bx
            local u = ((gx-cx)*by-(gy-cy)*bx)/determinant
            local v = (ax*(gy-cy)-ay*(gx-cx))/determinant
            if u>=-1e-10 and v>=-1e-10 and u+v<=1+1e-10 then
                return center*(1-u-v)+height(state,a[1],a[2])*u+height(state,b[1],b[2])*v
            end
        end
        error('terrain fan does not cover its source cell',0)
    end
    return quad_height(state,gx,gy,x0,x1,y0,y1)
end

function Mesh.build_tile(state, columns, rows, first_x, first_y, quads,
    z_offset_cm, rock_projection, plan)
    local last_x = math.min(#columns, first_x + quads)
    local last_y = math.min(#rows, first_y + quads)
    local uv_tile_cm = math.max(100, (state.runtime.uv_tile_meters or 20) * 100)
    local vertices, triangles, normals, uvs, cache = {}, {}, {}, {}, {}
    local function vertex(column, row)
        local key = row * 2 * (state.width * 2) + column * 2
        if cache[key] then return cache[key] end
        local index = #vertices
        vertices[index+1] = {X=state.origin_x + column * state.spacing_cm,
            Y=state.origin_y + row * state.spacing_cm,
            Z=height(state,column,row) + (z_offset_cm or 0)}
        normals[index+1] = normal_at(state,column,row,plan and 1 or state.sample_step)
        uvs[index+1] = {X=column * state.spacing_cm / uv_tile_cm,
            Y=row * state.spacing_cm / uv_tile_cm}
        cache[key] = index
        return index
    end
    -- Retain the base grid and the legacy ordering, including on flat maps.
    for y = first_y, last_y do
        for x = first_x, last_x do vertex(columns[x],rows[y]) end
    end
    local function triangle(a,b,c)
        triangles[#triangles+1] = a
        triangles[#triangles+1] = b
        triangles[#triangles+1] = c
    end
    local function projected(points, dx, dy)
        if not rock_projection or math.max(dx,dy) <= 1 then return points end
        local result = {}
        for _, index in ipairs(points) do
            local v = vertices[index+1]
            result[#result+1] = #vertices
            vertices[#vertices+1] = v
            normals[#normals+1] = normals[index+1]
            uvs[#uvs+1] = {X=(dx >= dy and (v.Y-state.origin_y)
                or (v.X-state.origin_x)) / uv_tile_cm, Y=v.Z / uv_tile_cm}
        end
        return result
    end
    local function quad(x0,x1,y0,y1)
        local a,b,c,d = vertex(x0,y0),vertex(x0,y1),vertex(x1,y0),vertex(x1,y1)
        local va,vb,vc,vd = vertices[a+1],vertices[b+1],vertices[c+1],vertices[d+1]
        local dx = math.abs((vc.Z+vd.Z-va.Z-vb.Z) / (2*(vc.X-va.X)))
        local dy = math.abs((vb.Z+vd.Z-va.Z-vc.Z) / (2*(vb.Y-va.Y)))
        local p = projected({a,b,c,d},dx,dy)
        triangle(p[1],p[2],p[3]);triangle(p[3],p[2],p[4])
    end
    local function fan(points, column, row)
        local center = vertex(column,row)
        for index = 1, #points do
            local a,b,c = center,points[index],points[index % #points+1]
            local va,vb,vc = vertices[a+1],vertices[b+1],vertices[c+1]
            local ux,uy,uz = vb.X-va.X,vb.Y-va.Y,vb.Z-va.Z
            local vx,vy,vz = vc.X-va.X,vc.Y-va.Y,vc.Z-va.Z
            local nz = ux*vy-uy*vx
            local p = projected({a,b,c},math.abs((uy*vz-uz*vy)/nz),
                math.abs((uz*vx-ux*vz)/nz))
            triangle(p[1],p[2],p[3])
        end
    end
    for y = first_y, last_y-1 do
        for x = first_x, last_x-1 do
            local x0,x1,y0,y1 = columns[x],columns[x+1],rows[y],rows[y+1]
            if refined(plan,x,y) then
                local xs,ys = indices(x0,x1,plan.fine_step),indices(y0,y1,plan.fine_step)
                for iy = 1, #ys-1 do
                    for ix = 1, #xs-1 do quad(xs[ix],xs[ix+1],ys[iy],ys[iy+1]) end
                end
            elseif stitched(plan,x,y) then
                -- Match every fine edge sample, including across sections.
                -- A fan stitches to the coarse interior without T-junctions.
                local points = {}
                for _,point in ipairs(perimeter(plan,x,y,x0,x1,y0,y1)) do
                    points[#points+1] = vertex(point[1],point[2])
                end
                fan(points,(x0+x1)/2,(y0+y1)/2)
            else
                quad(x0,x1,y0,y1)
            end
        end
    end
    return vertices,triangles,normals,uvs
end

return Mesh
