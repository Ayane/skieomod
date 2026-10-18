-- Minimal UFunction metadata for fixtures that exercise hook behavior.
local Reflection={next_address=900000}
function Reflection.func(parameters)
    Reflection.next_address=Reflection.next_address+1
    local address=Reflection.next_address
    return {IsValid=function()return true end,GetAddress=function()return address end,
        ForEachProperty=function(_,callback)
            for name,kind in pairs(parameters or {}) do
                callback({GetFName=function()return {ToString=function()return name end}end,
                    GetClass=function()return {GetFName=function()return {ToString=function()return kind end}end}end})
            end
        end}
end
return Reflection
