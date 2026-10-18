-- Advanced rules used by the visual Configure scenario action.
-- Currency, start year, starting balance and ticket price live in the graph.
local Data,Finance=require('station'),require('finance')
return {costs=Data.costs,class_costs=Data.class_costs,loans=Finance.loans,track_lift_rides=true}
