"""Märken som körs hos installationerna (anonym telemetri) -> docs/data/utrustning.json för GitHub Pages.

    TELEMETRY_STATS_URL=... TELEMETRY_STATS_TOKEN=... python3 scripts/export_public_equipment.py

Bara tillverkarnamn och antal per kategori, aldrig modeller, husidentifierare eller enheter. Ett märke tas bara med om
det finns i listan nedan (kända tillverkare). Integrationsförfattare, utvecklarkort och felvalda enheter (rökvarnare,
gräsklippare ...) hamnar aldrig på den publika sidan."""
import json, os, re, sys, urllib.request
from datetime import date
from pathlib import Path

# (regex på tillverkaren, visningsnamn). Samma familjer som telemetrisidan i webben (webdashboard/static/app.js).
BRANDS = [(r"^nibe|^(f|s|vvm|smo)\s?\d", "NIBE"), (r"^(å|š)koda", "Škoda"), (r"^kia", "Kia"), (r"^volvo", "Volvo"),
          (r"^(volkswagen|vw\b)", "Volkswagen"), (r"^mercedes", "Mercedes-Benz"), (r"^huawei", "Huawei"),
          (r"^mitsubishi", "Mitsubishi Electric"), (r"^daikin", "Daikin"), (r"^ivt", "IVT"), (r"^sensibo", "Sensibo"),
          (r"^gecko", "Gecko"), (r"^balboa", "Balboa"), (r"^bestway", "Bestway"), (r"^solaredge", "SolarEdge"),
          (r"^sungrow|^ftw-sungrow", "Sungrow"), (r"^goodwe", "GoodWe"), (r"^fronius|^ftw-fronius", "Fronius"),
          (r"^solax", "SolaX"), (r"^growatt|^ftw-growatt", "Growatt"), (r"^ferroamp", "Ferroamp"), (r"^solis", "Solis"),
          (r"^hypontech", "Hypontech"), (r"^saj|^ftw-saj", "SAJ"), (r"^foxess", "FoxESS"), (r"^victron", "Victron"),
          (r"^sonnen|^ftw-sonnen", "Sonnen"), (r"^sofar", "Sofar"), (r"^deye|^ftw-deye", "Deye"), (r"^alphaess", "AlphaESS"),
          (r"^givenergy", "GivEnergy"), (r"^sigenergy|^ftw-sigenergy", "Sigenergy"), (r"^solinteg|^ftw-solinteg", "Solinteg"),
          (r"^zonneplan", "Zonneplan"), (r"^easee", "Easee"), (r"^zaptec", "Zaptec"), (r"^wallbox", "Wallbox"),
          (r"^charge amps", "Charge Amps"), (r"^starcharge", "StarCharge"), (r"^garo", "Garo"), (r"^go-e", "go-e"),
          (r"^cfos", "cFos"), (r"^tesla", "Tesla"), (r"^nissan", "Nissan"), (r"^audi", "Audi"), (r"^byd", "BYD"),
          (r"^mg$", "MG"), (r"^renault", "Renault"), (r"^bmw", "BMW"), (r"^mazda", "Mazda"), (r"^cupra", "Cupra"),
          (r"^zeekr", "Zeekr"), (r"^polestar", "Polestar"), (r"^myvauxhall|^vauxhall", "Vauxhall"),
          (r"^tibber", "Tibber"), (r"^homewizard", "HomeWizard"), (r"^iammeter", "IAMMETER"), (r"^remne", "Remne"),
          (r"^perific", "Perific"), (r"^p1reader", "P1reader"), (r"^emporia", "Emporia"), (r"^thermia", "Thermia")]
# Vilka märken som får visas i vilken kategori (ett märke i fel kategori är en felvald enhet).
ALLOWED = {
    "heatpump": {"NIBE", "Mitsubishi Electric", "Daikin", "IVT", "Sensibo", "Thermia"},
    "spa": {"Gecko", "Balboa", "Bestway"},
    "solar": {"SolarEdge", "Sungrow", "GoodWe", "Fronius", "Huawei", "SolaX", "Growatt", "Ferroamp", "Solis", "Hypontech", "SAJ", "FoxESS", "Victron", "Zonneplan"},
    "battery": {"Sungrow", "Solis", "Victron", "Sonnen", "Fronius", "Growatt", "SolaX", "Sofar", "Deye", "AlphaESS", "SolarEdge", "Huawei", "GivEnergy", "Sigenergy", "Solinteg", "Ferroamp", "FoxESS"},
    "charger": {"Easee", "Zaptec", "Wallbox", "Charge Amps", "StarCharge", "Garo", "go-e", "cFos"},
    "car": {"Tesla", "Volvo", "Volkswagen", "Škoda", "Nissan", "Kia", "Audi", "Mercedes-Benz", "BYD", "MG", "Renault", "BMW", "Mazda", "Cupra", "Zeekr", "Polestar", "Vauxhall"},
    "meter": {"Tibber", "HomeWizard", "Sonnen", "Victron", "Fronius", "IAMMETER", "Remne", "Perific", "P1reader", "Emporia", "Zonneplan", "AlphaESS", "GivEnergy", "Growatt", "Sungrow", "Solis"},
}
# Drivrutiner utan märke i nyckeln (k = "driver" utan @): driver -> (kategori, visningsnamn)
DRIVER_ONLY = {("heatpump", "thermia_husdata"): "Thermia", ("heatpump", "nibe_local"): "NIBE", ("heatpump", "myuplink"): "NIBE",
               ("solar", "solaredge"): "SolarEdge", ("car", "tesla"): "Tesla", ("car", "nissan"): "Nissan",
               ("charger", "easee"): "Easee", ("spa", "gecko"): "Gecko", ("spa", "balboa"): "Balboa",
               ("solar", "ferroamp_modbus"): "Ferroamp", ("battery", "ferroamp_modbus"): "Ferroamp"}


def family(cat, key):
    drv, _, rest = key.partition("@")
    if not rest and not drv.startswith("ftw-"):
        return DRIVER_ONLY.get((cat, drv))
    maker = (rest.split("#")[0] if rest else drv).strip().lower()      # ftw-<märke> = FTW-drivrutin utan märkesdel
    for rx, name in BRANDS:
        if re.search(rx, maker):
            return name if name in ALLOWED.get(cat, ()) else None
    return None


def build(stats):
    out = {}
    for cat in ALLOWED:
        tot = {}
        for key, n in (stats.get("equipment", {}).get(cat) or {}).items():
            f = family(cat, key)
            if f:
                tot[f] = tot.get(f, 0) + n
        out[cat] = sorted(({"name": k, "n": v} for k, v in tot.items()), key=lambda x: (-x["n"], x["name"]))
    return {"updated": date.today().isoformat(), "installations": stats.get("active"), "equipment": out}


if __name__ == "__main__":
    req = urllib.request.Request(os.environ["TELEMETRY_STATS_URL"], headers={"X-Stats-Token": os.environ["TELEMETRY_STATS_TOKEN"]})
    stats = json.load(urllib.request.urlopen(req, timeout=20))
    dest = Path(__file__).resolve().parent.parent / "docs" / "data" / "utrustning.json"
    dest.write_text(json.dumps(build(stats), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("skrev", dest, file=sys.stderr)
