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


# --- stillestånd: vakttråden rapporterar var huvudtråden står, en gång, och startar inte om ---

def _watch(path, steps, **kw):
    """Kör watch() ett fast antal varv med en låtsasklocka; steps = klockans värde per varv. Returnerar (stall, recover)."""
    stalls, recovers = [], []
    clock = iter(steps)
    n = {"i": 0}

    def stop():
        n["i"] += 1
        return n["i"] > len(steps)
    heartbeat.watch(stalls.append, recovers.append, path=path, clock=lambda: next(clock), sleep=lambda s: None,
                    main_frame=lambda: sys._getframe(), stop=stop, **kw)
    return stalls, recovers


def test_stall_is_reported_once_with_where_the_main_thread_stands(tmp_path):
    p = str(tmp_path / "hb.json")
    heartbeat.beat(path=p)
    t0 = time.time()
    stalls, recovers = _watch(p, [t0 + 60, t0 + heartbeat.STALL_S + 10, t0 + heartbeat.STALL_S + 40, t0 + heartbeat.STALL_S + 70])
    assert len(stalls) == 1 and recovers == []                     # en gång per stillestånd, inte var 30:e sekund
    info = stalls[0]
    assert "inte gett livstecken" in info["text"]
    assert info["where"].startswith("test_heartbeat.py:") and " " in info["where"]          # fil:rad funktion i vår egen kod
    assert info["stack"] and all(" " in line and ":" in line for line in info["stack"])
    assert not any("/" in line for line in info["stack"])         # bara filnamn, aldrig sökvägar


def test_no_stall_report_inside_the_grace_period_or_while_busy(tmp_path):
    p = str(tmp_path / "hb.json")
    heartbeat.beat(path=p)
    t0 = time.time()
    assert _watch(p, [t0 + 100, t0 + heartbeat.STALL_S - 5])[0] == []          # under 15 min: inget
    heartbeat.beat("mpc_backtest", 3600, path=p)
    assert _watch(p, [t0 + heartbeat.STALL_S + 500])[0] == []                  # med flit upptagen: inget


def test_recovery_is_reported_and_a_new_stall_can_be_reported_again(tmp_path):
    p = tmp_path / "hb.json"
    heartbeat.beat(path=str(p))
    t0 = time.time()
    late = t0 + heartbeat.STALL_S + 60
    stalls, recovers = [], []
    seq = iter([late, late + 30, late + 40, late + 3000])         # stillestånd, löser sig, nytt stillestånd
    n = {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] == 3:                                             # tredje varvet: ett färskt livstecken skrivs av loopen
            heartbeat.beat(path=str(p))

    def clock():
        v = next(seq)
        return time.time() + 1 if n["i"] == 3 else v

    heartbeat.watch(stalls.append, recovers.append, path=str(p), clock=clock, sleep=sleep,
                    main_frame=lambda: sys._getframe(), stop=lambda n=n: n["i"] >= 4)
    assert len(stalls) >= 1 and len(recovers) == 1 and "livstecken" in recovers[0]


def test_a_failing_callback_never_kills_the_watcher(tmp_path):
    p = str(tmp_path / "hb.json")
    heartbeat.beat(path=p)
    t0 = time.time()
    n = {"i": 0, "calls": 0}
    clock = iter([t0 + heartbeat.STALL_S + 10] * 5)

    def boom(info):
        n["calls"] += 1
        raise RuntimeError("fel i anropet")

    def stop():
        n["i"] += 1
        return n["i"] > 3
    heartbeat.watch(boom, None, path=p, clock=lambda: next(clock), sleep=lambda s: None, main_frame=lambda: sys._getframe(), stop=stop)
    assert n["calls"] == 1 and n["i"] == 4                          # loopen gick vidare efter felet


def test_start_watch_writes_a_fresh_beat_first_and_starts_a_daemon(tmp_path, monkeypatch):
    p = str(tmp_path / "hb.json")
    monkeypatch.setattr(heartbeat, "PATH", p)
    Path(p).write_text(json.dumps({"t": time.time() - 99999, "busy_until": 0, "task": ""}))     # gammal fil från en tidigare process
    t = heartbeat.start_watch(lambda i: None, every_s=3600)
    assert t.daemon and t.is_alive() and t.name == "ew-heartbeat-watch"
    assert heartbeat.status(path=p)[0]                              # färskt livstecken: ingen falsk "stillestånd" efter en omstart


def test_describe_stack_names_file_line_and_function_only():
    where, stack = heartbeat.describe_stack(sys._getframe())
    assert where.startswith("test_heartbeat.py:") and "test_describe_stack" in where
    assert heartbeat.describe_stack(None) == ("", [])
    assert len(heartbeat.describe_stack(sys._getframe(), limit=3)[1]) <= 3


def test_the_engine_starts_the_watcher_and_only_reports_never_restarts():
    main = (ROOT / "smartbox/main.py").read_text()
    assert "heartbeat.start_watch(_on_loop_stall, _on_loop_recover)" in main
    assert 'telemetry.report_error(house_cfg, "main_loop_stall@"' in main and '"LoopStall"' in main
    src = (ROOT / "smartbox/heartbeat.py").read_text()
    assert "os._exit" not in src and "sys.exit(" not in src.split("def main")[0]           # vakten startar aldrig om något


def test_a_really_hung_main_thread_is_found_where_it_hangs(tmp_path):
    """En egen process vars huvudtråd blockerar på ett nätverksanrop utan tidsgräns: vakttråden ska hitta var."""
    code = f'''
import socket, sys, time
sys.path.insert(0, {str(ROOT / "smartbox")!r})
import heartbeat
def on_stall(info):
    print("STALL", info["where"], flush=True)
    for line in info["stack"]: print("STACK", line, flush=True)
heartbeat.start_watch(on_stall, lambda t: print("RECOVER", flush=True), stall_s=1.5, every_s=0.3)
def hung_network_call():
    a, b = socket.socketpair()
    a.settimeout(4.0)                          # blockerar tills tidsgränsen: huvudtråden ger inget livstecken
    try:
        a.recv(1)
    except socket.timeout:
        pass
hung_network_call()
heartbeat.beat()
time.sleep(0.8)
'''
    env = {"EW_HEARTBEAT_FILE": str(tmp_path / "hb.json"), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    out = r.stdout
    assert r.returncode == 0, r.stderr
    assert out.count("STALL") == 1                                          # en rapport, inte en per 0,3 s
    assert "hung_network_call" in out                                       # funktionen den hänger i
    assert "RECOVER" in out                                                 # och att det löste sig när livstecknet kom tillbaka
    assert "/" not in out.split("RECOVER")[0].replace("STALL ", "").replace("STACK ", "")   # inga sökvägar
