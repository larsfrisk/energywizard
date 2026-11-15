# Explicit tariffs for cooperation comparisons

Migration captures can use different tariff assumptions even when their spot
numbers agree. An optional complete `battery.shadow_plan.tariff_model` supplies
hypothetical full buy/sell prices without changing live tariff settings, billing,
cost reporting or active planning:

```yaml
tariff_model:
  currency: SEK
  spot_includes_vat: false
  buy_spot_factor: 1.25
  buy_extra: 0.4
  sell_positive_spot_factor: 0.95
  sell_negative_spot_factor: 1
  sell_extra: 0.1
```

These are synthetic values, not recommended supplier rates. All seven fields
are required; additional fields, invalid codes, nonfinite numbers and factors
outside 0–10 reject the candidate. Additive amounts may be negative. Currency is
a three-letter uppercase code and must equal EW's configured currency; the
explicit input VAT flag must equal EW's configured spot-input basis. There is no
currency conversion or automatic VAT adjustment. Matching declarations are not
independent feed, tax or invoice qualification.

For input spot `s`, full purchase price is `s * buy_spot_factor + buy_extra`.
Full export revenue is `s * sell_positive_spot_factor + sell_extra` at zero or
positive spot, and uses `sell_negative_spot_factor` at negative spot. All offsets
are in the declared currency per kWh, after the multiplication. Values are
checked for finite results. The model replaces the full tariff calculation for
the hypothetical candidate; it does not add live fees, time-of-use/distribution
charges, fixed-price or HDO rules. Representing time-dependent tariffs requires a
different explicit model; this option does not infer them.

Omitting the option preserves existing calls and prices. The bounded shadow
worker freezes the configuration and the planner rejects active use or a changed
input basis. Snapshots bind the actual full prices and allowlisted model fields
under `input_quality.tariff_model`, alongside optional PV/learning diagnostics.
Existing replay uses these recorded prices without reading current settings.

This is a default-off comparison facility. No installation settings are enabled,
no device commands are authorized, and no deployment is performed. It does not
establish forecast, policy, origin, economic or physical parity. Qualify actual
contract rates and review comparison configuration before collecting new plans.
