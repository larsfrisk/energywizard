"""Default-off cooperation-mode candidate plans; no actuator or active-plan path."""
from copy import deepcopy
from datetime import datetime
import math
from queue import Empty, Full, Queue
import threading
import time

from drivers.battery import INTENTS


def process(event):
    import shadow
    if not shadow.active():
        return None
    if not -5 <= time.time() - event["now"].timestamp() <= 90:
        return None
    import battery_plan
    from database_engine import engine
    return battery_plan.plan_from_db(engine, event["now"], event["state"]["soc_pct"],
        event["settings"], event["profile"], set(event["allowed"]),
        soc_evidence=event["state"], comparison=True)


class Monitor:
    """One daemon and at most one waiting sample; submit never waits for I/O."""
    def __init__(self, planner=process):
        self._planner = planner
        self._queue = Queue(maxsize=1)
        self._lock = threading.Lock()
        self._thread = None
        self._last_slot = None

    def _run(self):
        while True:
            event = self._queue.get()
            try:
                self._planner(event)
            except Exception:
                pass  # No raw configuration/errors in logs; comparison cannot affect control.
            finally:
                self._queue.task_done()

    def submit(self, config, settings, state, profile, *, now, shadow):
        try:
            allowed = config.get("allowed_intents")
            if (config.get("enabled") is not True or shadow is not True
                    or settings.get("control") != "samarbete" or settings.get("plan") is not True
                    or not isinstance(allowed, list) or not allowed
                    or any(not isinstance(x, str) or x not in INTENTS for x in allowed)
                    or "auto" not in allowed
                    or len(allowed) != len(set(allowed))
                    or not isinstance(now, datetime) or now.utcoffset() is None):
                return False
            for value, low, high in ((state.get("soc_pct"), 0, 100), (settings.get("capacity_kwh"), 0, float("inf"))):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                    return False
            if settings["capacity_kwh"] <= 0:
                return False
            slot = int(now.timestamp() // 900)
            event = {"now": now, "settings": deepcopy(settings), "profile": deepcopy(profile),
                     "allowed": tuple(allowed), "state": {k: state.get(k) for k in ("soc_pct", "soc_sample_at", "soc_source")}}
            # Balancing needs real ownership; never copy a maintenance request into comparison.
            event["settings"].pop("balance_request", None)
            with self._lock:
                if self._last_slot is not None and slot <= self._last_slot:
                    return False
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, daemon=True, name="battery-shadow-plan")
                    self._thread.start()
                try:
                    self._queue.put_nowait(event)
                except Full:
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except Empty:
                        pass
                    self._queue.put_nowait(event)
                self._last_slot = slot
            return True
        except Exception:
            return False
