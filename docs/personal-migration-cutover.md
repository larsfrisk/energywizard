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
remain necessary after a crash. Verified standby does not qualify module balancing.

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
   obligations are accounted for. Native Ferroamp does not yet establish a true
   solar hold or supply native module SOCs for balancing. Do not silently remove
   those obligations or stop a still-required meter feed.

## Rollback

Stop new EW schedules and reconcile in-flight requests. Confirm NIBE release and
Ferroamp default release **before** restoring Zenai. Preserve uncertain journals;
fail closed rather than clearing them or starting both writers. Revoke scoped
flags, restore exact prior config/image, then verify the old writer and meter.
Restoring a file is not proof that a native forced command was released.

This PR executes no physical commissioning, secret/configuration change, source
fencing, deployment or handover. It is one software batch and combined acceptance/
rollback contract, not a declaration of completed physical migration.
