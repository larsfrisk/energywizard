"""Comparison-only learning: causal, cached, read-only, and never active authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

import battery_shadow as B


NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def event(**changes):
    return dict(now=NOW, settings={"control": "samarbete", "capacity_kwh": 10,
                                  "max_power_w": 5000, "efficiency": .9},
                state={"soc_pct": 50}, profile={}, allowed=("auto", "charge"),
                learn_from_history=True) | changes


def test_optional_model_is_cached_then_refreshed_and_does_not_mutate_input(monkeypatch):
    monkeypatch.setattr(B, "_eligible", lambda e: True)
    learned, planned = [], []
    def learner(settings, as_of):
        learned.append((settings, as_of))
        return {"learned": {}, "use": {"load_profile": {(0, 1): 1.2}, "solar_factor": {1: .8}}}
    evaluator = B.Evaluator(learner, lambda e: planned.append(e) or e)
    first = event(); original = deepcopy(first)
    result = evaluator.process(first)
    assert first == original
    assert result["settings"]["load_profile"] == {(0, 1): 1.2}
    assert result["settings"]["comparison_learning"] == {"state": "learned", "age_s": 0}
    assert learned[0][1] == NOW
    assert evaluator.process(event(now=NOW+timedelta(minutes=15)))["settings"]["comparison_learning"]["age_s"] == 900
    assert len(learned) == 1
    evaluator.process(event(now=NOW+timedelta(hours=6)))
    assert len(learned) == 2
    evaluator.process(event(now=NOW+timedelta(hours=6,minutes=15), settings=original["settings"] | {"capacity_kwh": 12}))
    assert len(learned) == 3


@pytest.mark.parametrize("mode", ["insufficient", "failure", "malformed"])
def test_unavailable_history_keeps_configured_fallback_without_raw_errors(monkeypatch, mode):
    monkeypatch.setattr(B, "_eligible", lambda e: True)
    def learner(settings, as_of):
        if mode == "failure":
            raise RuntimeError("private database details")
        return {"use": {}} if mode == "insufficient" else {"use": None}
    evaluator = B.Evaluator(learner, lambda e: e)
    supplied = event()
    supplied["settings"]["load_profile"] = {(0, 1): 2}
    result = evaluator.process(supplied)
    assert result["settings"]["load_profile"] == {(0, 1): 2}
    expected = "insufficient" if mode == "insufficient" else "unavailable"
    assert result["settings"]["comparison_learning"]["state"] == expected
    assert "private database details" not in str(result)


def test_default_off_and_shadow_or_stale_guards_do_not_learn(monkeypatch):
    def forbidden(*args):
        raise AssertionError("Learning must not run")
    monkeypatch.setattr(B, "_eligible", lambda e: True)
    evaluator = B.Evaluator(forbidden, lambda e: e)
    supplied = event(learn_from_history=False)
    assert evaluator.process(supplied) is supplied
    assert "comparison_learning" not in supplied["settings"]
    monkeypatch.setattr(B, "_eligible", lambda e: False)
    assert evaluator.process(event()) is None


def test_real_postgres_history_is_read_only_and_cutoff_excludes_later_data(db, smartbox, monkeypatch):
    import battery_learning as L
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError
    engine = create_engine("postgresql+psycopg://postgres:test@localhost/smartbox_test")
    cutoff = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=1)
    cutoff = cutoff.replace(minute=cutoff.minute//15*15)
    db.execute("TRUNCATE sensor_log")
    db.execute("CREATE TABLE IF NOT EXISTS battery_plan_forecast (t_slot TIMESTAMPTZ PRIMARY KEY, load_kw NUMERIC, solar_kw NUMERIC, made_at TIMESTAMPTZ DEFAULT now())")
    db.execute("TRUNCATE battery_plan_forecast")
    for delta, soc, watts in ((-45, 10, 1000), (-30, 20, 1000), (1, 99, 1000000)):
        t = cutoff + timedelta(minutes=delta)
        db.execute("INSERT INTO sensor_log(timestamp,battery_soc,battery_power_w,net_power,price,pv_power_w,solar_forecast_w,house_consumption_w) VALUES(%s,%s,0,%s,1,%s,%s,%s)", (t,soc,watts,watts,watts,watts))
    for delta, value, made in ((-45, 1, cutoff-timedelta(hours=2)), (-30, 999, cutoff+timedelta(seconds=10))):
        db.execute("INSERT INTO battery_plan_forecast VALUES(%s,%s,1,%s)", (cutoff+timedelta(minutes=delta),value,made))
    observed, pairs, loads = [], [], []
    def learn(samples, solar, settings):
        observed.append((samples, solar))
        return {"learned": {}, "use": {}}
    monkeypatch.setattr(L, "learn", learn)
    monkeypatch.setattr(L, "median_load_profile", lambda rows: (loads.extend(rows) or {}))
    monkeypatch.setattr(L, "outcome_bias", lambda data, kind: (pairs.append((kind,data)) or (None,None,len(data))))
    try:
        with pytest.raises(ValueError):
            L.learn_from_db(B._ReadOnlyHistory(engine), {}, as_of=cutoff.replace(tzinfo=None))
        L.learn_from_db(B._ReadOnlyHistory(engine), {}, as_of=cutoff)
        assert [sample[1] for sample in observed[-1][0]] == [10, 20]
        assert all(float(actual)<100000 for _,_,actual in observed[-1][1])
        assert all(kw<100 for _,_,kw in loads)
        assert all(float(fc)!=999 for _,rows in pairs for fc,_ in rows)
        observed.clear(); pairs.clear()
        L.learn_from_db(B._ReadOnlyHistory(engine), {})  # Existing callers retain their current-time behavior.
        assert 99 in [sample[1] for sample in observed[-1][0]]
        with B._ReadOnlyHistory(engine).connect() as conn:
            assert conn.execute(text("SELECT current_setting('transaction_read_only'), current_setting('statement_timeout')")).one() == ('on','2s')
        with pytest.raises(DBAPIError):
            with B._ReadOnlyHistory(engine).connect() as conn:
                conn.execute(text("CREATE TABLE forbidden_shadow_learning_write (n INT)"))
        assert db.execute("SELECT to_regclass('forbidden_shadow_learning_write')").fetchone()[0] is None
    finally:
        engine.dispose()


@pytest.mark.parametrize('explicit_model', [False, True])
def test_learning_outcome_is_bound_into_real_comparison_snapshot(db, monkeypatch, tmp_path, explicit_model):
    import battery_plan, ew_settings, ha_solar_forecast, learning, nordpool, plan_snapshot, weather
    from sqlalchemy import create_engine
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    now = now.replace(minute=now.minute//15*15)
    db.execute("TRUNCATE elpriser")
    for i in range(2):
        db.execute("INSERT INTO elpriser VALUES (%s,%s)", (now+timedelta(minutes=15*i),1))
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path/'settings.json'))
    monkeypatch.setattr(ha_solar_forecast, "power_at", lambda *args: None)
    monkeypatch.setattr(learning, "predict_base_load", lambda *args: 1)
    monkeypatch.setattr(weather, "get_weather_at", lambda *args: (0,0,0,0))
    monkeypatch.setattr(weather, "get_smart_solar_w", lambda *args, **kwargs: 0)
    monkeypatch.setattr(nordpool, "full_buy_cost", lambda price, *args: price)
    monkeypatch.setattr(nordpool, "full_sell_income", lambda price: 0)
    captured = []
    def capture(*args, **kwargs):
        snap = plan_snapshot.build(*args, **kwargs)
        captured.append(snap)
        return snap['plan_id']
    monkeypatch.setattr(plan_snapshot, "capture", capture)
    settings = dict(capacity_kwh=1, reserve_soc=20, max_soc=90, max_power_w=1000,
                    comparison_learning={"state":"learned","age_s":900,"private":"must-not-leak"})
    original = deepcopy(settings)
    if explicit_model:
        settings = B._with_battery_model({'settings':settings,'battery_model':dict(
            capacity_kwh=2,reserve_soc=10,max_soc=80,charge_kw=3,discharge_kw=4,
            charge_efficiency=.8,discharge_efficiency=.95)})['settings']
    engine = create_engine("postgresql+psycopg://postgres:test@localhost/smartbox_test")
    try:
        result = battery_plan.plan_from_db(B._ReadOnlyHistory(engine),now,50,settings,{}, {'auto','hold','charge'},comparison=True)
        expected = {"source":"ew_history","state":"learned","age_s":900}
        assert result['input_quality']['learning'] == captured[0]['input_quality']['learning'] == expected
        assert 'must-not-leak' not in plan_snapshot.canonical(captured[0])
        assert plan_snapshot.replay(captured[0])['matches']
        assert not result['control_ready'] and result['simulation_only']
        if explicit_model:
            params = captured[0]['inputs']['params']
            assert params['capacity_kwh']==2 and params['soc0_kwh']==1
            assert params['reserve_kwh']==.2 and params['max_kwh']==1.6
            assert (params['charge_kw'],params['discharge_kw'])==(3,4)
            assert (params['charge_efficiency'],params['discharge_efficiency'])==(.8,.95)
            assert captured[0]['input_quality']['battery_model']=={'source':'explicit_comparison'}
            assert original['capacity_kwh']==1
    finally:
        engine.dispose()
