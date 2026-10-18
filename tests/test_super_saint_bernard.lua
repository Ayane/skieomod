package.path='mod/SkiEO-SuperSaintBernard/Scripts/?.lua;mod/SkiEO-CustomMaps/Scripts/?.lua;'..package.path
local M,J=require('survival'),require('json')
local station=require('station')
assert(#station.objects==7,'the starting resort is missing its support buildings')
local scene,ids={},{}
for _,object in ipairs(station.objects) do
    assert(not ids[object.guid.D],'starting resort contains duplicate native IDs')
    ids[object.guid.D]=true;scene[object.id]=object
end
for _,name in ipairs({'SkiPatrolHut','Maintenance'}) do
    local object=assert(scene[name],'starting resort is missing '..name)
    assert(object.kind=='building' and object.class=='/Game/Blueprints/Buildings/BP_'..name..'.BP_'..name..'_C')
    assert(object.hub.D==scene.TicketOffice.hub.D,'support building is outside the resort base hub')
    local dx,dy=object.position_cm[1]-scene.menouve.position_cm[1],object.position_cm[2]-scene.menouve.position_cm[2]
    assert(dx*dx+dy*dy<10000^2,'support building is too far from the base terminal')
end
local function date(year,month,phase)
    local fiscal_year=year-2002-(month<7 and 1 or 0)
    local fiscal_month=(month+5)%12
    return {year=year,month=month,fiscal_year=fiscal_year,months=fiscal_year*12+fiscal_month+(phase or 0),balance=2000000,lift_rides={menouve=0,plan_du_jeu=0}}
end
local balance,expenses=2000000,0
local function pay(cost,_,mandatory)
    if not mandatory and cost>balance then return false end
    balance=balance-cost;expenses=expenses+cost;return true
end
local s=M.new();M.advance(s,date(2003,12),pay)
local rows=M.condition_rows(s.assets.menouve,date(2003,12))
assert(#rows==3 and rows[1].label=='Installation condition' and rows[3].label=='Approval','building information includes redundant annual upkeep or untranslated labels')
local legacy=M.new();legacy.notice='Travaux commandés. La remontée reste arrêtée jusqu’à la réception et au contrôle.'
M.restore(legacy);assert(legacy.notice=='Works ordered. The lift stays closed until completion and inspection.','saved French notices were not migrated')
local next_date=date(2004,12);M.advance(s,next_date,pay)
assert(expenses==60000 and math.abs(s.assets.menouve.condition-61.48)<.001)
local old_condition=s.assets.menouve.condition
M.advance(s,next_date,pay);assert(expenses==60000 and s.assets.menouve.condition==old_condition,'same calendar charged twice')
local other=M.new();other.effort=1;M.advance(other,date(2003,12),pay);M.advance(other,date(2004,12),pay)
assert(other.assets.menouve.condition<s.assets.menouve.condition,'less maintenance did not increase wear')
local reinforced=M.new();reinforced.effort=3;M.advance(reinforced,date(2003,12),pay);M.advance(reinforced,date(2010,12),pay)
assert(reinforced.assets.menouve.condition>45 and M.blocked(reinforced.assets.menouve,date(2011,1),false),'maintenance renewed legal authorization')
assert(M.blocked(reinforced.assets.menouve,date(2009,1),true),'storm did not close lift')
assert(not M.order(s,'menouve','refit',date(2004,12),function() return false end) and not s.assets.menouve.project,'unfunded works were ordered')
-- Early planning can save the winter; a grant requires real committed investment.
local win=M.new();M.advance(win,date(2003,12),pay)
assert(not M.grant(win,date(2009,1),function() error('unearned grant') end))
assert(M.order(win,'menouve','refit',date(2008,6),pay))
assert(not M.grant(win,date(2008,7),function() error('grant too early') end))
local credits=0;assert(M.grant(win,date(2009,1),function(n) credits=credits+n end))
assert(not M.grant(win,date(2009,2),function() error('duplicate grant') end) and credits==500000)
assert(M.order(win,'plan_du_jeu','refit',date(2009,6),pay))
M.advance(win,date(2010,10),pay)
assert(win.assets.menouve.authorized_until==2013 and not win.assets.menouve.project)
assert(not M.order(win,'menouve','refit',date(2010,10),pay),'repeat refit created indefinite authorization')
M.advance(win,date(2010,11),pay)
local final=date(2011,4);final.lift_rides={menouve=20,plan_du_jeu=30}
M.advance(win,final,pay);assert(win.status=='completed' and win.compliant_winter_months>=3)
local closed=M.new();M.advance(closed,date(2003,12),pay)
closed.assets.menouve.authorized_until=2013;closed.assets.plan_du_jeu.authorized_until=2013
closed.effort=3;M.advance(closed,date(2010,11),pay);M.advance(closed,date(2011,4),pay)
assert(closed.status=='failed','a resort closed all winter won without serving any skiers')
local overdraft=M.new();M.advance(overdraft,date(2010,11),pay)
overdraft.assets.menouve.authorized_until=2013;overdraft.assets.plan_du_jeu.authorized_until=2013
overdraft.start_fiscal_year=1;overdraft.rides_in_winter=true;overdraft.last_rides={menouve=0,plan_du_jeu=0}
local bankrupt=date(2011,4);bankrupt.balance=1;bankrupt.lift_rides={menouve=1,plan_du_jeu=1}
M.advance(overdraft,bankrupt,pay);assert(overdraft.status=='failed','victory used the balance before the maintenance debit')
-- Works ordered too late cannot retroactively save a lost winter.
balance=2000000
local late=M.new();M.advance(late,date(2003,12),pay)
assert(M.order(late,'menouve','refit',date(2011,1),pay));assert(M.order(late,'plan_du_jeu','refit',date(2011,1),pay))
M.advance(late,date(2011,4),pay);assert(late.status=='failed')
-- Restoring a saved checkpoint preserves maintenance, projects and the last charge.
local restored=J.decode(J.encode(win));local paid=restored.maintenance_paid
M.advance(restored,date(2011,4),pay);assert(restored.maintenance_paid==paid and restored.status=='completed')
assert(not pcall(M.advance,restored,date(2008,1),pay),'backwards time silently reset the scenario')
local dead=M.new();M.advance(dead,date(2003,12),pay)
local broke=date(2004,3);broke.balance=-1;M.advance(dead,broke,pay);assert(dead.status=='failed')
print('Super Saint-Bernard: wear, real calendar charges, legal expiry, funded works, conditional grant, saved checkpoints and winter survival OK')
