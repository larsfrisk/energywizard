"""Sponsring: länken som finns i alla gränssnitt, och en vänlig påminnelse en gång i månaden.

Påminnelsen är på som standard och kan stängas av i inställningarna. Den visas först när
installationen har använts en vecka, och högst en gång per kalendermånad: som en ruta i webben
och appen (tills den stängs) och som en notis i Home Assistant.
"""
from datetime import datetime, timedelta

import ew_settings

URL = "https://github.com/sponsors/murre87"
GRACE_DAYS = 7

TITLE = {"sv": "Gillar du EnergyWizard? ❤️", "en": "Do you like EnergyWizard? ❤️"}
TEXT = {
    "sv": ("Hej! Jag hoppas att EnergyWizard gör nytta hemma hos dig. Jag bygger det på min fritid, och mycket av "
           "koden skrivs, granskas och testas tillsammans med Claude, en AI som kostar pengar för varje timme den "
           "arbetar. De senaste veckorna har det kostat runt 1 000 € att utveckla EnergyWizard, och allt delas gratis "
           "med alla som använder det. Om du tycker att projektet är värt det blir jag väldigt tacksam för en "
           "sponsring, stor som liten. Det håller EnergyWizard gratis och öppet för alla. Tack för att du är med!"),
    "en": ("Hi! I hope EnergyWizard is making a difference in your home. I build it in my spare time, and much of "
           "the code is written, reviewed and tested together with Claude, an AI that costs money for every hour it "
           "works. Over the past few weeks, developing EnergyWizard has cost around €1,000, and everything is shared "
           "for free with everyone who uses it. If you think the project is worth it, I would be very grateful for a "
           "sponsorship, big or small. It keeps EnergyWizard free and open for everyone. Thank you for being part of it!"),
}
# Ett extra utskick utöver månadens: visas en gång till även för den som redan sett/fått månadens påminnelse
# (2026-11-06, meddelandet om utvecklingskostnaden). Avstängd påminnelse och första veckan respekteras som vanligt.
CAMPAIGN = {"2026-11": "2026-11-kostnad"}
BUTTON = {"sv": "Sponsra EnergyWizard", "en": "Sponsor EnergyWizard"}

# Sparbaserad påminnelse (2026-11-20): när installationen vet hur mycket den sparat sista veckan sägs det först,
# och förslaget blir en konkret summa. Utan sparsiffra (för lite data) visas den vanliga texten som förut. Är
# besparingen under SAVED_MIN visas ingen ruta alls: då finns inget värde att peka på än.
SAVED_MIN = 50
VALUE_TEXT = {
    "sv": ("EnergyWizard har sparat dig {saved} {sym} den senaste veckan. Jag bygger det på min fritid och delar det "
           "gratis. Om det är värt något för dig håller en sponsring på runt 10 USD i månaden det gratis och öppet "
           "för alla. Stor som liten summa gör skillnad, och du kan sluta när du vill. Tack för att du är med!"),
    "en": ("EnergyWizard has saved you {saved} {sym} over the past week. I build it in my spare time and share it for "
           "free. If it is worth something to you, a sponsorship of around 10 USD a month keeps it free and open for "
           "everyone. Any amount helps, and you can stop whenever you like. Thank you for being part of it!"),
}
# Alternativ till GitHub Sponsors för den som inte har GitHub-konto (Buy Me a Coffee, Ko-fi). Tomt tills kontot finns:
# då visas ingen extra knapp. Fyll i adressen här och i .github/FUNDING.yml.
ALT_URL = ""
ALT_BUTTON = {"sv": "Ge utan GitHub-konto", "en": "Give without a GitHub account"}


def _month(now):
    m = now.strftime("%Y-%m")
    return CAMPAIGN.get(m, m)


def _installed_at(now):
    st = ew_settings.load()
    raw = st.get("installed_at")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    try:
        ew_settings.update(installed_at=now.isoformat())
    except OSError:
        pass
    return now


def enabled() -> bool:
    return ew_settings.get("sponsor_notice", True) is not False


def set_enabled(on: bool):
    ew_settings.update(sponsor_notice=bool(on))


def _due(now, key):
    if not enabled():
        return False
    if now - _installed_at(now) < timedelta(days=GRACE_DAYS):
        return False
    return ew_settings.get(key) != _month(now)


def _fmt_saved(v) -> str:
    return f"{int(round(v)):,}".replace(",", " ")


def state(lang="sv", now=None, saved=None, symbol="kr") -> dict:
    """Vad webben och appen ska visa. saved: besparingen senaste veckan i installationens valuta (None = okänd)."""
    now = now or datetime.now()
    lang = lang if lang in TEXT else "en"
    show = _due(now, "sponsor_seen_month")
    text = TEXT[lang]
    if saved is not None:
        if saved < SAVED_MIN:
            show = False
        else:
            text = VALUE_TEXT[lang].format(saved=_fmt_saved(saved), sym=symbol)
    return {"url": URL, "enabled": enabled(), "show": show, "title": TITLE[lang], "text": text, "button": BUTTON[lang],
            "alt_url": ALT_URL, "alt_button": ALT_BUTTON[lang]}


def dismiss(now=None):
    """Rutan är stängd för den här månaden."""
    ew_settings.update(sponsor_seen_month=_month(now or datetime.now()))


def send_ha_notice(call_service, lang="sv", now=None) -> bool:
    """Skickar månadens notis till Home Assistant (en gång per månad). True om den skickades."""
    now = now or datetime.now()
    if not _due(now, "sponsor_ha_month"):
        return False
    lang = lang if lang in TEXT else "en"
    ok = call_service("persistent_notification", "create", {
        "notification_id": "energywizard_sponsor",
        "title": TITLE[lang],
        "message": f"{TEXT[lang]}\n\n[{BUTTON[lang]}]({URL})",
    })
    if ok:
        ew_settings.update(sponsor_ha_month=_month(now))
    return bool(ok)
