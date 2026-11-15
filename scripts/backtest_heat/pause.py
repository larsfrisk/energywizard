"""Backtest: pausa rumsvärmen under dyra timmar när huset har värme att ge av, och betala tillbaka värmeskulden
när det är billigt (eller nära golvet). Varianter med och utan krav på billiga timmar framåt. Se model.py."""
from model import *          # noqa: F401,F403 - rows, el, cop, FULL, hw, UA, C, P_RUN, daymean
idx={x['t']:i for i,x in enumerate(rows)}
def cheap_ahead(i, hours=12):
    t0=rows[i]['t']; n=0; j=i+1
    while j<len(rows) and rows[j]['t']-t0<=timedelta(hours=hours):
        n+= rows[j]['mode']=='CHEAP'; j+=1
    return n
def sim(start=21.0, release=20.3, max_h=4.0, need_cheap_q=0, horizon=12):
    D=0.0; paused=False; ps=None; prev=None; under=0; minT=99; skip=skipkr=extra=extrakr=ph=0.0; base=basekr=0.0
    for i,x in enumerate(rows):
        if x['tin'] is None or x['price'] is None: prev=None; continue
        if prev and x['t']-prev>timedelta(hours=1): D=0.0; paused=False
        prev=x['t']; e=el(x); c=cop(x); p=FULL(x['price']); tsim=x['tin']-D/C; base+=e; basekr+=e*p
        if x['mode']=='EXPENSIVE' and daymean.get(x['t'].date(),99)<12:
            if not paused and tsim>=start and (need_cheap_q==0 or cheap_ahead(i,horizon)>=need_cheap_q): paused=True; ps=x['t']
            if paused and (tsim<=release or (x['t']-ps).total_seconds()/3600>=max_h): paused=False
        else: paused=False
        if paused: ph+=0.25
        if paused and not hw(x) and e>0: D+=e*c; skip+=e; skipkr+=e*p
        D-=min(D, UA*(D/C)*0.25); tsim=x['tin']-D/C
        if not paused and D>0 and (x['mode']=='CHEAP' or tsim<20.2):
            room=(1-x['comp'])*P_RUN*0.25/1000*c; take=min(room,D); D-=take; extra+=take/c; extrakr+=take/c*p
        tsim=x['tin']-D/C
        if D>0.01 and tsim<20 and x['tin']>=20: under+=0.25; minT=min(minT,tsim)
    return ph,skip,skip-extra,skipkr-extrakr,under,(minT if minT<99 else None),D,base,basekr
print(f"{'variant':52} {'paus h':>6} {'flyttat':>7} {'sparat kWh':>10} {'sparat kr':>9} {'h<20':>5} {'min':>5}")
for name,kw in [("utan framåtblick (som förut)",{}),
                ("billigt ≥2 h inom 12 h, släpp 20,5, max 3 h",dict(release=20.5,max_h=3,need_cheap_q=8)),
                ("billigt ≥3 h inom 12 h, släpp 20,5, max 3 h",dict(release=20.5,max_h=3,need_cheap_q=12)),
                ("billigt ≥4 h inom 12 h, start 21,2, släpp 20,6, max 3 h",dict(start=21.2,release=20.6,max_h=3,need_cheap_q=16)),
                ("billigt ≥3 h inom 8 h, start 21,2, släpp 20,6, max 3 h",dict(start=21.2,release=20.6,max_h=3,need_cheap_q=12,horizon=8))]:
    ph,skip,sk,skr,under,minT,D,base,basekr=sim(**kw)
    print(f"{name:52} {ph:6.0f} {skip:7.0f} {sk:10.0f} {skr:9.0f} {under:5.1f} {minT if minT else '-':>5}")
print(f"Pumpens el sedan mars: {base:.0f} kWh, {basekr:.0f} kr")
