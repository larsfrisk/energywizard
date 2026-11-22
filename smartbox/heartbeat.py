"""heartbeat.py - livstecken från motorns huvudloop, så att en motor som hänger sig syns (docker ps, Portainer).

Huvudloopen skriver en liten fil varje varv (cirka var 10:e sekund). Containerns HEALTHCHECK kör `python heartbeat.py`,
som blir röd om filen är äldre än MAX_AGE_S. En krasch hanteras redan (omstartspolicyn, run.sh i tillägget); det här fångar
en motor som lever men står still, till exempel ett nätverksanrop utan tidsgräns. En uppgift som med flit tar lång tid
(veckans MPC-backtest) markerar sig som upptagen med long_task() så att den inte ger falsklarm.

Skriver aldrig något som kan fälla loopen: alla fel i beat() sväljs.
"""
from __future__ import annotations

import json
import os
import sys
import time

PATH = os.environ.get("EW_HEARTBEAT_FILE", "/tmp/ew_heartbeat.json")
MAX_AGE_S = 600           # ett varv tar normalt några sekunder; tio minuter utan livstecken är inte normalt


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


def main() -> int:
    ok, text = status()
    print(("OK: " if ok else "OHÄLSOSAMT: ") + text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
