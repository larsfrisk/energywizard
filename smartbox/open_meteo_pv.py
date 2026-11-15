"""Optional comparison-only tilted-plane PV model; fixed endpoint, bounded reads."""
from datetime import datetime, timedelta, timezone
import json
import math
import time

import requests

URL = "https://api.open-meteo.com/v1/forecast"
FIELDS = ("latitude", "longitude", "tilt_deg", "azimuth_deg", "kwp", "derate")


def configuration(config):
    if config.get("enabled") is not True or config.get("source") != "open_meteo":
        raise ValueError("Explicit Open-Meteo comparison model required")
    values = {}
    for key in FIELDS:
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Explicit finite model geometry and derating required")
        values[key] = float(value)
    if not (-90 <= values["latitude"] <= 90 and -180 <= values["longitude"] <= 180
            and 0 <= values["tilt_deg"] <= 90 and -180 <= values["azimuth_deg"] <= 180
            and values["kwp"] > 0 and 0 < values["derate"] <= 1):
        raise ValueError("Invalid model geometry or derating")
    return values


def parse(payload, config):
    """Hourly irradiance means end at the API timestamp, not start there."""
    units, hourly = payload.get("hourly_units") or {}, payload.get("hourly") or {}
    if units.get("time") != "unixtime" or units.get("global_tilted_irradiance") != "W/m²":
        raise ValueError("Unexpected irradiance units")
    times, values = hourly.get("time"), hourly.get("global_tilted_irradiance")
    if not isinstance(times, list) or not isinstance(values, list) or not 1 <= len(times) == len(values) <= 96:
        raise ValueError("Invalid hourly arrays")
    periods, previous = [], None
    for stamp, irradiance in zip(times, values):
        if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp % 3600 or (previous is not None and stamp <= previous):
            raise ValueError("Ordered unique UTC hour endpoints required")
        previous = stamp
        if isinstance(irradiance, bool) or not isinstance(irradiance, (int, float)) or not math.isfinite(irradiance) or irradiance < 0:
            continue
        watts = config["kwp"] * config["derate"] * irradiance
        if not math.isfinite(watts):
            continue
        end = datetime.fromtimestamp(stamp, timezone.utc)
        periods.append((end-timedelta(hours=1), end, watts))
    return periods


def fetch(config):
    params = {"latitude": config["latitude"], "longitude": config["longitude"],
              "tilt": config["tilt_deg"], "azimuth": config["azimuth_deg"],
              "hourly": "global_tilted_irradiance", "timezone": "UTC", "timeformat": "unixtime", "forecast_days": 3}
    with requests.get(URL, params=params, timeout=(5, 15), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError("Forecast request unavailable")
        parts, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 2_000_000:
                raise ValueError("Oversize forecast response")
            parts.append(chunk)
    return json.loads(b"".join(parts))


class Forecast:
    """One geometry/cache per worker, hourly refresh, no stale-on-error reuse."""
    def __init__(self, reader=fetch, clock=time.time):
        self.reader, self.clock = reader, clock
        self._key, self._at, self._data = None, None, None

    def snapshot(self, raw):
        now = self.clock()
        try:
            config = configuration(raw)
        except (ValueError, TypeError, AttributeError):
            return {"state": "invalid_config", "periods": [], "fetched_at": None}
        key = tuple(config[k] for k in FIELDS)
        if key != self._key or self._at is None or not 0 <= now-self._at < 3600:
            self._key, self._at = key, now
            self._data = {"state": "unavailable", "periods": [], "fetched_at": None}
            try:
                payload = self.reader(config)
                receipt = self.clock()
                periods = parse(payload, config)
                if any(b.timestamp() > receipt and a.timestamp() < receipt+72*3600 for a,b,_ in periods):
                    count = len(payload["hourly"]["time"])
                    self._data = {"state": "ready" if len(periods)==count else "partial",
                                  "periods": periods, "fetched_at": receipt}
            except Exception:
                pass  # Never publish coordinates, response bodies or raw errors.
        return {**self._data, "periods": list(self._data["periods"])}
