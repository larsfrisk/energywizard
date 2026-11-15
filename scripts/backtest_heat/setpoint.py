"""Backtest: rumsåterkopplingens börvärde (gpm.py Prio 5b) mot det som faktiskt kördes. 1 °C börvärde ger ca 3 °C
framledning (uppmätt), och lägre framledning ger bättre COP. Regeln är densamma som i motorn:
  nära golvet (< golv + 0,4) -> golv + 1; billigt och < max - 0,5 -> högsta; billigt -> golv;
  dyrt och >= golv + 0,5 -> lägsta; annars golv.
Se model.py för modellen och dess begränsningar."""
from model import *          # noqa: F401,F403
import csv

sp={}
for r in csv.reader(open(os.path.join(DIR, 'sp.csv'))):
    from datetime import datetime as _dt
    f=lambda v: float(v) if v not in ('',None) else None
    sp[_dt.fromisoformat(r[0])]=(f(r[1]),f(r[2]),f(r[3]))
K_SUP=3.0          # °C framledning per °C börvärde (uppmätt)
COP_PER_C=0.025    # COP-förbättring per °C lägre framledning
def choose(mode, tin, floor, store_max, s_act=20.0, debt=0.0, lookahead_ok=True):
    if tin < floor + 0.1: return max(21.0, s_act + 1.0)          # golvet: alltid mer värme än förut
    if mode=='CHEAP':
        if tin < store_max: return 23.0 if debt > 0.5 else 22.0      # betala tillbaka / lagra
        return 20.0
    if mode=='EXPENSIVE' and not lookahead_ok: return min(s_act, 20.0)
    if mode=='EXPENSIVE':
        if tin > floor+0.5: return 18.0
        if tin > floor+0.2: return 19.0
        return 20.0
    if mode=='CHEAP':
        return 22.0 if tin < store_max else 20.0
    return 20.0
IDX={x['t']:i for i,x in enumerate(rows)}
NEED_CHEAP_Q=[0]
def cheap_ok(x, hours=12):
    if NEED_CHEAP_Q[0]==0: return True
    i=IDX[x['t']]; t0=x['t']; n=0; j=i+1
    while j<len(rows) and rows[j]['t']-t0<=timedelta(hours=hours):
        n+=rows[j]['mode']=='CHEAP'; j+=1
    return n>=NEED_CHEAP_Q[0]
def run_sp(floor=20.0, store_max=22.0, exp_low=18.0, season_c=12.0, need_cheap_q=0):
    NEED_CHEAP_Q[0]=need_cheap_q
    D=0.0; prev=None; R=defaultdict(lambda: defaultdict(float)); under=0.0; minT=99; n_heat=0
    for x in rows:
        if x['tin'] is None or x['price'] is None or x['t'] not in sp: prev=None; continue
        cf, s_act, f_act = sp[x['t']]
        if prev and x['t']-prev>timedelta(hours=1): D=0.0
        prev=x['t']; m=x['t'].strftime('%Y-%m'); e=el(x); c=cop(x); p=FULL(x['price'])
        R[m]['base_kwh']+=e; R[m]['base_kr']+=e*p
        tsim=x['tin']-D/C
        heating = daymean.get(x['t'].date(),99) < season_c and cf and s_act and not hw(x) and cf > tsim + 3
        if not heating:
            R[m]['new_kwh']+=e; R[m]['new_kr']+=e*p
            # skulden svalnar/återhämtas inte utan värmesäsong; ett svalare hus förlorar mindre
            D-=min(D, UA*(D/C)*0.25)
            continue
        n_heat+=1
        s_new=choose(x['mode'], tsim, floor, store_max, s_act, D, cheap_ok(x))
        if exp_low!=18.0 and s_new==18.0: s_new=exp_low
        sup_act=cf; sup_new=cf+K_SUP*(s_new-s_act)
        q_act=e*c
        span_act=max(0.5, sup_act-x['tin']); span_new=max(0.0, sup_new-tsim)
        q_new=q_act*span_new/span_act
        q_max=P_RUN*0.25/1000*c*(1+COP_PER_C*max(0,sup_act-sup_new))
        q_new=min(q_new, max(q_max, q_act))
        c_new=c*(1+COP_PER_C*(sup_act-sup_new))
        e_new=q_new/c_new if c_new>0 else e
        D+= (q_act-q_new)
        D-= UA*(D/C)*0.25                 # svalare (eller varmare) hus: mindre (mer) förlust
        R[m]['new_kwh']+=e_new; R[m]['new_kr']+=e_new*p
        tsim=x['tin']-D/C
        if tsim<floor and x['tin']>=floor: under+=0.25; minT=min(minT,tsim)
        R[m]['tin_act']+=x['tin']; R[m]['tin_new']+=tsim; R[m]['nq']+=1
    return R,under,(minT if minT<99 else None),D
def report(R):
    t=defaultdict(float)
    print(f"{'Månad':8} {'pump kWh':>8} {'ny kWh':>7} {'sparat kWh':>10} {'sparat kr':>9} {'inne nu':>7} {'inne ny':>7}")
    for m in sorted(R):
        r=R[m]
        for k_,v in r.items(): t[k_]+=v
        if r['nq']:
            print(f"{m:8} {r['base_kwh']:8.0f} {r['new_kwh']:7.0f} {r['base_kwh']-r['new_kwh']:10.0f} {r['base_kr']-r['new_kr']:9.0f} {r['tin_act']/r['nq']:7.1f} {r['tin_new']/r['nq']:7.1f}")
    print(f"{'Totalt':8} {t['base_kwh']:8.0f} {t['new_kwh']:7.0f} {t['base_kwh']-t['new_kwh']:10.0f} {t['base_kr']-t['new_kr']:9.0f}")
    return t



def prio5b(mode, tin, floor, indoor_max, lo, hi):
    if tin < floor + 0.4:
        return floor + 1.0
    if mode == 'CHEAP':
        return hi if tin < indoor_max - 0.5 else floor
    if mode == 'EXPENSIVE' and tin >= floor + 0.5:
        return lo
    return floor


RULE = {}


def choose(mode, tin, floor, store_max, s_act=20.0, debt=0.0, lookahead_ok=True):   # noqa: F811 - ersätter grundregeln
    return prio5b(mode, tin, floor, RULE['max'], RULE['lo'], RULE['hi'])


if __name__ == "__main__":
    print(f"{'variant':44} {'sparat kWh':>10} {'sparat kr':>9} {'h<20':>6} {'min':>6}")
    for name, rule in [("standard 19/23,5 (golv 20, max 22)", dict(lo=19.0, hi=23.5, max=22.0)),
                       ("15-25 (golv 20, max 22)", dict(lo=15.0, hi=25.0, max=22.0)),
                       ("15-23 (golv 20, max 22)", dict(lo=15.0, hi=23.0, max=22.0))]:
        RULE.clear(); RULE.update(rule)
        R, under, minT, D = run_sp(floor=20.0, store_max=21.5)
        tt = defaultdict(float)
        for r in R.values():
            for k_, v in r.items():
                tt[k_] += v
        mt = f"{minT:.1f}" if minT else "-"
        print(f"{name:44} {tt['base_kwh']-tt['new_kwh']:10.0f} {tt['base_kr']-tt['new_kr']:9.0f} {under:6.1f} {mt:>6}")
    RULE.clear(); RULE.update(lo=19.0, hi=23.5, max=22.0)
    R, under, minT, D = run_sp(floor=20.0, store_max=21.5)
    print(); report(R)
    print(f"Under 20 °C på grund av styrningen: {under:.1f} h. Kvar vid slutet: {D:.0f} kWh värme.")
