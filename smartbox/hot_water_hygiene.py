"""An operator timer reset is separate from measured temperature history."""
from datetime import datetime, timezone
import math


def last_event(measured, reset_at=None, *, now=None):
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    if measured is not None:
        measured = measured.replace(tzinfo=timezone.utc) if measured.tzinfo is None else measured
    if (type(reset_at) not in (int, float) or not math.isfinite(reset_at)
            or not 0 < reset_at <= now):
        return measured
    reset = datetime.fromtimestamp(reset_at, timezone.utc)
    return max(measured, reset) if measured is not None else reset
