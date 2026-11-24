"""Veckobrevets utseende (tabell-HTML, 600 px) och text. Innehållet kommer ur en veckofil (issue-JSON), texterna runt om ur LABELS.

Veckofilens format (ett språk kan saknas, då används engelska):
  {"id": "2026-w48", "period": {"sv": "17–24 november 2026", ...}, "versions": "1.2.153–1.2.178",
   "subject": {"sv": "...", "en": "...", "cs": "..."}, "preheader": {...},
   "items": {"sv": [["Rubrik", "Text"], ...], "en": [...], "cs": [...]}}
"""
import html

F = "font-family:Inter,-apple-system,'Segoe UI',Roboto,Arial,sans-serif"
e = html.escape
CHANGELOG = "https://github.com/murre87/energywizard/blob/main/ha-addon/smartbox/CHANGELOG.md"
SITE = "https://murre87.github.io/energywizard/"
SPONSOR = "https://github.com/sponsors/murre87"
PROJECTS = [("Familjetavlan", "https://github.com/murre87/familjetavla"), ("ProfitAlgos", "https://profitalgos.com/"), ("Strategy Library", "https://agent.profitalgos.com/")]
LABELS = {
 "sv": dict(kick="Veckans nyheter", h="Det här är nytt i EnergyWizard", how="Så här uppdaterar du",
  how_t="I Home Assistant: Inställningar › Tillägg › EnergyWizard › Uppdatera. Kör du med Docker hämtar du nya bilder som vanligt.",
  more="Alla ändringar i detalj", site="EnergyWizards kunskapsbank",
  sponsor="EnergyWizard är gratis och öppet. Om det sparar pengar hemma hos dig kan du hålla det så med en sponsring.", sponsor_btn="Sponsra EnergyWizard",
  proj_h="Fler projekt av EnergyWizards skapare",
  proj={"Familjetavlan": "Familjens tavla för skärmen hemma, med Home Assistant: kalender, väder, elpris och mer.",
        "ProfitAlgos": "Handelsalgoritmer för ProRealTime och IG, med live-resultat.",
        "Strategy Library": "Över 10 000 öppna strategier med färdig ProRealTime-kod."},
  why="Du får det här för att du själv har angett din e-postadress i EnergyWizard för att få de senaste nyheterna.", unsub="Avsluta prenumerationen",
  gdpr="Personuppgiftsansvarig är EnergyWizards skapare. Din e-postadress används bara för det här veckobrevet, lämnas inte vidare och raderas när du avslutar prenumerationen."),
 "en": dict(kick="This week's news", h="What's new in EnergyWizard", how="How to update",
  how_t="In Home Assistant: Settings › Add-ons › EnergyWizard › Update. If you run Docker, pull the new images as usual.",
  more="All changes in detail", site="EnergyWizard knowledge base",
  sponsor="EnergyWizard is free and open. If it saves you money at home, you can help keep it that way with a sponsorship.", sponsor_btn="Sponsor EnergyWizard",
  proj_h="More projects by EnergyWizard's creator",
  proj={"Familjetavlan": "A family dashboard for the screen at home, with Home Assistant: calendar, weather, electricity price and more.",
        "ProfitAlgos": "Trading algorithms for ProRealTime and IG, with live results.",
        "Strategy Library": "Over 10,000 open strategies with ready-made ProRealTime code."},
  why="You are receiving this because you entered your email address in EnergyWizard to get the latest news.", unsub="Unsubscribe",
  gdpr="The data controller is EnergyWizard's creator. Your email address is used only for this weekly letter, is not passed on, and is deleted when you unsubscribe."),
 "cs": dict(kick="Novinky týdne", h="Co je nového v EnergyWizard", how="Jak aktualizovat",
  how_t="V Home Assistant: Nastavení › Doplňky › EnergyWizard › Aktualizovat. Pokud používáte Docker, stáhněte nové image jako obvykle.",
  more="Všechny změny podrobně", site="Znalostní báze EnergyWizard",
  sponsor="EnergyWizard je zdarma a otevřený. Pokud vám doma šetří peníze, můžete ho podpořit sponzorstvím.", sponsor_btn="Podpořit EnergyWizard",
  proj_h="Další projekty tvůrce EnergyWizard",
  proj={"Familjetavlan": "Rodinná nástěnka pro obrazovku doma, s Home Assistant: kalendář, počasí, cena elektřiny a další.",
        "ProfitAlgos": "Obchodní algoritmy pro ProRealTime a IG, s živými výsledky.",
        "Strategy Library": "Více než 10 000 otevřených strategií s hotovým kódem pro ProRealTime."},
  why="Tento e-mail dostáváte, protože jste v EnergyWizard sami zadali svou e-mailovou adresu, abyste dostávali nejnovější novinky.", unsub="Odhlásit odběr",
  gdpr="Správcem osobních údajů je tvůrce EnergyWizard. Vaše e-mailová adresa se používá pouze pro tento týdenní zpravodaj, nepředává se dál a po odhlášení se smaže."),
}


def pick(d, lang, default=""):
    """Värde per språk ur en {språk: värde}-karta, annars engelska, annars första som finns."""
    if not isinstance(d, dict):
        return default
    return d.get(lang) or d.get("en") or next(iter(d.values()), default)


def subject(issue, lang):
    return pick(issue.get("subject"), lang, "EnergyWizard")


def _btn(url, label, bg="#04ce78", fg="#04210f"):
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" style="display:inline-table;margin:4px 6px 4px 0"><tr><td style="background:{bg};border-radius:12px">'
            f'<a href="{url}" style="display:inline-block;padding:12px 20px;{F};font-size:15px;font-weight:700;color:{fg};text-decoration:none">{e(label)}</a></td></tr></table>')


def build_html(issue, lang, unsub_url):
    L = LABELS.get(lang) or LABELS["en"]
    lang = lang if lang in LABELS else "en"
    items = pick(issue.get("items"), lang, [])
    period = pick(issue.get("period"), lang)
    sub = " · ".join(x for x in (period, ("version " + issue["versions"]) if issue.get("versions") else "") if x)
    rows = "".join(f'<tr><td style="padding:0 26px 14px;{F}"><div style="font-size:16px;font-weight:700;color:#0f172a;margin-bottom:3px">{e(a)}</div>'
                   f'<div style="font-size:14px;line-height:1.55;color:#475569">{e(b)}</div></td></tr>' for a, b in items)
    proj = "".join(f'<tr><td style="padding:6px 0;{F};font-size:13px;line-height:1.5;color:#475569"><a href="{u}" style="color:#02915a;font-weight:700;text-decoration:none">{e(n)}</a> &middot; {e(L["proj"][n])}</td></tr>' for n, u in PROJECTS)
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>{e(subject(issue, lang))}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9"><span style="display:none;max-height:0;overflow:hidden;opacity:0">{e(pick(issue.get("preheader"), lang))}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9"><tr><td align="center" style="padding:24px 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px"><tr><td style="padding:0 6px 12px;{F};font-size:22px;font-weight:700;color:#0f172a">Energy<span style="color:#04ce78">Wizard</span></td></tr>
<tr><td style="background:#fff;border:1px solid #e8eef3;border-radius:18px;overflow:hidden"><table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="padding:28px 26px 14px;{F}"><div style="font-size:12px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#02915a">{e(L["kick"])}</div>
<div style="font-size:28px;line-height:1.2;font-weight:800;color:#0f172a;margin:6px 0 6px">{e(L["h"])}</div>
<div style="font-size:13px;color:#64748b">{e(sub)}</div></td></tr>
{rows}
<tr><td style="padding:6px 26px 14px;{F}"><div style="border:1px solid #bff0d8;border-radius:16px;padding:16px 20px;background:#e7f9f0">
<div style="font-size:15px;font-weight:700;color:#063a22;margin-bottom:4px">{e(L["how"])}</div><div style="font-size:14px;line-height:1.5;color:#063a22">{e(L["how_t"])}</div></div></td></tr>
<tr><td style="padding:0 26px 18px;{F}">{_btn(CHANGELOG, L["more"])}{_btn(SITE, L["site"], "#0f172a", "#ffffff")}</td></tr>
<tr><td style="padding:0 26px 22px;{F};font-size:13px;line-height:1.5;color:#475569;border-top:1px solid #eef2f6"><div style="padding-top:16px">{e(L["sponsor"])}</div><div style="padding-top:8px">{_btn(SPONSOR, L["sponsor_btn"], "#f1f5f9", "#0f172a")}</div></td></tr>
</table></td></tr>
<tr><td style="padding:18px 10px 0;{F}"><div style="font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#64748b;padding-bottom:4px">{e(L["proj_h"])}</div><table role="presentation" width="100%" cellpadding="0" cellspacing="0">{proj}</table></td></tr>
<tr><td style="padding:14px 10px 0;{F};font-size:12px;line-height:1.6;color:#64748b">{e(L["why"])} <a href="{e(unsub_url)}" style="color:#64748b">{e(L["unsub"])}</a><br><br>{e(L["gdpr"])}</td></tr>
</table></td></tr></table></body></html>
'''


def build_text(issue, lang, unsub_url):
    L = LABELS.get(lang) or LABELS["en"]
    lines = [subject(issue, lang), ""]
    for a, b in pick(issue.get("items"), lang, []):
        lines += [a, b, ""]
    lines += [L["how"] + ": " + L["how_t"], "", L["more"] + ": " + CHANGELOG, L["site"] + ": " + SITE, "", L["sponsor"], SPONSOR, "", L["proj_h"]]
    lines += [f"{n}: {u}" for n, u in PROJECTS]
    lines += ["", L["why"], L["unsub"] + ": " + unsub_url, "", L["gdpr"]]
    return "\n".join(lines) + "\n"
