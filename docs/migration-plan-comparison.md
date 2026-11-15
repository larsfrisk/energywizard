# Recorded Zenai/EW input audit

See the [handover readiness checkpoint](migration-handover-readiness.md) for the
implemented scope, last installation evidence and remaining qualification gates.

Before comparing planning outcomes, audit private captures from both systems:

```text
python scripts/audit_migration_plans.py private-ew.json private-zenai.json
```

The command only reads these two local JSON files (at most 2 MB each). It does
not import Zenai, run either planner, access databases/networks, or issue commands.
Output contains capture hashes, counts and code-owned diagnostic labels, not
configuration, endpoints, schedules, prices or household values. Errors are generic.
Keep original captures private even if the audit output is shared.

## Supported recorded formats

EW planning snapshot schema 1 or 2 supplies `plan_id`, `made_at`,
`inputs.slots` and `inputs.params`. Zenai replay schema 2, as produced by
`build_plan_replay_payload` in the reviewed local Zenai source, supplies
`plan_run_id`, `captured_at`, `config_hash`, `inputs.config`, `inputs.soc_pct`,
and `output.plan_details`. The latter must include 15-minute `hours` and explicit
`objective_assumptions`. Missing fields or unsupported versions are rejected;
the tool never reconstructs them from configuration defaults.

Both content hashes and Zenai's config hash are verified. This establishes
internal integrity, not authenticity, source-code identity or physical correctness.
Old EW captures do not need the current planner hash because no replay is executed.

| Selected fact | EW field | Zenai field |
|---|---|---|
| Quarter | `slots[].t` | `hours[].hour_start` |
| Full buy/sell numbers | `buy`, `sell` | `import_cost`, `export_rev` |
| Total forecast load | `load_kw + ev_kw` | `load_kw + extra_load_kw` |
| PV forecast | `solar_kw` | `solar_kw` |
| Capacity, energy bounds, rated powers | `params` | `objective_assumptions` |
| Initial stored energy | `soc0_kwh` | `inputs.soc_pct × capacity / 100` |
| Charge/discharge efficiency | explicit directional pair, otherwise square root of `eff` | separate efficiency assumptions |

The serializer in the reviewed Zenai legacy planner rounds each load component
and PV to two decimals and tariffs to four. Absolute comparison tolerances are
0.010000001 kW for the sum of two load components, 0.005000001 kW for PV,
0.000050001 per tariff, and 0.000001 for battery assumptions. They are returned
with the report. These tolerances can conceal smaller differences; a match means
only that selected recorded numbers are within those tolerances.

Timestamps require explicit offsets and are compared in UTC. Captures must have
ordered, consecutive physical quarters. Different horizons and planning origins
are reported as mismatches; horizons are never silently trimmed, filled or
resampled. A partially elapsed first quarter is separately flagged, since the
two planners may handle its remaining duration differently.

## Remaining comparison gates

### Read-only installation check — 2026-11-15

At 14:03 UTC, 132 consecutive current EW database price quarters were compared
with explicit price intervals from the latest preceding Zenai capture (196 seconds
old). All 132 numbers matched within 1e-9, with no missing intervals. Zenai's
content and configuration hashes validated. Queries used read-only transactions
and two-second statement timeouts; EW remained in shadow mode. No device calls,
configuration updates or deployment occurred. Only the count-based report was
retained locally; no credentials or price series are published here.

This check used current database rows, not EW's original recorded planning inputs:
the deployed capture format did not yet retain `spot`. It therefore establishes
numerical agreement for that inspected price horizon only. It does not verify
currency/VAT basis, supplier fees, invoice correctness, future feeds, matched
forecasts or economic/physical equivalence. Existing final-tariff differences
still need separate configuration reconciliation. A new EW capture after deploying
spot evidence is required for a recorded-plan comparison.

### Recorded spot-price evidence

New EW snapshots retain optional finite `slots[].spot` evidence, the price actually
passed to tariff calculation (including the existing forward-fill behavior).
Older snapshots remain readable and replayable without this field. It does not
change optimization or dispatch. Snapshots still contain private household data.

`spot_price_comparison` compares these numbers with Zenai's recorded
`inputs.prices` entries (`time_start`, `time_end`, `SEK_per_kWh`). One explicit
interval must cover the complete physical quarter. Hourly intervals may cover
four quarters; gaps are never filled or averaged and overlaps are rejected.
Offsets are normalized to UTC, preserving repeated DST hours. Numeric zero and
negative prices are valid. The absolute tolerance is 1e-9 in recorded price units.

The report exposes counts only: `matched` requires full coverage, `different`
means at least one observed difference, and `unavailable` means incomplete
evidence without an observed difference. `complete` separately identifies full
coverage. This diagnostic is separate from `selected_inputs_match`, which still
compares final tariffs and the other documented effective inputs. Currency, VAT
basis and feed identity are not inferred from numeric equality or a field name;
`basis_qualified` is always false. A numeric difference can be caused by different
price bases and is not itself proof that either feed is wrong.

`selected_inputs_match` is an inventory aid, not a parity result. Numeric tariffs
do not establish equal currency or measurement boundary. Equal total load does
not establish identical hot-water/EV exclusions or prevent historical double
counting. Dynamic reserves, daily charge ceilings, initial direction, risk,
wear, terminal value, grid/fuse limits, hygiene/comfort and command semantics
are not compared. Separate upstream/version changes may require a new adapter.

Every report keeps `economic_comparison_ready`, `adoption_ready` and
`control_ready` false. A later paired economic evaluation needs identical qualified
inputs, explicit policy/constraint models and terminal-energy treatment. Hardware
release/ownership and actual bounded hot-water operation remain separate migration
gates. No live captures or economic comparison were performed by the synthetic tests.
