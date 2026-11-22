"""Livstecken från huvudloopen (heartbeat.py): en motor som hänger sig ska synas, en som är upptagen med flit ska inte larma."""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
import heartbeat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_beat_is_healthy(tmp_path):
    p = str(tmp_path / "hb.json")
    heartbeat.beat(path=p)
    ok, text = heartbeat.status(path=p)
    assert ok and "livstecken" in text


def test_stale_beat_is_unhealthy(tmp_path):
    p = str(tmp_path / "hb.json")
    heartbeat.beat(path=p)
    ok, text = heartbeat.status(now=time.time() + heartbeat.MAX_AGE_S + 5, path=p)
    assert not ok and "inte gett livstecken" in text
    assert heartbeat.status(now=time.time() + heartbeat.MAX_AGE_S - 30, path=p)[0]        # strax innanför gränsen


def test_missing_or_corrupt_file_is_unhealthy(tmp_path):
    p = tmp_path / "hb.json"
    ok, text = heartbeat.status(path=str(p))
    assert not ok and "inget livstecken" in text
    p.write_text("inte json")
    assert not heartbeat.status(path=str(p))[0]
    p.write_text(json.dumps({"x": 1}))
    assert not heartbeat.status(path=str(p))[0]


def test_a_long_task_is_busy_not_hung_until_its_time_is_up(tmp_path):
    p = str(tmp_path / "hb.json")
    heartbeat.beat("mpc_backtest", 1800, path=p)
    old = time.time() + heartbeat.MAX_AGE_S + 60                  # långt efter normal gräns men inom uppgiftens tid
    ok, text = heartbeat.status(now=old, path=p)
    assert ok and "mpc_backtest" in text
    assert not heartbeat.status(now=time.time() + 1801 + heartbeat.MAX_AGE_S, path=p)[0]   # uppgiften är försenad: hängd


def test_long_task_context_sets_busy_and_clears_it(tmp_path, monkeypatch):
    p = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "PATH", p)
    with heartbeat.long_task("x", 600):
        d = json.loads(Path(p).read_text())
        assert d["busy_until"] > time.time() + 500 and d["task"] == "x"
    d = json.loads(Path(p).read_text())
    assert d["busy_until"] == 0 and d["task"] == ""             # klart: inget upptaget-fönster kvar


def test_long_task_does_not_swallow_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(heartbeat, "PATH", str(tmp_path / "hb.json"))
    try:
        with heartbeat.long_task("x", 60):
            raise ValueError("fel i uppgiften")
    except ValueError:
        pass
    else:
        raise AssertionError("felet ska gå vidare")


def test_beat_never_breaks_the_loop_when_the_file_cannot_be_written(tmp_path):
    heartbeat.beat(path=str(tmp_path / "finns-inte" / "hb.json"))           # katalogen saknas: inget undantag


def test_command_line_exit_code_is_the_healthcheck(tmp_path):
    p = str(tmp_path / "hb.json")
    env = {"EW_HEARTBEAT_FILE": p, "PATH": "/usr/bin:/bin"}
    run = lambda: subprocess.run([sys.executable, str(ROOT / "smartbox/heartbeat.py")], env=env, capture_output=True, text=True)
    r = run()
    assert r.returncode == 1 and "OHÄLSOSAMT" in r.stdout          # inget livstecken än
    heartbeat.beat(path=p)
    r = run()
    assert r.returncode == 0 and r.stdout.startswith("OK:")
    Path(p).write_text(json.dumps({"t": time.time() - 3 * heartbeat.MAX_AGE_S, "busy_until": 0, "task": ""}))
    assert run().returncode == 1                                    # gammalt livstecken: röd


def test_the_engine_image_has_the_healthcheck_and_the_loop_beats():
    docker = (ROOT / "smartbox/Dockerfile").read_text()
    assert 'HEALTHCHECK' in docker and "/app/heartbeat.py" in docker and "--start-period" in docker
    main = (ROOT / "smartbox/main.py").read_text()
    assert "heartbeat.beat()" in main and 'heartbeat.long_task("mpc_backtest"' in main
