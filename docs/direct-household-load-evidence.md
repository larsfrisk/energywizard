# Optional direct AC household-load evidence

A DC-coupled installation may expose PV and battery powers on the DC side while
also exposing a phase-based household-load measurement. Do not combine unmatched
grid/PV/battery boundaries or assume a conversion efficiency to manufacture an AC
measurement. A separate optional capture target records a directly selected total
AC household-load sensor for offline forecast-error evaluation.

```yaml
energy_source_evidence:
  enabled: true
  boundary: ac_household
  target: household_total
  household:
    entity_id: sensor.example_total_ac_load
    positive: consumption
```

This is an example, not an installation mapping. Capture remains off unless
explicitly configured. Qualify the actual signal boundary, phase wiring, sign,
aggregation and timestamp semantics first. The sensor must expose power in W or
kW; values are normalized to nonnegative consumption watts. Negative, missing or
nonfinite readings become missing evidence, never zero. Explicit zero is valid.
HA report/update time is preserved as `ha_report`, not device measurement time.
Sensor names or an integration's label alone do not establish physical correctness.

The existing minute logger stores allowlisted schema-2 JSON in the existing
`energy_source_evidence` column, without entity IDs or raw configuration. A private
mapping/process fingerprint separates source contexts. This route reads only the
already-populated cache, changes no active load estimate, forecast, guard or
device command, and does not query the sensor or cloud. The original component
capture target and schema-1 behavior remain the default.

Export using the explicit matching target:

```text
python scripts/export_energy_source_evidence.py --since 2026-11-01T00:00:00+01:00 --until 2026-11-10T00:00:00+01:00 --target household_total > private-total-load.json
python scripts/evaluate_household_forecast.py private-total-load.json --source-dated --split 2026-11-08T00:00:00+01:00 --candidate-method recent_trend
```

Export retains read-only/two-second DB transactions and the existing 31-day and
100,000-row bounds. Missing, malformed or other-target records remain explicit
gaps. The default export target remains `hot_water_excluded`; it does not silently
accept direct-total records.

The direct contract is `boundary: ac_household`, `signal: household_total`,
`positive: consumption`, `excluded_loads: []`. Each raw sample contains
`timestamp`, `load_w`, `load_sample_at`, `load_basis`, and optionally a source
context. Defaults require source age <=90 seconds, gaps <=90 seconds and >=90%
quarter coverage. The left sample must stay fresh through the interval's end.
Invalid endpoints, context changes and mixed-context quarters are not bridged.
Only measured portions contribute energy; the final sample is not extrapolated.
Receipt-only evidence requires explicit `--allow-receipt` and stays labelled.

This target includes hot water, EVs and other loads. Nothing is subtracted or
reserved; no dedicated hot-water meter is needed for this **total-load** experiment.
It does not make the existing hot-water-excluded route ready or make total demand
interchangeable with EW's EV-excluded baseline. Paired planner-snapshot scoring
remains refused until controlled-load targets/reservations are explicitly aligned.
Output retains the total-load contract, false adoption readiness and unestablished
physical measurement qualification. Seven-day training/held-out requirements still
apply; keep captures and prediction outputs private.

No installation configuration, capture enablement or deployment is performed by
this feature. Choosing an entity and enabling capture remain separately reviewed
installation actions. Physical control/release and full hot-water handover remain
separate qualification gates.
