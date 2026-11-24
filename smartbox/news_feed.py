"""Fliken Nyheter: de utskickade veckobreven (samma text som i mejlet), hämtade från samlaren och cachade i fem minuter.

Publikt innehåll utan personuppgifter, så alla som är inloggade i appen eller webben får se det, oavsett roll. Når samlaren inte svarar
visas den senast hämtade listan (eller en tom).
"""
import time

import requests

import telemetry

_cache = {}
TTL_S = 300


def issues(lang: str, limit: int = 8, now=time.time, get=requests.get) -> list:
    lang = (lang or "en")[:2].lower()
    lang = lang if lang in ("sv", "en", "cs") else "en"
    hit = _cache.get(lang)
    if hit and now() - hit[0] < TTL_S:
        return hit[1]
    try:
        r = get(f"{telemetry.ENDPOINT}/news/issues", params={"lang": lang, "limit": limit}, timeout=8)
        data = (r.json() or {}).get("issues") if r.ok else None
        if isinstance(data, list):
            clean = [{"id": str(x.get("id", ""))[:20], "period": str(x.get("period", ""))[:60], "versions": str(x.get("versions", ""))[:40],
                      "items": [[str(a)[:200], str(b)[:1500]] for a, b in (x.get("items") or [])[:12]]} for x in data if isinstance(x, dict)]
            _cache[lang] = (now(), clean)
            return clean
    except Exception:
        pass
    return hit[1] if hit else []
