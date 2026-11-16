# Personal NIBE migration: read-only commissioning checkpoint

Checked 2026-11-16. This records the personal migration's next concrete step;
it does not authorize writes, deployment, configuration changes or writer handover.
The installation's bindings, addresses, credentials, settings and trigger timestamp
remain in private working notes, outside the repository.

## Verified without actuation

- The running Zenai installation still selects enabled local REST hot-water
  scheduling. Its native alternative is disabled; a previous trigger is recorded.
  No active boost or pending local write was recorded in the read-only inventory.
- Fresh device metadata resolved exactly one boost, demand-mode, BT7 top,
  BT6 charging and system-power candidate point. Discovery and metadata collection
  used two GETs. No cloud fallback or device writes were invoked.
- The actual EW NIBE driver source was then loaded into a separate, temporary
  read-only process at the existing installation. Local authentication remained
  in that process. Its real pinned transport made three GETs and returned usable
  BT7 temperature with local-receipt provenance and a released boost state.
  All actuator methods and non-GET HTTP methods were blocked; zero write attempts
  occurred. Hashes of all three loaded EW source files matched the checkout.
- A separate offline replay of captured metadata validated the configured native
  start and release through the actual driver, with two simulated commands and
  five captured-point reads. No network transport was available in this replay.
  The device's unknown enum bounds were handled by the explicit installation
  allowlist already supported by the driver, not guessed from cloud IDs.
- The current demand mode matched Zenai's configured value at capture time.
  That is an observation, not proof of future mode or ownership.
- The private candidate policy includes deployed source defaults as well as
  explicit settings, including comfort lookahead. Offline demand derivation
  accepted it and preserved the existing trigger timestamp. The candidate keeps
  control, scheduling and exclusive-ownership enablement off and was not applied.

The system-power candidate was not classified as dedicated hot-water electrical
power. The configured planning power remains a model; no reservation is added
against a household baseline that may already contain this load.

## Remaining handover work

The deployed EW installation still uses its existing generic climate driver with
control disabled. Its native hot-water runtime is not enabled. Global shadow and
battery cooperation remain in place, and the configuration hash is unchanged.
Zenai remains the physical writer.

The native boost [transport](nibe-local-rest.md),
[bounded lifecycle](hot-water-control.md),
[runtime and operator recovery](hot-water-control-runtime.md) are software
capabilities. A successful GET or captured replay does not verify physical start,
release, watchdog behavior, electrical timing or safe competing-writer behavior.

Before proposing a live test, preserve the installation's existing room-heating
driver while isolating hot-water ownership, account for the demand-mode setting,
and prepare a specific scoped test plus rollback. Changing the sole heat-pump
driver or disabling global shadow would affect more than the new boost path.
The already working Zenai history/settings should seed that reviewed transition;
do not reset trigger age to the migration time or silently adopt an existing boost.

Exact forecast equality, optional measurement-capture rollout and a long economic
benchmark are not prerequisites for this personal feature handover. The next work
is actuator isolation and commissioning, not additional generic migration tooling.
