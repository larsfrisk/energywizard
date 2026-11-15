# Battery plan comparison during cooperation

EW normally builds a battery plan only in control mode. For migration comparison
while Zenai or another controller remains the active writer, an optional path can
record candidate plans without giving EW control:

```yaml
battery:
  enabled: true
  control: samarbete
  plan: true
  capacity_kwh: 20  # use the installation's actual configured usable capacity
  shadow_plan:
    enabled: true
    allowed_intents: [auto, charge, discharge, hold]
```

This is disabled by default. The existing EW shadow-mode setting must also be on.
The example does not change live configuration. `allowed_intents` explicitly
declares a hypothetical planning model; it does not advertise or qualify driver
capabilities. Include `auto` and select only the other intents being compared. Existing capacity, reserve,
ceiling, power, efficiency, tariff and forecast settings still supply the inputs.

The main loop submits its existing SOC reading, normalized battery settings and
load profile at most once per physical quarter. One daemon worker and at most
one waiting sample keep planning away from the control loop. The worker rechecks
shadow mode and rejects samples older than 90 seconds or over five seconds in the
future. Pending samples are replaced by the latest quarter. Failed/dropped work
does not retry in the same quarter and may leave a comparison gap. It is not a
promise to capture every quarter. Configuration changes within a quarter take
effect for the next submitted quarter.

The candidate uses the ordinary EW forecast construction and optimizer, including
their existing fill/fallback behavior and input-quality diagnostics. It does not
infer sustainable charging power from EW's active-plan history in cooperation mode;
it uses the configured/already-loaded learned planning limit by default. An optional
history-learning pass is described below. Balancing requests are excluded because comparison has
no physical ownership. This does not add hot-water reservations or qualify their
baseline exclusions.

## Optional history model

Set `battery.shadow_plan.learn_from_history: true` to let the comparison worker
reuse EW's existing battery/load/PV learning logic without switching EW to control
mode. This is a second opt-in, off by default; no live configuration is changed
by this feature. Without it, the previous comparison behavior is preserved.

Learning runs in a read-only PostgreSQL transaction with a two-second timeout per
statement, on the existing worker. Measured rows must not be later than the frozen
candidate origin; outcome-learning forecasts must also have been recorded by that
origin and their quarters must have completed. Existing active-control callers
without an explicit cutoff retain their current behavior. This is not new model
training logic or qualification of the historical measurement boundary.

The accepted model is cached privately for six hours, invalidated when normalized
primitive settings change or the clock moves backwards. It never populates the
active controller's model. Learning failure or insufficient history keeps the
configured comparison fallback. The attempt is retried after cache expiry or a
settings change. Slow learning cannot block the main loop; queued sample expiry
may mean a snapshot is skipped rather than using an old origin.

Snapshots record `input_quality.learning` with source `ew_history`, state
`learned`, `insufficient` or `unavailable`, and the age of the last attempt. These
are diagnostics, not evidence that a forecast improves economics. Existing model
validation/bounds, fallback, and active-plan/forecast-history non-mutation remain.

Candidate snapshots have `purpose: "cooperative_shadow"` bound into their content
hash. They are saved under `cooperative-shadow/` inside `EW_PLAN_SNAPSHOT_DIR`
(default `/data/planning-snapshots`). The existing owner-only atomic writer and
per-directory retention limits apply. `EW_PLAN_SNAPSHOTS=0` disables these captures
too. The normal planning-snapshot counters include these attempts.

Comparison returns before any active `battery_plan_slots` or
`battery_plan_forecast` writes. Results have no `action_now`/`power_now_w` dispatch
fields and are never assigned to the runtime active plan or measurement plan ID.
No device/driver methods are called by the worker. Cooperation rules and the
existing writer remain unchanged. No candidate becomes authority after restart
or after turning shadow mode off.

Copy a private candidate snapshot and a separately recorded Zenai capture into
the [recorded-input audit](migration-plan-comparison.md). Its readiness flags stay
false: forecasts, timestamps, horizons and policies may still differ. This change
was tested with synthetic inputs and an isolated database; it does not enable live
capture, deploy EW, qualify control, or establish economic/physical equivalence.

## Optional PV comparison input

See [the Open-Meteo PV comparison model](comparison-open-meteo-pv.md) for an
explicit, default-off irradiance input. It does not change active planning.
