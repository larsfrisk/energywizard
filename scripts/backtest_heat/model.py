"""Gemensam modell för värmepumpens backtester (2026-11): husets värmeförlust (UA), tidskonstant (tau) och
värmekapacitet (C) skattas ur loggen, och pumpens el per kvart ur load_breakdown. Data exporteras med export.sh.

    BT_DIR=<katalog med q.csv, pump.csv, sp.csv> python3 pause.py | setpoint.py

Begränsningar: modellen är linjär (en tidskonstant, ingen solinstrålning, ingen tappvarmvatten-dynamik) och
osäker vid extrema börvärden. Använd skillnader mellan varianter, inte absoluta kronor."""
import os
DIR = os.environ.get("BT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
import csv, statistics as st
from datetime import datetime, timedelta
from collections import defaultdict
rows=[]
for r in csv.reader(open(os.path.join(DIR, 'q.csv'))):
    t=datetime.fromisoformat(r[0]); f=lambda x: float(x) if x not in ('',None) else None
    rows.append(dict(t=t,price=f(r[1]),tin=f(r[2]),tout=f(r[3]),comp=f(r[4]) or 0.0,mode=r[5],dww=f(r[6]) or 0.0,cop=f(r[7]),n=int(r[8])))
pump={datetime.fromisoformat(r[0]):float(r[1]) for r in csv.reader(open(os.path.join(DIR, 'pump.csv'))) if r[1]}
# Effekt när kompressorn går (W), ur load_breakdown
runs=[pump[x['t']]/x['comp'] for x in rows if x['t'] in pump and x['comp']>=0.9 and pump[x['t']]>500]
P_RUN=st.median(runs) if runs else 2800.0
FULL=lambda spot: spot*1.25+0.62675           # SE: moms på spot + nätöverföring, skatt, påslag (motorns standard)
def el(x):                                     # kWh el för kvarten
    if x['t'] in pump and pump[x['t']]>0: return pump[x['t']]*0.25/1000
    return x['comp']*P_RUN*0.25/1000
def hw(x): return x['dww']>=1.5 and x['comp']>0  # varmvattenladdning i kvarten (tanken stiger) - pausas aldrig
COP_DEF=3.0
def cop(x): return x['cop'] if x['cop'] and 1.5<x['cop']<6 else COP_DEF
# UA: värmeförlust per grad (kW_th/°C) ur dygn med värmebehov
days=defaultdict(lambda:[0.0,[],[]])
for x in rows:
    if x['tin'] is None or x['tout'] is None: continue
    d=days[x['t'].date()]
    if not hw(x): d[0]+=el(x)*cop(x)
    d[1].append(x['tin']); d[2].append(x['tout'])
ua=[]
for d,(heat,ti,to) in days.items():
    if len(ti)>=90 and st.mean(to)<8:
        dT=st.mean(ti)-st.mean(to)
        if dT>8: ua.append(heat/(24*dT))
UA=st.median(ua)
# Tidskonstant: avsvalning när kompressorn står (minst 2 h i följd)
slopes=[]
i=0
while i<len(rows)-8:
    seg=rows[i:i+8]
    if all(s['comp']==0 and s['tin'] is not None and s['tout'] is not None for s in seg) and (seg[-1]['t']-seg[0]['t'])==timedelta(hours=1,minutes=45) and st.mean([s['tout'] for s in seg])<8:
        dTdt=(seg[-1]['tin']-seg[0]['tin'])/1.75; diff=st.mean([s['tin']-s['tout'] for s in seg])
        if diff>8: slopes.append(-dTdt/diff)
        i+=8
    else: i+=1
k=st.median([s for s in slopes if s>0]) if slopes else 1/40
TAU=1/k; C=UA*TAU
print(f"Modell: P_run={P_RUN:.0f} W, UA={UA:.3f} kW/°C ({len(ua)} dygn), tau={TAU:.1f} h ({len(slopes)} perioder), C={C:.1f} kWh/°C, COP-standard {COP_DEF}")

daymean={}
for d,(heat,ti,to) in days.items():
    if to: daymean[d]=st.mean(to)
