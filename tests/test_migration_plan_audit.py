"""Synthetic captures in the actual EW/Zenai envelope shapes; no upstream imports."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from migration_plan_audit import audit
import plan_snapshot
from battery_plan import optimize


def seal(payload, key):
    payload.pop(key, None)
    payload[key] = hashlib.sha256(plan_snapshot.canonical(payload).encode()).hexdigest()
    return payload


def captures():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    slots = [dict(t=(now + timedelta(minutes=15*i)).isoformat(), buy=buy, sell=.1,
                  load_kw=1.2, solar_kw=.3, ev_kw=.8) for i, buy in enumerate([-.1, .5, 2])]
    params = dict(soc0_kwh=5, capacity_kwh=10, reserve_kwh=2, max_kwh=9,
                  charge_kw=3, discharge_kw=4, eff=.81, allowed={"auto", "hold", "charge", "discharge"})
    ew = plan_snapshot.build(slots, params, optimize(slots, **params), now)
    config = {"battery": {"secret_extra": "must-not-leak"}}
    zenai = dict(schema_version=2, captured_at=now.isoformat(), app_version="test",
                 config_hash=hashlib.sha256(plan_snapshot.canonical(config).encode()).hexdigest(),
                 inputs=dict(config=config, prices=[], solar_forecast={}, soc_pct=50),
                 output=dict(schedule={}, plan_details=dict(slot_minutes=15,
                     objective_assumptions=dict(battery_capacity_kwh=10, battery_min_soc_pct=20,
                         battery_max_soc_pct=90, max_charge_kw=3, max_discharge_kw=4,
                         charge_efficiency=.9, discharge_efficiency=.9),
                     hours=[dict(hour_start=s["t"], import_cost=s["buy"], export_rev=s["sell"],
                                 solar_kw=.3, load_kw=1.2, extra_load_kw=.8) for s in slots])))
    return ew, seal(zenai, "plan_run_id")


def test_matching_selected_inputs_never_qualify_economics_or_control():
    ew, zenai = captures()
    original = deepcopy((ew, zenai))
    result = audit(ew, zenai)
    assert result["selected_inputs_match"] and result["difference_counts"] == {}
    assert not any(result[k] for k in ("adoption_ready", "control_ready", "economic_comparison_ready", "partial_first_quarter"))
    assert "must-not-leak" not in json.dumps(result)
    assert (ew, zenai) == original


def test_equivalent_offsets_and_serialization_rounding_are_explicit():
    ew, zenai = captures()
    zenai["captured_at"] = "2026-11-14T01:00:00+01:00"
    for row in zenai["output"]["plan_details"]["hours"]:
        row["hour_start"] = datetime.fromisoformat(row["hour_start"]).astimezone(timezone(timedelta(hours=1))).isoformat()
        row["load_kw"] += .0049
        row["extra_load_kw"] += .0049
        row["solar_kw"] += .0049
        row["import_cost"] += .000049
    result = audit(ew, seal(zenai, "plan_run_id"))
    assert result["selected_inputs_match"]
    assert result["absolute_tolerances"]["total_load_kw"] < .011


@pytest.mark.parametrize("field,label", [("import_cost", "buy_tariff"), ("export_rev", "sell_tariff"),
    ("solar_kw", "solar_forecast"), ("extra_load_kw", "total_load_forecast")])
def test_forecast_or_reserved_load_differences_are_counted(field, label):
    ew, zenai = captures()
    zenai["output"]["plan_details"]["hours"][1][field] += .1
    result = audit(ew, seal(zenai, "plan_run_id"))
    assert not result["selected_inputs_match"] and result["difference_counts"] == {label: 1}


@pytest.mark.parametrize("field,label", [("battery_capacity_kwh", "capacity"),
    ("battery_min_soc_pct", "reserve_energy"), ("battery_max_soc_pct", "maximum_energy"),
    ("max_charge_kw", "charge_limit"), ("max_discharge_kw", "discharge_limit"),
    ("charge_efficiency", "charge_efficiency"), ("discharge_efficiency", "discharge_efficiency")])
def test_effective_battery_assumptions_are_not_silently_normalized(field, label):
    ew, zenai = captures()
    zenai["output"]["plan_details"]["objective_assumptions"][field] += .1
    assert label in audit(ew, seal(zenai, "plan_run_id"))["difference_counts"]


def test_different_horizons_are_not_trimmed_and_partial_origins_are_visible():
    ew, zenai = captures()
    zenai["output"]["plan_details"]["hours"].pop()
    zenai["captured_at"] = "2026-11-14T00:02:00Z"
    result = audit(ew, seal(zenai, "plan_run_id"))
    assert result["difference_counts"] == {"planning_origin": 1, "horizon": 1}
    assert result["ew_quarters"] == 3 and result["zenai_quarters"] == 2
    assert result["partial_first_quarter"]


@pytest.mark.parametrize("mode", ["identity", "config_hash", "schema", "duplicate", "gap", "naive", "hourly", "missing_extra", "nan"])
def test_invalid_or_unsupported_recordings_are_rejected(mode):
    ew, zenai = captures()
    details = zenai["output"]["plan_details"]
    if mode == "identity":
        zenai["inputs"]["soc_pct"] = 99
    elif mode == "config_hash":
        zenai["inputs"]["config"]["battery"]["secret_extra"] = "changed"
    elif mode == "schema":
        zenai["schema_version"] = 99
    elif mode in {"duplicate", "gap", "naive"}:
        details["hours"][1]["hour_start"] = {"duplicate": details["hours"][0]["hour_start"],
            "gap": "2026-11-14T01:00:00Z", "naive": "2026-11-14T00:15:00"}[mode]
    elif mode == "hourly":
        details["slot_minutes"] = 60
    elif mode == "missing_extra":
        del details["hours"][0]["extra_load_kw"]
    else:
        details["hours"][0]["load_kw"] = float("nan")
    with pytest.raises((ValueError, KeyError)):
        if mode != "identity":
            seal(zenai, "plan_run_id")
        audit(ew, zenai)


def test_cli_only_reads_captures_and_sanitizes_errors(tmp_path):
    ew, zenai = captures()
    paths = [tmp_path / "ew.json", tmp_path / "zenai.json"]
    for path, payload in zip(paths, (ew, zenai)):
        path.write_text(json.dumps(payload))
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/audit_migration_plans.py"), *map(str, paths)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)["selected_inputs_match"]
    paths[1].write_text('{"secret":"must-not-leak"}')
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and "must-not-leak" not in result.stderr and not result.stdout
