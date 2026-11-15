# Directional battery efficiency

EW can optionally model charging and discharging losses separately:

```yaml
battery:
  charge_efficiency: 0.9
  discharge_efficiency: 1.0
```

This is an illustrative model, not hardware calibration or a live configuration
change. Both fields must be supplied together as finite fractions greater than
zero and at most one. Missing both preserves the existing model: the square root
of `efficiency` (round-trip) is applied in each direction. A partial or invalid
explicit pair is rejected rather than guessing its missing half.

Charging adds `AC kWh × charge_efficiency` to stored energy. Discharging removes
`AC kWh / discharge_efficiency`. Reserve/ceiling clipping converts stored energy
back to AC power with the appropriate direction's efficiency. Terminal stored
energy is valued with discharge efficiency. Optimizer, its self-consumption
baseline, measured self-use comparison and offline forecast evaluation use the
same selected pair.

The explicit pair takes precedence over `efficiency`, including any learned
round-trip value. Existing learning continues to estimate its round-trip model;
it does not invent or overwrite a directional pair. No new calibration or learning
algorithm is introduced. Capacity/power learning and physical control guards are
unchanged.

Snapshots bind both optional parameters and fingerprint the planner plus its
efficiency helper source before replaying the selected model. The input
audit uses recorded directional values when present, falling back to the legacy
square-root model for older captures. Replay still requires matching planner
code/hash; this does not make old-code snapshots replayable under arbitrary new
code. No schema-version change or raw configuration capture is needed.

Two models can have the same round-trip product while producing different stored
energy and terminal value. For example, 0.9 charging / 1 discharging has the same
0.9 product as sqrt(0.9) in each direction, but equal AC charging produces different
stored energy. Do not treat equal products as matched planner assumptions.

The fields are YAML model settings; no new UI controls or automatic adoption are
added. Live EW/Zenai settings, tariffs, power limits, device permissions and shadow
mode are not changed. This closes one model gap in migration comparison, not
physical handover or economic qualification.
