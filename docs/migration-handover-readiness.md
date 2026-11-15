# Zenai → EnergyWizard handover readiness

Evidence checkpoint: 2026-11-15. This records completed software and the remaining
installation work; it does not authorize configuration changes or real commands.
Issues [#407](https://github.com/murre87/energywizard/issues/407) and
[#257](https://github.com/murre87/energywizard/issues/257) remain open.

## Implemented and verified scope

| Area | Available behavior | Qualification still required |
|---|---|---|
| Battery evidence | Original power/SOC receipt/report provenance reaches comparison input quality; unknown ages remain unknown. | Device freshness, AC boundary and complete module coverage. |
| Cooperation comparisons | Separate hypothetical snapshots, no active-plan writes/dispatch authority, forced-shadow and sample-age guards. | Complete matched-input and physical handover evidence. |
| Battery/tariff assumptions | Explicit comparison-only battery and tariff models, directional efficiencies, recorded spot evidence and replay. | Actual invoice rates, sustainable powers and operational policy review. |
| PV input | Optional Open-Meteo tilted-irradiance model, UTC interval accounting, bounded fetching, coverage/status and fallback. | Accuracy and model/source equivalence; common provider alone does not establish parity. |
| Load forecasting | Existing history learner plus offline median-blend/recent-trend evaluation; dated capture reconstruction can feed the CLI. | Qualified held-out measurements and downstream constraint/economic evaluation. |
| Hot-water scheduling | Deadline/price proposal, dated observations, replayed lifecycle/ownership and explicit residual-load reservations. | Real bounded trigger/release, precedence and measured residual integration. |

See [cooperation comparisons](cooperative-battery-shadow.md),
[recorded-input audit](migration-plan-comparison.md),
[load evaluation](load-forecast-evaluation.md), and
[hot-water handover replay](hot-water-shadow-handover.md).

## Last verified installation evidence

The approved comparison deployment used source `bc5f8be`, with forced shadow and
cooperation retained and Zenai remaining the active writer. Explicit battery and
tariff models were enabled first; PV comparison was subsequently enabled after
separate approval for recurring provider requests and the automatic config restart.
History learning remained off. This is a historical checkpoint, not a current
health monitor or permission to update the deployment.

The resulting private EW/Zenai pair contained 118 quarters each. Both content
identities and Zenai's configuration identity validated. Selected battery
assumptions and full buy/sell tariffs matched within the audit tolerances; all
118 recorded spot values matched numerically. Load differed in all 118 quarters,
PV in 32. Planning origins differed by 780 seconds and the first quarter was
partly elapsed. EW's PV source reported ready with full coverage. These counts
do not establish accuracy, savings, equal measurement boundaries or policy parity.

A read-only history check found about 10.1 days of EW data, but no accepted
weekday/hour load-profile bins or load-bias correction. The learner needs three
observations of a weekday/hour, not merely three calendar days. Its thresholds
were preserved. A separate read-only inventory found 14,679 history rows but zero
source-evidence records, dedicated hot-water electrical-power values or dated
hot-water electrical-power values. The capture schema existed; capture was off.
Old undated rows were not backfilled or treated as qualified measurements.

Private configuration, coordinates, source IDs and raw household series are not
published here. Refer to installation-local reports for a new, time-bound check.

## Evidence needed for the next stage

1. **Qualify the measurement target.** Identify signed grid import/export, PV and
   battery powers at the same AC household boundary; establish polarity, units,
   source dates and synchronization. For the current hot-water-excluded residual
   route, qualify a dedicated hot-water electrical source. Thermal output, total
   compressor power, tank/COP estimates and sensor names do not establish that
   boundary. If that measurement is unavailable, agree a different explicit
   forecast-target/exclusion design rather than assuming a power value.
   A [direct total-load capture target](direct-household-load-evidence.md) is an
   alternative for a battery-only forecast-error experiment if a qualified AC
   household-load signal is available. It includes hot water/EVs, changes no
   runtime forecast, and does not qualify hot-water-excluded reservations.
2. **Collect the declared target without double counting.** Configure source
   capture only after mapping review. Preserve gaps and source contexts. Qualify
   EV/other exclusions separately before adding their reservations to a forecast.
   The current residual tool excludes hot water only. Obtain at least the
   evaluator's seven-day training and one-day held-out coverage; minimum counts
   alone do not qualify a representative dataset.
3. **Evaluate the frozen planning experiment.** Predeclare candidate, target,
   prices, origin, horizon, initial energy, policies and terminal-energy treatment.
   Current paired scoring requires an exact quarter-boundary origin and supported
   policies. Do not trim a partial quarter or invent boundary SOC to bypass it.
   Source-dated hot-water residual input cannot score an ordinary whole-house
   snapshot until reservations and exclusions align. Report ending SOC and
   constraint checks alongside cash flow; cash difference is not measured savings.
4. **Commission the selected hardware transport separately.** Prepare an explicit
   installation-specific test/rollback plan before requesting real writes. Verify
   supported intents, post-send power/readback, timeout/ambiguity, release, restart
   and ownership. Keep one physical writer; never use passing mocks or replay to
   open a verified-control allowlist or remove an opt-in.

For hot water, additionally qualify temperature roles, bounded boost duration and
release/readback, manual/away/hygiene precedence and recovery ownership. Enabled
local REST remains preferred; unavailable local evidence does not authorize cloud
fallback. See [NIBE qualification](nibe-hot-water-qualification.md),
[Ferroamp control boundaries](ferroamp-energyhub.md), and
[source-dated residual reconstruction](hot-water-residual-load.md).

The next live work depends on these installation facts and separately authorized
commissioning. Forecast mismatch by itself is not a reason to copy another
controller's powers, force numerical agreement, relax evidence checks or enable
physical control. Economic, adoption and control readiness remain unqualified.
