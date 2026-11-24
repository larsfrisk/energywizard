# Veckobrevet (nyheter varje torsdag kl 11)

Ett valfritt veckobrev för dem som själva skrivit in sin e-postadress i EnergyWizard (appens första sida, Inställningar › Appen,
webbens installationsguide eller System). Personuppgiftsansvarig är EnergyWizards skapare.

## Hur det hänger ihop

- **Fliken Nyheter:** samma veckobrev ligger som en egen flik i appen och webben, för alla roller (även familj och gäst). Texten hämtas
  från samlaren (`GET /news/issues`, publikt, ingen persondata) och en utgåva syns först när dess torsdag kl 11 passerat.

- **Anmälan:** appen/webben anropar `smartbox/news_signup.py`, som postar adress + språk till samlaren
  (`telemetry-collector/news.py`). Inget hus-ID skickas, så listan kan inte kopplas till telemetrin.
- **Dubbel opt-in:** samlaren mejlar en bekräftelselänk. Först när den klickats räknas adressen. Samma adress kan få ett nytt
  bekräftelsemejl högst var tionde minut och samlaren skickar högst 60 sådana mejl per timme (skydd mot missbruk).
- **Avregistrering:** länk i varje brev (och `List-Unsubscribe` med ett-klick). Raden raderas helt. Appen kan också avsluta.
- **Utskick:** `telemetry-collector/news_send.py` i samlarens container. Skickar bara torsdag kl 11 svensk tid, högst en gång per
  (utgåva, adress), och inget om det saknas en veckofil eller ligger en `.hold` bredvid den.

## Veckofilen

En JSON-fil per ISO-vecka, `YYYY-wNN.json` (exempel: `issues/2026-w48.json`), med sammanfattningen på sv, en och cs. Filen läggs i
samlarens datavolym, `/data/news/`, utan att bygga om något:

    docker exec telemetry-collector mkdir -p /data/news
    docker cp newsletter/issues/2026-w48.json telemetry-collector:/data/news/

Sammanfattningen skrivs ur `ha-addon/smartbox/CHANGELOG.md` (posterna sedan förra torsdagen), i vanligt språk, högst 7 poster. Det finns inget utkastsmejl: filen som ligger i `/data/news/` går ut av sig själv torsdag kl 11, så den ska vara kontrollerad när den läggs dit.
Rubrik + 1-3 meningar per post. Skriv inget som inte stämmer: ej provat på riktig utrustning ska stå.

## Provutskick och spärr

    docker exec telemetry-collector python news_send.py /data/news/2026-w48.json                        # torrkörning
    docker exec telemetry-collector python news_send.py /data/news/2026-w48.json --go --now --only a@b.se  # provmejl till en bekräftad adress
    touch /data/news/2026-w48.json.hold                                                                # stoppa veckans utskick

## Cron (på värden, UTC)

`~/scripts/ew_news_send.sh` körs torsdagar kl 09 och 10 UTC; bara körningen där klockan i Stockholm är 11 skickar (sommar- och vintertid).
