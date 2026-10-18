-- Authoring assumptions, not recovered historical lending contracts.
-- Nominal annual rates are converted to monthly rates by the scenario host.
local Finance={}
Finance.loans={
    Small={name='Working capital',income_days=1.5,annual_rate=0.06,months=24},
    Medium={name='Safety upgrades',income_days=4,annual_rate=0.05,months=60},
    Large={name='Infrastructure loan',income_days=8,annual_rate=0.045,months=120},
}
return Finance
