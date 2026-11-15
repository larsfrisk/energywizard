# Household-load comparison — evaluation stage of #257

This change does not replace a runtime forecast, change control or add a trained
ML model. It validates input signals and provides a causal comparison harness.
Actual installation benchmarking and paired downstream economics remain pending.

At the AC household boundary, positive grid power is import and positive battery
power is charging:

    household = grid + PV - battery_charge
    baseline_target = household - explicitly_excluded_controlled_loads

All inputs are watts at aligned timestamps. PV/excluded loads are nonnegative;
missing readings and inconsistent negative residuals invalidate the interval.
`controlled_w` is an explicit list, not guessed equipment discovery. Subtract only
loads that are separately planned and will be added back to future total demand.
Do not remove heat pump/spa demand if it remains part of the forecast target, or
subtract the same device twice. Incorrect sign/measurement boundaries can invalidate
the comparison. A missing controlled-load measurement is not zero.

Input JSON is an array of local measurements, for example:

```
[{"timestamp":"2026-11-11T00:00:00+01:00","grid_w":2200,"pv_w":0,
  "battery_w":200,"controlled_w":[500]}]
```

Supply actual history, including all sample timestamps, and run:

```
python scripts/evaluate_household_forecast.py samples.json --split 2026-11-11T00:00:00+01:00
```

Inputs are limited to 50 MB. No uploads, live reads, device writes or settings edits
occur. Reconstruct physical UTC quarters with >=90% coverage; hold the left sample
only until the next finite sample within 90 seconds. Longer gaps stay excluded.
Repeated local DST hours retain distinct physical quarter keys.

## Source-dated capture input

Pass `--source-dated` to evaluate a private `contract`/`samples` capture from
[source-evidence export and residual reconstruction](hot-water-residual-load.md):

```text
python scripts/evaluate_household_forecast.py private-source-export.json --source-dated --split 2026-11-11T00:00:00+01:00 --candidate-method recent_trend
```

The CLI reruns the actual source-date/AC-sign/residual validator; it never trusts
precomputed `rows`, supplied quality summaries, or database insertion times as
measurement dates. Existing age/skew/gap/coverage defaults apply, and missing
readings stay gaps. `--allow-receipt` explicitly permits receipt evidence only in
this mode; it never switches local REST to cloud or relabels receipt as source time.

This target excludes dedicated hot-water electricity only. The output retains
that contract and validation counts, and says physical measurement qualification
is not established. EV/other separately planned loads are not silently removed.
Pairing this mode with `--planner-snapshot` is refused: residual load cannot replace
whole-house demand without matching controlled-load exclusions and reservations.
This mode performs forecast-error evaluation only, retains the chronological
minimum-data gates and never enables runtime adoption. Keep both inputs and
prediction output private. The default raw-array input path remains unchanged.

Predeclared minimum evaluation: 672 valid training quarters (one week's worth) and
96 held-out quarters. Prefer multiple representative weeks and seasonal datasets
before drawing conclusions. A frozen weekday/hour p85 profile is clamped 1–6 kW,
with 2.5 kW sparse-key fallback, matching the current baseline's statistical shape.
It is fitted to the reconstructed signal, not a replay of the old import-only
training data or a claim about the exact forecast historically issued by the engine.

Candidate: 50% of that baseline and 50% median of available completed recent-hour
quarters plus matching local quarters yesterday/last week. These supports must
precede the forecast origin; earlier test observations can feed subsequent origins
in the documented rolling evaluation. The candidate falls back to baseline when
support is missing; it does not require a new dependency or model.

The report gives matched-sample MAE/RMSE and predictions. The forecast-error gate is
>=5% relative MAE improvement without increased RMSE. This is only an evaluation
criterion, not permission to enable anything. `adoption_ready` is always false:
paired planner-cost/constraint evaluation on recorded inputs, real household data,
and a reviewed opt-in rollout/reversion decision are still required. A lower MAE
alone does not establish economic improvement.

## Optional near-term trend candidate

Pass `--candidate-method recent_trend` to select a second offline candidate.
The default `median_blend` keeps the existing numerical behavior. Reports identify
the selected method; neither method is selected or adopted automatically.

The trend candidate requires eight contiguous completed physical UTC quarters
immediately before the origin. It compares the last hour's mean with the preceding
hour's mean and anchors to the last completed quarter:

```text
adjustment = 0.35 × (last_hour_mean - preceding_hour_mean)
             + 0.20 × (last_quarter - baseline)
candidate = baseline + adjustment × max(0, 1 - horizon_hours / 4)
```

It clips to 70–135% of the existing baseline and 0.05–25 kW. At four hours or
later it returns the baseline. Missing recent quarters cause baseline fallback;
older samples are not substituted. Before-origin targets also use the baseline.
The baseline and seven-day training/evaluation requirements remain unchanged.

This is inspired by Zenai's bounded near-term activity shaping, not a port of its
ML, seasonal or neighbouring-slot corrections. Here each feature is a reconstructed
quarter; the support window is explicitly two hours. No claim of exact Zenai
equivalence or forecast/economic improvement follows from the formula alone.

In rolling error evaluation, completed test quarters may feed later origins.
In the paired planner evaluation, every horizon feature stays frozen at the one
snapshot origin; future actual load is used only to score the simulated actions.
Repeated DST hours remain separate physical quarters. Qualified signed/excluded
load data and held-out evaluation are still required; EW minute history is not
automatically accepted as that dataset. No runtime forecast, live configuration,
provider access or device ownership changes are made.

## Paired planner cash-flow counterfactual

Optionally pass --planner-snapshot PATH to the same CLI. It validates the snapshot identity and exact planner replay, then freezes both full-horizon forecasts using only quarters completed before that snapshot origin. Both runs share the captured initial SOC, prices, PV, EV and planner settings; simulated realized load comes from the aligned reconstructed measurements. Future actuals never feed any forecast in that horizon.

Only snapshots made exactly at the first quarter boundary are accepted, because the simulator models whole quarters. Export-disabled, non-block EV policies and balancing snapshots are rejected rather than simulated with different constraints. At least 672 completed training quarters and all realized horizon quarters are required. The report includes actions, simulated SOC bounds, ending SOC and energy cash costs in the snapshot price units. It excludes wear/switching charges and terminal energy valuation: a cash delta with different ending SOC is not savings. It does not qualify fuse/comfort behavior or hardware, and adoption_ready remains false. The existing MAE test split and this single planner origin are separate evaluations. No recorded household dataset is bundled; synthetic tests prove invariants, not economic improvement.
