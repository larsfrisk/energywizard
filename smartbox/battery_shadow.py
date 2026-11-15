"""Default-off cooperation-mode candidate plans; no actuator or active-plan path."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime
import math
from queue import Empty, Full, Queue
import threading
import time

from drivers.battery import INTENTS


def _eligible(event):
    import shadow
    return shadow.active() and -5 <= time.time() - event["now"].timestamp() <= 90


def process(event):
    if not _eligible(event):
        return None
    import battery_plan
    from database_engine import engine
    return battery_plan.plan_from_db(engine, event["now"], event["state"]["soc_pct"],
        event["settings"], event["profile"], set(event["allowed"]),
        soc_evidence=event["state"], comparison=True)


class _ReadOnlyHistory:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def connect(self):
        from sqlalchemy import text
        with self.engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '2s'"))
            yield conn


def _learn(settings, as_of):
    import battery_learning
    from database_engine import engine
    return battery_learning.learn_from_db(_ReadOnlyHistory(engine), settings, as_of=as_of)


class Evaluator:
    """Private six-hour model cache; never populates the active controller model."""
    def __init__(self, learner=_learn, planner=process):
        self._learner, self._planner = learner, planner
        self._model, self._at, self._key = None, None, None
        self._state = "unavailable"

    def process(self, event):
        if not _eligible(event):
            return None
        if event.get("learn_from_history") is not True:
            return self._planner(event)
        import battery_learning
        settings = event["settings"]
        # Only normalized primitive settings affect cache identity. Forecast/profile
        # dictionaries are inputs to planning, not configuration for learning.
        key = tuple(sorted((k, v) for k, v in settings.items() if v is None or isinstance(v, (str, int, float, bool))))
        now = event["now"].timestamp()
        if self._at is None or key != self._key or not 0 <= now - self._at < 21600:
            self._model, self._state = None, "unavailable"
            self._key, self._at = key, now
            try:
                model = self._learner(deepcopy(settings), event["now"])
                if not isinstance(model, dict) or not isinstance(model.get("use"), dict):
                    raise ValueError("Invalid history model")
                self._model = model
                self._state = "learned" if model["use"] else "insufficient"
            except Exception:
                pass  # Preserve configured fallback; never expose database/config errors.
        applied = battery_learning.apply(settings, self._model) if self._model and self._model["use"] else deepcopy(settings)
        applied["comparison_learning"] = {"state": self._state, "age_s": now - self._at}
        return self._planner({**event, "settings": applied})


class Monitor:
    """One daemon and at most one waiting sample; submit never waits for I/O."""
    def __init__(self, planner=None):
        self._planner = planner or Evaluator().process
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
                     "learn_from_history": config.get("learn_from_history") is True,
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
