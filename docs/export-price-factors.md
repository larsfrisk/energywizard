# Export spot-price factors

Settings → Electricity prices and fees supports separate nonnegative factors for
positive and negative export spot prices. Both default to 1, preserving previous
calculations. Values from 0 through 10 are accepted. These are contract settings,
not a recommendation for the user's tariff.

For a spot contract, EW first converts the recorded spot value to the configured
export VAT basis, multiplies that spot component by the factor selected by its
sign, then adds the existing export offset. The offset is never multiplied.

For example, with positive factor 0.95, negative factor 1 and zero offset,
an ex-VAT spot of 2 gives export income 1.90, while -2 remains an export cost
of 2 (income -2). Factor 0 removes only that spot component; a configured offset
still applies. These values illustrate the formula, not current live settings.

Fixed export prices remain `fixed price + offset`; neither factor applies.
Import tariffs, time-of-use and HDO purchases are unchanged. SQL reporting uses
the same piecewise formula as Python/planning, including the VAT conversion.

The settings API fields are `sell_factor` and `sell_negative_factor`. Older clients
that omit them preserve saved factors. Empty values reset the saved override.
Environment fallbacks are `PRICE_SELL_FACTOR` and `PRICE_SELL_NEGATIVE_FACTOR`;
invalid/nonfinite/out-of-range values fall back to 1. API requests reject invalid
values without saving them. English and Czech labels are included.

This closes the representational gap found in the Zenai migration: a constant
export offset alone cannot represent a percentage deduction on positive spot
prices with a different negative-price policy. It does not migrate live tariffs,
approve a contract, reconcile other planner inputs or establish savings.
