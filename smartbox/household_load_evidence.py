"""Offline dated direct AC household-load reconstruction; no component mixing."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import math

from hot_water_residual import _epoch,_finite
from load_forecast_evaluation import aggregate

CONTRACT={'boundary':'ac_household','signal':'household_total',
          'positive':'consumption','excluded_loads':[]}


def reconstruct(samples,contract,*,max_age_s=90,max_gap_s=90,min_coverage=.9,allow_receipt=False):
    if contract!=CONTRACT:raise ValueError('Explicit direct AC total-load contract required')
    age,gap,coverage=map(_finite,(max_age_s,max_gap_s,min_coverage))
    if not (0<age<=300 and 0<gap<=300 and 0<coverage<=1) or type(allow_receipt) is not bool:
        raise ValueError('Invalid direct-load reconstruction policy')
    if not isinstance(samples,list) or len(samples)>100000 or any(not isinstance(s,dict) for s in samples):
        raise ValueError('At most 100000 direct measurement rows')
    if any(any(k in s for k in ('controlled_w','hot_water_kw','ev_kw')) for s in samples):
        raise ValueError('Excluded or reserved inputs cannot represent household total')
    ordered=sorted((_epoch(s['timestamp']),i,s) for i,s in enumerate(samples))
    if len({t for t,_,_ in ordered})!=len(ordered):raise ValueError('Duplicate physical timestamp')
    invalid,rejected,bases=Counter(),Counter(),Counter()
    prepared=[]
    for t,_,s in ordered:
        try:
            value,stamp=_finite(s.get('load_w')),_epoch(s.get('load_sample_at'))
            basis=s.get('load_basis');context=s.get('source_context')
            if value<0 or s.get('boundary') not in {None,'ac_household'} or s.get('target') not in {None,'household_total'}:
                raise ValueError('Invalid total-load target')
            if context is not None and (not isinstance(context,str) or len(context)!=64 or any(c not in '0123456789abcdef' for c in context)):
                raise ValueError('Invalid source context')
            if basis not in {'source','ha_report','local_receipt'} or (basis=='local_receipt' and not allow_receipt):
                raise ValueError('Unaccepted timestamp basis')
            if not 0<=t-stamp<=age:raise ValueError('Stale or future source')
            prepared.append((t,value,stamp,context));bases[basis]+=1
        except (ValueError,TypeError,OverflowError):
            invalid['invalid_evidence']+=1;prepared.append((t,None,None,None))
    sums=defaultdict(lambda:[0.,0.]);contexts=defaultdict(set);accepted=0
    for (start,value,stamp,context),(end,next_value,_,next_context) in zip(prepared,prepared[1:]):
        if value is None or next_value is None:rejected['invalid_endpoint']+=1;continue
        if context!=next_context:rejected['source_mapping_changed']+=1;continue
        if end-start>gap:rejected['sample_gap']+=1;continue
        if end-stamp>age:rejected['source_expires_within_interval']+=1;continue
        # Embed the direct load in the existing integrator, without claiming
        # component measurements or subtracting any controlled demand.
        pair=[{'timestamp':datetime.fromtimestamp(t,timezone.utc),'grid_w':v,'pv_w':0,'battery_w':0}
              for t,v in ((start,value),(end,next_value))]
        rows,_=aggregate(pair,min_coverage=1e-12,max_gap_s=gap)
        if any(not math.isfinite(r['kw']) for r in rows):rejected['numeric_overflow']+=1;continue
        for row in rows:
            seconds=row['coverage']*900
            sums[row['t']][0]+=row['kw']*seconds;sums[row['t']][1]+=seconds
            contexts[row['t']].add(context)
        accepted+=1
    mixed={t for t,values in contexts.items() if len(values)>1}
    if mixed:rejected['mixed_source_context_quarters']=len(mixed)
    rows=[{'t':t,'kw':energy/seconds,'coverage':min(1.,seconds/900),'covered_energy_kwh':energy/3600}
          for t,(energy,seconds) in sorted(sums.items()) if t not in mixed and seconds/900+1e-12>=coverage]
    return {'baseline_contract':'household_total','excluded_loads':[],'adoption_ready':False,'rows':rows,
            'report':{'input_samples':len(samples),'invalid_samples':dict(invalid),'accepted_intervals':accepted,
                      'rejected_intervals':dict(rejected),'accepted_quarters':len(rows),'source_bases':dict(bases),
                      'max_age_s':age,'max_gap_s':gap,'minimum_quarter_coverage':coverage,
                      'receipt_evidence_accepted':allow_receipt}}
