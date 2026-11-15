# Optional Open-Meteo PV comparison model

The migration inventory found Open-Meteo configured in Zenai, while EW uses its
internal weather model. HA exposed daily/near-term Forecast.Solar sensors but no
supported detailed series. A separately opt-in **comparison-only** input lets EW
record candidates using a tilted-panel irradiance model without changing active
planning, the global PV forecast source, or device ownership.

Under the existing `battery.shadow_plan` configuration, optionally add:

```yaml
pv_model:
  enabled: true
  source: open_meteo
  latitude: 50.0
  longitude: 10.0
  tilt_deg: 30
  azimuth_deg: 0
  kwp: 5
  derate: 0.8
```

All numbers above are synthetic examples. Every geometry/nameplate/derating field
must be explicit; no house location or panel defaults are supplied. Enabling it
sends the configured coordinates and geometry to Open-Meteo. No API key is used.
This feature is off by default and does not apply any live configuration.

[Open-Meteo documents](https://open-meteo.com/en/docs#hourly-parameter-definition)
hourly tilted irradiance as a mean over the hour ending at its timestamp. The
adapter therefore maps an endpoint to the preceding hour, uses UTC epoch times,
and conserves that hour's modelled energy when averaging into quarters. Those
quarters do not imply native 15-minute weather resolution. API azimuth uses south
as zero, east as -90 and west as +90; tilt is 0–90 degrees. Do not copy north-based
azimuth values from another model without conversion.

Model watts are `kwp × derate × tilted_irradiance_W_per_m²`. Nameplate kWp and the
explicit aggregate derating fraction approximate PV conversion; this is not an
inverter/clipping, temperature, shading or storage model. It does not reproduce
Zenai's older sun-position approximation exactly and is not claimed to improve
accuracy or savings without recorded evaluation.

The fixed HTTPS endpoint uses bounded response size and connection/read timeouts,
without redirects. The existing comparison worker holds one hourly cache per
geometry. Expired failures never reuse an old forecast; malformed/missing hours
stay gaps and fall back to the existing HA/internal estimate. Explicit zero is
valid. No HA integration refresh or provider fallback is triggered by this adapter.

Candidate snapshots contain model coverage, status and fetch receipt time, never
coordinates or raw API responses. Receipt time is not a provider issue/run time;
it may be later than the candidate's queued origin. Existing learning corrections
and plan style still apply. Snapshots remain hypothetical, with physical/baseline,
origin alignment and economic qualification outstanding. The active planner
rejects this comparison-only input. No deployment or live API query was made
while implementing/testing this feature.
