"""Cooperation comparisons must never acquire active-plan or actuator authority."""
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

import battery_shadow as B


NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
CONFIG = {"enabled": True, "allowed_intents": ["auto", "charge", "hold"]}
SETTINGS = {"control": "samarbete", "plan": True, "capacity_kwh": 10}
STATE = {"soc_pct": 50, "soc_sample_at": NOW.timestamp() - 10, "soc_source": "ha_reported"}


class FakeThread:
    def __init__(self, **kwargs):
        assert kwargs["daemon"] is True
    def start(self):
        pass


def test_frozen_event_is_bounded_deduplicated_and_has_no_driver(monkeypatch):
    monkeypatch.setattr(B.threading, "Thread", FakeThread)
    monitor = B.Monitor()
    settings = dict(SETTINGS, balance_request={"request": True})
    state = dict(STATE, token="private", power_w=999)
    profile = {0: 1}
    assert monitor.submit(CONFIG, settings, state, profile, now=NOW, shadow=True)
    assert not monitor.submit(CONFIG, settings, state, profile, now=NOW, shadow=True)
    profile[0] = 9
    event = monitor._queue.get_nowait()
    monitor._queue.task_done()
    assert event["profile"] == {0: 1} and event["state"] == STATE
    assert "balance_request" not in event["settings"]
    assert "driver" not in event
    for quarter in range(1, 5):
        assert monitor.submit(CONFIG, SETTINGS, STATE, {}, now=NOW + timedelta(minutes=15*quarter), shadow=True)
    assert monitor._queue.qsize() == 1
    assert monitor._queue.get_nowait()["now"] == NOW + timedelta(hours=1)


@pytest.mark.parametrize("change", [dict(shadow=False), dict(config={}), dict(config={"enabled": True}),
    dict(config={"enabled": True, "allowed_intents": ["auto", "unknown"]}),
    dict(config={"enabled": True, "allowed_intents": ["charge"]}),
    dict(config={"enabled": True, "allowed_intents": ["auto", "auto"]}),
    dict(settings=dict(SETTINGS, control="styr")), dict(settings=dict(SETTINGS, control="av")),
    dict(settings=dict(SETTINGS, plan=False)), dict(settings=dict(SETTINGS, capacity_kwh=0)),
    dict(state={"soc_pct": None}), dict(state={"soc_pct": float("nan")}),
    dict(state={"soc_pct": True}), dict(now=NOW.replace(tzinfo=None))])
def test_default_off_and_all_guards_reject_before_starting_worker(change):
    monitor = B.Monitor()
    args = dict(config=CONFIG, settings=SETTINGS, state=STATE, profile={}, now=NOW, shadow=True) | change
    assert not monitor.submit(**args)
    assert monitor._thread is None and monitor._queue.empty()


def test_blocked_planner_never_blocks_submit_and_latest_waiting_sample_wins():
    entered, release, finished = Event(), Event(), Event()
    def planner(event):
        entered.set()
        release.wait(5)
        finished.set()
    monitor = B.Monitor(planner)
    try:
        assert monitor.submit(CONFIG, SETTINGS, STATE, {}, now=NOW, shadow=True)
        assert entered.wait(2)
        for quarter in range(1, 4):
            assert monitor.submit(CONFIG, SETTINGS, STATE, {}, now=NOW + timedelta(minutes=15*quarter), shadow=True)
        assert monitor._queue.qsize() == 1
    finally:
        release.set()
    assert finished.wait(2)


@pytest.mark.parametrize("shadow,age", [(False, 0), (True, 91), (True, -6)])
def test_worker_rechecks_shadow_and_discards_old_or_future_queue_samples(monkeypatch, shadow, age):
    import shadow as S
    monkeypatch.setattr(S, "active", lambda: shadow)
    monkeypatch.setattr(B.time, "time", lambda: NOW.timestamp() + age)
    assert B.process({"now": NOW}) is None  # No database import or planner access.


def test_worker_requests_only_a_comparison_plan(monkeypatch):
    import sys
    from types import SimpleNamespace
    import shadow
    import battery_plan
    monkeypatch.setattr(shadow, "active", lambda: True)
    monkeypatch.setattr(B.time, "time", lambda: NOW.timestamp())
    monkeypatch.setitem(sys.modules, "database_engine", SimpleNamespace(engine="read-engine"))
    calls = []
    monkeypatch.setattr(battery_plan, "plan_from_db", lambda *args, **kwargs: calls.append((args, kwargs)))
    B.process(dict(now=NOW, state=STATE, settings=SETTINGS, profile={}, allowed=("auto", "hold")))
    assert calls[0][1] == dict(comparison=True, soc_evidence=STATE)
    assert calls[0][0][-1] == {"auto", "hold"}
