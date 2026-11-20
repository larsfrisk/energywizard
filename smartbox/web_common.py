"""API som webben och mobilappen delar: sponsring och installationens språk.

register(app, role_of, open_setup) där role_of(request) ger 'owner'|'family'|'guest'|None och
open_setup() säger om startguiden pågår (inget lösenord valt än)."""
from fastapi import Request
from fastapi.responses import JSONResponse

import ew_settings
import i18n_routes
import sponsor


_saved_cache = {"t": 0.0, "v": None}


def week_saved(engine):
    """(besparing senaste 7 dygnen, valutasymbol) eller (None, "kr") om det inte går att räkna. Cachas i tio minuter."""
    import time
    if engine is None:
        return None, "kr"
    try:
        import nordpool
        sym = nordpool.cost_settings()["symbol"]
    except Exception:
        sym = "kr"
    if time.time() - _saved_cache["t"] < 600:
        return _saved_cache["v"], sym
    v = None
    try:
        import datetime as dt
        import zoneinfo

        import savings
        today = dt.datetime.now(zoneinfo.ZoneInfo("Europe/Stockholm")).date().isoformat()
        with engine.connect() as c:
            wk = savings.summarize_periods(savings.daily_rows(c, days=10), today)["week"]
        v = wk["saved_kr"] if wk["days"] >= 3 else None      # minst tre dygn med data, annars är siffran missvisande
    except Exception:
        v = None
    _saved_cache.update(t=time.time(), v=v)
    return v, sym


def register(app, role_of, open_setup=lambda: False, engine=None):
    @app.get("/api/sponsor")
    async def api_sponsor(request: Request, lang: str = ""):
        lang = lang or i18n_routes.default_language()
        if role_of(request) != "owner":
            st = sponsor.state(lang)
            st["show"] = False                       # påminnelsen är till ägaren, länken till alla
            return st
        saved, sym = week_saved(engine)
        return sponsor.state(lang, saved=saved, symbol=sym)

    @app.post("/api/sponsor/dismiss")
    async def api_sponsor_dismiss(request: Request):
        if role_of(request) != "owner":
            return JSONResponse({"detail": "Bara ägaren"}, status_code=403)
        sponsor.dismiss()
        return {"ok": True}

    @app.post("/api/sponsor/notice")
    async def api_sponsor_notice(request: Request):
        if role_of(request) != "owner":
            return JSONResponse({"detail": "Bara ägaren kan ändra det här"}, status_code=403)
        body = await request.json()
        sponsor.set_enabled(bool(body.get("enabled", True)))
        return {"ok": True, "enabled": sponsor.enabled()}

    @app.post("/api/setup/language")
    async def api_setup_language(request: Request):
        """Installationens språk (standard för alla enheter). I startguiden, eller av ägaren."""
        if not (open_setup() or role_of(request) == "owner"):
            return JSONResponse({"detail": "Bara ägaren kan ändra språket för hela installationen"}, status_code=403)
        body = await request.json()
        lang = str(body.get("language", ""))
        if lang not in i18n_routes.languages():
            return JSONResponse({"detail": "Okänt språk"}, status_code=400)
        ew_settings.update(language=lang)
        return {"ok": True, "language": lang}
