# Battery operating limits

Settings → Battery planning lets the owner choose a normal charge ceiling and a
margin above the discharge reserve. Changes invalidate the cached plan and apply
to runtime decisions on the next engine iteration. Invalid combinations are
rejected without changing either setting. Both controls have English and Czech
translations.

```yaml
battery:
  reserve_soc: 10
  discharge_buffer_soc: 2
  normal_max_soc: 90
  max_soc: 100
```

This example stops ordinary forced discharge at 12% and controlled charging at
90%. The native Ferroamp driver independently rechecks SOC before sending a
command. A separately verified small standby reference may still be used above
the underlying 10% reserve to prevent uncontrolled charge/discharge. Standby is
not advertised as an exact zero-power idle.

Qualified, explicitly scheduled balancing retains its separate maintenance target
and returns to the ordinary ceiling afterwards. The normal setting does not enable
balancing or remove its qualification flags. Manual top-ups and negative-price
charging remain subject to the normal ceiling and electrical guards.

Without these optional settings, existing installations retain their configured
`max_soc` and have no added reserve margin. Web settings take precedence over YAML.
The ceiling governs EW's requests and planning; inverter-native limits and the
driver's supported intents still apply. An unsupported idle cannot be represented
as a guaranteed physical stop, and export safeguards remain in force.

## Scheduled hot-water load

The active battery planner can include the bounded hot-water owner's future load:

```yaml
battery:
  hot_water_reservations:
    enabled: true
    background_kw: 0.5  # Explicit background model excluding controlled boosts
```

This is disabled by default. Enabling it replaces the old mixed-history load
forecast with a separate background forecast before adding each scheduled boost
once. EV reservations remain separate. Quarter overlaps, partial first quarters,
maximum runtime and confirmed early completion are respected. A schedule change
invalidates the battery plan immediately rather than waiting for the next quarter.

The background profile learns from fresh, explicit **boost-off** observations only,
using the existing household-load boundary and excluding separately planned EV
load. Historical rows with unknown boost state, active boosts or stale receipts
are not reclassified as boost-free. At least three days of sufficiently covered
hourly samples are required; otherwise the explicit `background_kw` model is used.

The configured electrical power is an estimate, not a power cap or a dedicated
hot-water meter. Ordinary heat-pump operation can remain part of the background;
this separation excludes controlled boosts, not all heat-pump energy. Snapshots
retain the background and modelled reservation separately and replay the effective
forecast and battery limits. Measured residual reconstruction remains a separate
contract; this feature does not relabel modelled data as measured energy.
