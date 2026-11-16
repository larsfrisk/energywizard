# Bounded hot-water boost controller

`hot_water_control.BoostController` connects the explicit boost/release driver
operation to a bounded lifecycle. It has no engine hook, default configuration,
background worker or cloud fallback. No installation is enabled by this change.
It is separate from `ShadowCycle`; simulation journals cannot authorize commands.

The caller supplies a private atomic journal loader/saver, a stable SHA-256
context identifying the heater/bindings/policy, and an already selected window
(`start`, `end`, `deadline`, epoch seconds). The existing price/deadline planner
can supply that window. Target, observation age, receipt acceptance and maximum
runtime are explicit. The controller does not qualify sensor roles or calculate
headroom, reservations or prices. Those remain caller responsibilities.

Call serially from one exclusive owner, with explicit global shadow, ownership
and permission flags. An eligible start requires fresh temperature and an
independent released-state read. A boost already active at first observation
is external and is never adopted or released. Late starts retain the original
end; no start occurs after the window. Runtime is measured from the command
attempt, not delayed confirmation. Target completion requires a post-attempt
temperature observation. Cancellation, away, guard loss, stale temperature,
window expiry and runtime expiry release an owned boost when readable.

Intent is saved before each transport call. Readback determines state, rather
than a successful method return. Unknown delivery is never retried: pending
starts are observed until confirmed and then stopped if overdue; pending releases
are observed without replay. Unknown boost state prevents writes. A failed save
blocks commands, including cleanup, and requires operator reconciliation.

Restarted plans never start. Restarted active/pending starts can only reconcile
and release, and require the caller to explicitly confirm exclusive ownership
again with the same context. Restarted pending releases never replay. A shadow,
manual, hygiene or ownership change interrupts authority without writing; it
cannot later resume. A backwards clock enters stop-only recovery. Context
mismatch or invalid journal blocks control. There is no automatic journal reset.

This is not a distributed lock or a device-side watchdog. The integration must
provide atomic private storage, exclusive ownership versus Zenai/other controls,
regular ticks, guarded configuration changes and an operator recovery path.
Process downtime or unavailable transport cannot guarantee immediate release.
No real device writes or handover were performed to validate this software step.
