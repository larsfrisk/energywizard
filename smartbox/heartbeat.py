"""heartbeat.py - livstecken från motorns huvudloop, så att en motor som hänger sig syns (docker ps, Portainer).

Huvudloopen skriver en liten fil varje varv (cirka var 10:e sekund). Containerns HEALTHCHECK kör `python heartbeat.py`,
som blir röd om filen är äldre än MAX_AGE_S. En krasch hanteras redan (omstartspolicyn, run.sh i tillägget); det här fångar
en motor som lever men står still, till exempel ett nätverksanrop utan tidsgräns. En uppgift som med flit tar lång tid
(veckans MPC-backtest) markerar sig som upptagen med long_task() så att den inte ger falsklarm.

Skriver aldrig något som kan fälla loopen: alla fel i beat() sväljs.

Stillestånd: en vakttråd (watch/start_watch) ser efter livstecknet var 30:e sekund. Är det äldre än STALL_S (15 min, med
marginal över HEALTHCHECK:ens 10) och ingen uppgift är markerad som upptagen, rapporterar den EN gång per stillestånd var
huvudtråden står (fil, rad och funktion, aldrig värden) och, när livstecknet kommer tillbaka, att det löst sig. Den
startar inte om något: en omstart kan ge loopar om orsaken är Home Assistant eller databasen, och först när vi sett hur
ofta det händer på riktigt går det att bestämma om och hur en omstart ska ske.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback

PATH = os.environ.get("EW_HEARTBEAT_FILE", "/tmp/ew_heartbeat.json")
MAX_AGE_S = 600           # ett varv tar normalt några sekunder; tio minuter utan livstecken är inte normalt
STALL_S = 900             # vakttråden rapporterar först efter så här länge (marginal över HEALTHCHECK:ens MAX_AGE_S)
WATCH_EVERY_S = 30
_LIBRARY = ("/site-packages/", "/lib/python")


def beat(task: str = "", busy_s: float = 0.0, path: str | None = None) -> None:
    """Skriv livstecknet. busy_s > 0: en uppgift som får ta så här länge innan filen räknas som gammal."""
    p = path or PATH
    try:
        now = time.time()
        tmp = f"{p}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"t": now, "busy_until": now + busy_s if busy_s else 0, "task": str(task)[:60]}, f)
        os.replace(tmp, p)
    except Exception:
        pass


class long_task:
    """with heartbeat.long_task("mpc_backtest", 2700): ... - tål så här många sekunder utan nytt livstecken."""

    def __init__(self, name: str, max_s: float):
        self.name, self.max_s = name, float(max_s)

    def __enter__(self):
        beat(self.name, self.max_s)
        return self

    def __exit__(self, *exc):
        beat()
        return False


def status(now: float | None = None, path: str | None = None, max_age: float = MAX_AGE_S) -> tuple[bool, str]:
    """(i lag, text). Saknad eller trasig fil är inte i lag."""
    now = time.time() if now is None else now
    try:
        with open(path or PATH, encoding="utf-8") as f:
            d = json.load(f)
        t, busy = float(d["t"]), float(d.get("busy_until") or 0)
    except Exception as e:
        return False, f"inget livstecken ({type(e).__name__})"
    age = now - t
    if age <= max_age:
        return True, f"livstecken för {age:.0f} s sedan"
    if now < busy:
        return True, f"upptagen med {d.get('task') or 'en lång uppgift'} (livstecken för {age:.0f} s sedan)"
    return False, f"motorn har inte gett livstecken på {age:.0f} s (gräns {max_age:.0f} s)"


def describe_stack(frame, limit: int = 14) -> tuple[str, list[str]]:
    """(var i vår egen kod, anropskedjan ytterst först som "fil.py:rad funktion"). Bara filnamn, radnummer och funktionsnamn:
    inga sökvägar, värden eller texter. Tomt om det inte går att avgöra (ingen ram)."""
    if frame is None:
        return "", []
    try:
        frames = [(fr.filename.replace("\\", "/"), f"{os.path.basename(fr.filename)}:{fr.lineno} {fr.name}")
                  for fr in traceback.extract_stack(frame)]
    except Exception:
        return "", []
    own = [t for f, t in frames if not any(k in f for k in _LIBRARY)]
    return (own[-1] if own else "")[:60], [t for _f, t in frames][-limit:]


def _main_frame():
    return sys._current_frames().get(threading.main_thread().ident)


def watch(on_stall, on_recover=None, stall_s: float = STALL_S, every_s: float = WATCH_EVERY_S, path: str | None = None,
          clock=time.time, sleep=time.sleep, main_frame=_main_frame, stop=lambda: False) -> None:
    """Se efter livstecknet tills stop() är sann. on_stall({text, where, stack}) en gång per stillestånd, on_recover(text) när
    det löst sig. Fel i anropen eller i själva kontrollen får aldrig fälla vakttråden."""
    stalled = False
    while not stop():
        sleep(every_s)
        try:
            ok, text = status(now=clock(), path=path, max_age=stall_s)
            if not ok and not stalled:
                stalled = True
                where, stack = describe_stack(main_frame())
                on_stall({"text": text, "where": where, "stack": stack})
            elif ok and stalled:
                stalled = False
                if on_recover:
                    on_recover(text)
        except Exception:
            pass


def start_watch(on_stall, on_recover=None, stall_s: float = STALL_S, every_s: float = WATCH_EVERY_S) -> threading.Thread:
    """Startar vakttråden (daemon). Skriver ett färskt livstecken först, så att en fil från en tidigare process (omstart i samma
    container) inte räknas som ett stillestånd direkt."""
    beat("start")
    t = threading.Thread(target=watch, args=(on_stall, on_recover, stall_s, every_s), name="ew-heartbeat-watch", daemon=True)
    t.start()
    return t


def main() -> int:
    ok, text = status()
    print(("OK: " if ok else "OHÄLSOSAMT: ") + text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
