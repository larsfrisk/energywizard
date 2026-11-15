"""Explicit directional model, with the unchanged legacy round-trip fallback."""
import math


def resolve(eff, charge_efficiency=None, discharge_efficiency=None):
    if charge_efficiency is None and discharge_efficiency is None:
        eta = math.sqrt(eff)
        return eta, eta
    values = (charge_efficiency, discharge_efficiency)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 < v <= 1 for v in values):
        raise ValueError("Both directional efficiencies must be finite numbers greater than zero and at most one")
    return values
