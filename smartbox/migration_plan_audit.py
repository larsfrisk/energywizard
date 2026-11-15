"""Offline comparison of recorded planner inputs; no planner/device execution."""
from datetime import datetime, timezone
import hashlib
import math

from plan_snapshot import canonical


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid recorded number")
    return float(value)


def _time(value):
    if not isinstance(value, str):
        raise ValueError("Offset-aware recorded timestamp required")
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() is None:
        raise ValueError("Offset-aware recorded timestamp required")
    return stamp.astimezone(timezone.utc).timestamp()


def _identity(payload, key, versions):
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] not in versions:
        raise ValueError("Unsupported recorded schema")
    body = {k: v for k, v in payload.items() if k != key}
    raw = canonical(body).encode()
    if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != payload.get(key):
        raise ValueError("Invalid recorded identity")


def _rows(rows, time_key):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 192:
        raise ValueError("Recorded horizon must contain 1 to 192 quarters")
    times = [_time(row[time_key]) for row in rows]
    if any(t % 900 != 0 for t in times) or any(b - a != 900 for a, b in zip(times, times[1:])):
        raise ValueError("Recorded quarters must be ordered and consecutive")
    return times


def audit(ew, zenai):
    """Compare allowlisted effective facts from EW and Zenai replay schema 2.

    Identity is integrity only, not authenticity. Zenai detail rows are rounded
    by its serializer; tolerances cover only that documented rounding.
    """
    _identity(ew, "plan_id", {1, 2})
    _identity(zenai, "plan_run_id", {2})
    zi = zenai["inputs"]
    if hashlib.sha256(canonical(zi["config"]).encode()).hexdigest() != zenai.get("config_hash"):
        raise ValueError("Invalid recorded configuration identity")
    slots = ew["inputs"]["slots"]
    details = zenai["output"]["plan_details"]
    hours = details["hours"]
    if _number(details["slot_minutes"]) != 15:
        raise ValueError("Zenai capture must use quarter-hour slots")
    et, zt = _rows(slots, "t"), _rows(hours, "hour_start")
    made, captured = _time(ew["made_at"]), _time(zenai["captured_at"])
    differences = {}

    def compare(name, left, right, tolerance=1e-6):
        if abs(_number(left) - _number(right)) > tolerance:
            differences[name] = differences.get(name, 0) + 1

    compare("planning_origin", made, captured, 0)
    if et != zt:
        differences["horizon"] = 1
    # Never silently trim, resample, fill gaps or align a different horizon.
    if et == zt:
        for slot, hour in zip(slots, hours):
            compare("buy_tariff", slot["buy"], hour["import_cost"], .000050001)
            compare("sell_tariff", slot["sell"], hour["export_rev"], .000050001)
            compare("solar_forecast", slot["solar_kw"], hour["solar_kw"], .005000001)
            compare("total_load_forecast", _number(slot["load_kw"]) + _number(slot["ev_kw"]),
                    _number(hour["load_kw"]) + _number(hour["extra_load_kw"]), .010000001)
    p, a = ew["inputs"]["params"], details["objective_assumptions"]
    cap = _number(p["capacity_kwh"])
    zcap = _number(a["battery_capacity_kwh"])
    if cap <= 0 or zcap <= 0:
        raise ValueError("Positive recorded battery capacity required")
    compare("capacity", cap, zcap)
    compare("initial_energy", p["soc0_kwh"], _number(zi["soc_pct"]) * zcap / 100)
    compare("reserve_energy", p["reserve_kwh"], _number(a["battery_min_soc_pct"]) * zcap / 100)
    compare("maximum_energy", p["max_kwh"], _number(a["battery_max_soc_pct"]) * zcap / 100)
    compare("charge_limit", p["charge_kw"], a["max_charge_kw"])
    compare("discharge_limit", p["discharge_kw"], a["max_discharge_kw"])
    if p.get("charge_efficiency") is None and p.get("discharge_efficiency") is None:
        efficiency = _number(p["eff"])
        if not 0 < efficiency <= 1:
            raise ValueError("Valid recorded round-trip efficiency required")
        charge_eta = discharge_eta = math.sqrt(efficiency)
    else:
        charge_eta, discharge_eta = (_number(p[k]) for k in ("charge_efficiency", "discharge_efficiency"))
        if not all(0 < v <= 1 for v in (charge_eta, discharge_eta)):
            raise ValueError("Valid recorded directional efficiencies required")
    compare("charge_efficiency", charge_eta, a["charge_efficiency"])
    compare("discharge_efficiency", discharge_eta, a["discharge_efficiency"])
    return {"schema": 1, "ew_plan_id": ew["plan_id"], "zenai_plan_id": zenai["plan_run_id"],
            "ew_quarters": len(et), "zenai_quarters": len(zt),
            "selected_inputs_match": not differences, "difference_counts": differences,
            "absolute_tolerances": {"tariff": .000050001, "solar_kw": .005000001,
                                    "total_load_kw": .010000001, "battery": 1e-6, "origin_seconds": 0},
            "partial_first_quarter": made > et[0] or captured > zt[0],
            "adoption_ready": False, "control_ready": False, "economic_comparison_ready": False,
            "limits": ["Integrity is not authenticity or measurement qualification.",
                       "Numeric tariffs do not establish matching currency or AC boundary.",
                       "Total load matching does not establish equivalent controlled-load exclusions.",
                       "Policies, dynamic reserves, charge ceilings, risk/wear/terminal values and command semantics are not compared.",
                       "No plans are executed, scored or classified as equivalent; no savings or hardware claim."]}
