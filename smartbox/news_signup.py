"""Veckobrevet i appen och guiden: en valfri anmälan med e-post till EnergyWizards nyheter (torsdag kl 11).

Adressen skickas bara till samlaren (telemetry.ENDPOINT + /news/...), som mejlar en bekräftelselänk (dubbel opt-in). Här sparas bara
vad installationen behöver för att visa läget: adressen, installationens egen hemlighet för status och avbryt, och om raden på
första sidan är bortklickad. Inget hus-ID skickas med, så listan kan inte kopplas till telemetrin.
"""
import requests

import ew_settings
import telemetry

KEY = "news_signup"


class NewsError(Exception):
    """Ett fel med en text som går att visa för användaren."""


def valid_email(e) -> bool:
    """Samma enkla, linjära kontroll som samlaren (inga regex)."""
    if not isinstance(e, str) or not 6 <= len(e) <= 254 or e.count("@") != 1:
        return False
    if any(c.isspace() or ord(c) < 32 or c in '<>(),;:"\\[]' for c in e):
        return False
    local, domain = e.split("@")
    if not 1 <= len(local) <= 64 or ".." in e or local[0] == "." or local[-1] == ".":
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and not any(not l or len(l) > 63 or l[0] == "-" or l[-1] == "-" for l in labels) and len(labels[-1]) >= 2


def _saved() -> dict:
    d = ew_settings.get(KEY)
    return d if isinstance(d, dict) else {}


def state(refresh: bool = False) -> dict:
    """{status: none|pending|confirmed, email, dismissed}. Med refresh frågas samlaren om en väntande anmälan hunnit bekräftas."""
    d = _saved()
    dismissed = bool(d.get("dismissed"))
    status = d.get("status") or "none"
    if refresh and status == "pending" and d.get("token"):
        try:
            r = requests.get(f"{telemetry.ENDPOINT}/news/status", params={"t": d["token"]}, timeout=8)
            remote = (r.json() or {}).get("status") if r.ok else None
            if remote in ("confirmed", "pending"):
                if remote != status:
                    ew_settings.update(**{KEY: {**d, "status": remote}})
                status = remote
            elif remote == "none":                      # avregistrerad via länken i ett mejl
                ew_settings.update(**{KEY: {"dismissed": dismissed}})
                status, d = "none", {}
        except Exception:
            pass                                        # samlaren onåbar: visa det vi vet
    return {"status": status, "email": d.get("email") if status != "none" else None, "dismissed": dismissed}


def subscribe(email: str, lang: str) -> dict:
    email = str(email or "").strip().lower()
    if not valid_email(email):
        raise NewsError("Skriv en giltig e-postadress.")
    try:
        r = requests.post(f"{telemetry.ENDPOINT}/news/subscribe", json={"email": email, "lang": str(lang or "en")[:2]}, timeout=15)
    except Exception:
        raise NewsError("Kunde inte nå servern just nu. Försök igen om en stund.")
    if r.status_code == 429:
        raise NewsError("Vänta några minuter innan du ber om ett nytt bekräftelsemejl.")
    if r.status_code == 400:
        raise NewsError("Skriv en giltig e-postadress.")
    if not r.ok:
        raise NewsError("Kunde inte skicka bekräftelsemejlet. Försök igen senare.")
    j = r.json() or {}
    if j.get("already"):                                # redan anmäld och bekräftad: ingen ny hemlighet, ingen nytt mejl
        ew_settings.update(**{KEY: {"email": email, "status": "confirmed", "dismissed": True}})
        return {"status": "confirmed", "email": email, "already": True}
    ew_settings.update(**{KEY: {"email": email, "token": j.get("t"), "status": "pending", "dismissed": True}})
    return {"status": "pending", "email": email}


def cancel() -> dict:
    d = _saved()
    if d.get("token"):
        try:
            requests.post(f"{telemetry.ENDPOINT}/news/cancel", json={"t": d["token"]}, timeout=10)
        except Exception:
            raise NewsError("Kunde inte nå servern just nu. Försök igen om en stund.")
    ew_settings.update(**{KEY: {"dismissed": True}})
    return {"status": "none", "email": None}


def dismiss() -> dict:
    ew_settings.update(**{KEY: {**_saved(), "dismissed": True}})
    return state()
