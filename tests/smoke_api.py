"""Rökprov av webbens alla GET-vägar (#562). Körs i en egen process av tests/test_api_smoke.py: startar webbappen mot en riktig
Postgres med motorns egna tabeller (utan Home Assistant) och anropar varje /api/-väg med inloggning.

Godkänt: 200, och 401/403/404/409 (användaren eller installationen saknar något) samt 502/503 (en tjänst bakom, t.ex. Home
Assistant, svarar inte). Underkänt: 500 eller ett oväntat undantag, alltså ett fel i vår kod. Skriver de underkända vägarna och
slutar med kod 1."""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("TEST_DB_HOST", "localhost")
PORT = os.environ.get("PGPORT", "5432")
USER, PASSWORD = os.environ.get("POSTGRES_USER", "postgres"), os.environ.get("POSTGRES_PASSWORD", "test")
DB = "smartbox_smoke"

import psycopg  # noqa: E402

admin = psycopg.connect(f"host={HOST} port={PORT} user={USER} password={PASSWORD} dbname=postgres", autocommit=True)
if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone():
    admin.execute(f"CREATE DATABASE {DB}")
admin.close()

os.environ.update(DASHBOARD_PASSWORD="smoketest", POSTGRES_USER=USER, POSTGRES_PASSWORD=PASSWORD, POSTGRES_DB=DB,
                  POSTGRES_HOST=HOST, POSTGRES_PORT=PORT, PGPORT=PORT, TELEMETRY_STATS_URL="")
sys.path[:0] = [str(ROOT / "webdashboard"), str(ROOT / "smartbox")]
os.chdir(ROOT / "webdashboard")

import requests  # noqa: E402


class _NoNetwork(requests.ConnectionError):
    pass


def _no_network(*a, **k):
    raise _NoNetwork("inget nätverk i rökprovet")


for _n in ("get", "post", "put", "delete", "request", "head", "patch"):
    setattr(requests, _n, _no_network)
requests.Session.request = lambda self, *a, **k: _no_network()

import logger  # noqa: E402
import nordpool  # noqa: E402
import settings  # noqa: E402
import weather  # noqa: E402

for init in (logger.init_log_db, logger.init_overrides_db, logger.init_load_breakdown_db, nordpool.init_db, settings.init_settings_db,
             weather.init_weather_db):
    init()

# En rad data och dagens elpriser, så att vägarna går förbi sitt "ingen data än" (Ekonomi-felet #562 låg bakom den kontrollen)
with logger.get_db() as _c:
    _c.execute("""INSERT INTO sensor_log (timestamp, price, indoor_temp, outdoor_temp, water_temp, net_power, compressor_running, active_mode)
                  VALUES (now(), 1.5, 21.0, 2.0, 55.0, 800, 1, 'CHEAP') ON CONFLICT (timestamp) DO NOTHING""")
    _c.execute("""INSERT INTO elpriser (time_start, sek_per_kwh)
                  SELECT g, 1.0 + (extract(hour FROM g))::numeric / 20 FROM generate_series(date_trunc('day', now()) - interval '1 day',
                  date_trunc('day', now()) + interval '2 days', interval '15 minutes') g ON CONFLICT (time_start) DO NOTHING""")
mod = importlib.import_module("app")
import asyncio  # noqa: E402
import json as _json  # noqa: E402


def call(method, path, body=None, cookie=None):
    """Anropar ASGI-appen direkt (ingen testklient: starlettes TestClient kräver ett paket som skiljer mellan versioner)."""
    raw = _json.dumps(body).encode() if body is not None else b""
    headers = [(b"host", b"smoke"), (b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": headers, "server": ("smoke", 80), "client": ("127.0.0.1", 1), "scheme": "http", "root_path": ""}
    out = {"status": None, "headers": []}
    sent = [False]

    async def receive():
        if not sent[0]:
            sent[0] = True
            return {"type": "http.request", "body": raw, "more_body": False}
        await asyncio.sleep(3600)

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"], out["headers"] = msg["status"], msg["headers"]

    async def run():
        try:
            await asyncio.wait_for(mod.app(scope, receive, send), timeout=60)
        except asyncio.TimeoutError:
            out["status"] = "timeout (60 s)"
        except Exception:
            pass                                    # Starlette skickar 500 och kastar sedan om felet; statusen är det som räknas
    asyncio.run(run())
    return out


_login = call("POST", "/api/login", {"user": "admin", "password": "smoketest"})
assert _login["status"] == 200, "inloggningen i rökprovet"
COOKIE = "; ".join(v.decode().split(";")[0] for k, v in _login["headers"] if k == b"set-cookie")
paths = sorted({r.path for r in mod.app.routes if "GET" in getattr(r, "methods", set()) and r.path.startswith("/api/") and "{" not in r.path})
OK = {200, 401, 403, 404, 409, 502, 503}
bad = []
for path in paths:
    try:
        code = call("GET", path, cookie=COOKIE)["status"]
    except Exception as e:                      # undantag som inte blev ett svar
        code = f"undantag {type(e).__name__}: {e}"
    if code not in OK:
        bad.append((path, code))
print(f"{len(paths)} vägar provade")
for path, code in bad:
    print(f"FEL {code} {path}")
sys.exit(1 if bad or len(paths) < 40 else 0)
