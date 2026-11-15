"""Offline, local-only comparison. Input JSON is never uploaded; no runtime settings change."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'smartbox'))
from load_forecast_evaluation import aggregate,evaluate,evaluate_planner_snapshot

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('samples',help='Local measurement JSON; with --source-dated, a contract/samples capture export')
    p.add_argument('--split',required=True,help='Chronological evaluation start, ISO time with offset')
    p.add_argument('--timezone',default='Europe/Stockholm')
    p.add_argument('--candidate-method',choices=('median_blend','recent_trend'),default='median_blend',
                   help='Offline candidate only; default preserves the existing median blend')
    p.add_argument('--planner-snapshot',type=Path,help='Optional local quarter-boundary planner snapshot for paired cash-flow evaluation')
    p.add_argument('--source-dated',action='store_true',help='Reconstruct a dated AC hot-water-excluded residual before error evaluation')
    p.add_argument('--allow-receipt',action='store_true',help='Explicitly accept receipt dates with --source-dated; never changes transport preference')
    args=p.parse_args()
    if args.allow_receipt and not args.source_dated:p.error('--allow-receipt requires --source-dated')
    if args.source_dated and args.planner_snapshot:
        p.error('Source-dated hot-water-excluded input cannot score a planner snapshot without separately aligned controlled-load reservations')
    path=Path(args.samples)
    if path.stat().st_size>50_000_000:p.error('Input limited to 50 MB')
    if args.source_dated:
        from hot_water_residual import reconstruct
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            residual=reconstruct(data['samples'],data['contract'],allow_receipt=args.allow_receipt)
            rows,coverage=residual['rows'],residual['report']
            result=evaluate(rows,args.split,args.timezone,candidate_method=args.candidate_method)
        except (ValueError,TypeError,KeyError,OverflowError):
            p.error('Invalid or insufficient source-dated load capture; check contract, dates and chronological coverage')
        result['input_contract']={'baseline_contract':residual['baseline_contract'],
                                  'excluded_loads':residual['excluded_loads'],
                                  'measurement_qualification':'not_established'}
    else:
        rows,coverage=aggregate(json.loads(path.read_text()))
        result=evaluate(rows,args.split,args.timezone,candidate_method=args.candidate_method)
    if args.planner_snapshot:
        if args.planner_snapshot.stat().st_size>2_000_000:p.error('Snapshot limited to 2 MB')
        result['economic_evaluation']=evaluate_planner_snapshot(rows,json.loads(args.planner_snapshot.read_text()),args.timezone,candidate_method=args.candidate_method)
    result['coverage']=coverage
    print(json.dumps(result,indent=2))
