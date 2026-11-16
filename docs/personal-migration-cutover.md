# Consolidated personal migration cutover

This batch prepares NIBE hot water and Ferroamp battery ownership together.
It enables neither installation. Site addresses, credentials, native bindings
and trigger history remain in private working notes.

## Control software

The existing `heat_pump.driver` retains room heating, summer mode and its HA
entity. An explicit `heat_pump.hot_water_control.driver: nibe_local` selects an
independent boost-only driver. Its point allowlist is `water_temp`,
`hot_water_boost` and optional `hot_water_mode`. Other setting writes are refused.
A mode binding's `required_value` is read and checked before starting; the driver
does not force another authority's mode.

Both local scopes require separate `live_control_confirmed` and
`exclusive_owner_confirmed` flags. Defaults stay off. Global shadow remains on
for HA, cars, charging, room heating, solar and other integrations. Only the
approved boost-only driver and native Ferroamp battery scope can bypass it.
The dashboard displays the configured exceptions. Simulated commands no longer
reserve real ramp headroom against an approved local writer.

NIBE's explicit `priority_boosts: true` routes existing hot-water On/Off and
hygiene requests through bounded control. Manual On is consumed once until the
override changes; Off releases an owned boost. Hygiene may preempt a future price
window or raise an active target without extending runtime. It takes precedence
over manual Off. Away/electrical guards and temperature freshness still apply.
A temperature reading is not a hygiene-treatment certificate.

`initial_trigger_at` imports an explicitly dated past trigger only for a new
journal. Retained history is never reset from it. Capture final Zenai history
after quiescing that writer. Normal price/deadline scheduling and ambiguous-write
recovery remain in force.

## Distinct battery standby

Zenai's near-zero hold uses a small positive discharge reference. EW's `hold`
allows solar charging; its `idle` means no charge/discharge. Neither capability
is falsely advertised by Ferroamp. Instead, `standby_verified: true` plus an
explicit `standby_reference_w` within `(0, 50]` enables a distinct `standby`.
It also prevents solar charging and consumes the small configured energy amount.

`standby_for_hold: true` explicitly permits this alternative for unsupported
hold/idle requests above reserve. It does not replace a real supported hold.
The optimizer models nonzero standby power/cost and cannot clip its fixed native
reference into fictitious zero power at reserve or under export protection.
Captures bind the power and replay deterministically. Fresh SOC, maximum power,
native release verification and export guards remain required.

Battery `control: styr` and `default_mode_verified` remain prerequisites. Ambiguous
native power/release attempts are latched and reconciled by readback, not replayed
each loop. The latch is in memory; startup release/ownership and operator recovery
remain necessary after a crash. Verified standby alone does not qualify module balancing.

## Independent metering and module maintenance

EW can read the existing direct HA ESPHome P1 integration instead of Zenai's
HTTP bridge. An optional complete-telegram contract handles HA's change-only
cache: unchanged zeros may have old sensor timestamps while the device telegram
timestamp advances. This requires explicit qualification that every configured
role belongs to the same device's complete telegram, not a mix of independent
sources. Missing/unavailable values, wrong units, future timestamps and stale
device or HA frame receipts fail closed. No cache read refreshes the device time.

Example structure (entity IDs are placeholders; do not apply without qualification):

```yaml
power_meter:
  frame_timestamp: sensor.p1_meter_timestamp
  frame_coherent: true
  max_age_s: 30
  entities:
    import_w: sensor.p1_active_import
    export_w: sensor.p1_active_export
    current_l1: sensor.p1_l1_current
    current_l2: sensor.p1_l2_current
    current_l3: sensor.p1_l3_current
```

The timestamp must be DSMR `YYMMDDhhmmssS`/`W` with explicit summer/winter
offset; power must have W/kW units and current A. Optional per-phase power roles
use paired `import_l1_w`/`export_l1_w` (likewise L2/L3). Existing meter behavior
is unchanged without `frame_timestamp`.

Native Ferroamp can independently subscribe to `extapi/data/eso` with
`battery.module_telemetry.enabled: true`, explicit broker `host`/`port` and a
complete `module_ids` list. Optional `username_env`/`password_env` name existing
environment secrets; `tls: true` and optional `tls_ca` enable broker TLS. The
reader never publishes. Retained/duplicate messages do not establish freshness;
missing, invalid, disconnected or older-than-120-second module receipts block
maintenance. Unknown module IDs latch a blocked inventory until restart with a
reviewed configuration. Public snapshots hash module identities.

The existing balance monitor schedules confirmed divergence at the cheapest
feasible window, with ordinary safety priorities retained. Native maintenance
requires the existing verified standby reference plus **both**
`battery.balance.full_charge_verified: true` and
`battery.balance.standby_dwell_verified: true`, alongside enabled balance and
control/ownership gates. These attestations require physical commissioning;
they are not established by receiving telemetry. The temporary target ceiling
applies only to an active scheduled balance decision; daily `max_soc` remains
unchanged. No vendor SOC-limit register is modified.

Standby dwell models its actual small discharge, never a fictitious zero-power
charge at the ceiling. A conservative total drift budget of 0.5% of capacity
limits feasibility. Live completion still requires **every** configured module
to remain freshly at the monitor's target tolerance for the entire dwell;
planner completion alone cannot complete maintenance. Infeasible windows defer
maintenance and retain the ordinary safe plan. Existing balancing status explains
why normal scheduling yields; the existing English/Czech translations apply.

Read-only verification on 2026-11-16 matched the configured source dongle to one
direct HA ESPHome entry, verified kW/A sensor units and advancing DSMR receipts,
and ran the new EW reader against two live ESO modules with publishing blocked.
This proves independent telemetry access, not complete-frame or physical
full-charge/standby qualification. Site bindings remain in private review files.

## One reviewed commissioning session

1. Merge/test the complete batch and obtain its audited immutable **AMD64** image.
   Stage with all live/ownership confirmations off. Preserve room settings,
   shadow, PVC, probes, selectors, traffic and battery cooperation. Use intended
   secret sources without exporting credentials into the repository. Check the
   owner status/API and actual read-only mappings.
2. Back up exact config, history and image pin. Recheck fresh meter/fuse evidence,
   native SOC/limits, mode, boost and source journals. Abort on active balancing,
   uncertain pending work, changed config identity or unknown ownership.
3. Quiesce Zenai's whole command path: Modbus can fall back to MQTT. Its persisted
   `dry_run` overrides configuration, so check both. Disable hot-water writes and
   native workers; check independent recovery jobs. Verify the restarted old
   writer is read-only before enabling EW. Keep source telemetry running if EW's
   grid sensor still depends on Zenai's Homey poller.
4. With explicit real-write approval, test NIBE start/release once through the
   isolated owner. Observe independent state/temperature and release within the
   reviewed test duration; never extend the configured cap. Unknown delivery
   stops the session and preserves the recovery journal.
5. Verify Ferroamp default/release behavior before setting its verification flag.
   With safe SOC and fresh electrical headroom, test bounded low-power charge,
   discharge and the exact reviewed standby reference. Confirm release after
   each, observing mode/reference and actual power separately. An accepted native
   reference is not proof of physical delivery. No device lease is assumed.
6. Only after both pass, retain scoped EW ownership, final trigger history and
   source-derived normal policy in that same session. Keep global shadow for
   unrelated actuators. Observe automatic scheduling and guards; leave Zenai
   read-only. No repeated feature-by-feature approval is needed within the
   specifically approved session and its limits.
7. Retire source services only after independent metering and module-maintenance
   obligations are accounted for. Qualify/apply the independent P1 mapping and
   complete module inventory, and verify full-charge/standby dwell behavior
   before enabling maintenance confirmations. Native standby remains distinct
   from true solar hold. Do not stop a still-required meter feed.

## Rollback

Stop new EW schedules and reconcile in-flight requests. Confirm NIBE release and
Ferroamp default release **before** restoring Zenai. Preserve uncertain journals;
fail closed rather than clearing them or starting both writers. Revoke scoped
flags, restore exact prior config/image, then verify the old writer and meter.
Restoring a file is not proof that a native forced command was released.

This PR executes no physical commissioning, secret/configuration change, source
fencing, deployment or handover. It is one software batch and combined acceptance/
rollback contract, not a declaration of completed physical migration.
