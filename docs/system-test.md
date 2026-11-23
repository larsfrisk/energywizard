# Testa ditt system

**Testa ditt system** kontrollerar att allt du valt i installationen fungerar. Det erbjuds som **sista steget i installationsguiden**, efter att installationen och alla val har sparats, och finns kvar under **System**. Idén kommer från Energy Pilot.

Testet har två delar. Du väljer själv vilka styrtester som ska köras, och läsningarna körs alltid.

## Del A: läsningar (inga kommandon, tar sekunder)

För allt du valt (värmepump, spabad, solceller, batteri, elmätare, elbilar och deras laddboxar, maskiner, väder) kontrolleras varje entitet:

| Kontroll | Fel eller varning |
|---|---|
| Finns i Home Assistant | fel: "Finns inte" (felstavad, omdöpt eller borttagen) |
| Svarar | fel: `unavailable`; varning: okänt värde |
| Värdet är ett tal där tal väntas | fel om det är text |
| Rimligt intervall | varning: temperatur utanför −60 till 130 °C, laddnivå utanför 0 till 100 |
| Färsk | varning om temperatur-, effekt- eller laddnivågivare inte uppdaterats på 90 minuter |

Dessutom läses drivrutinerna direkt (värmepump, spabad, laddbox, batteri), så att det som inte går via Home Assistant (till exempel Modbus) också kontrolleras. Några sammanhangsregler fångar kända fallgropar: en laddbox utan effektsensor ger 0 kr i kostnadskortet, och ett batteri eller spabad utan temperatur- eller laddnivåsensor varnas.

## Del B: styrtester (valfria, per enhet)

| Test | Vad som händer | Godkänt när |
|---|---|---|
| Batteri | håll, ladda och ladda ur med högst 1 kW, högst två minuter per steg | effekten följer beställningen i två avläsningar i rad |
| Värmepump | rumsbörvärdet ändras 0,5 °C | värdet läses tillbaka, och sätts sedan tillbaka |
| Spabad | målvärdet ändras 0,5 °C | värdet läses tillbaka, och sätts sedan tillbaka |
| Laddbox | 6 A i högst 90 sekunder, bara om bilen är inkopplad och inte laddar | ström kommer, sedan 0 A igen |

Värmepumpen provas bara om dess börvärde går att **läsa tillbaka** (annars går det inte att återställa), och laddboxen bara om bilen står inkopplad och inte laddar.

## Säkerhet

- Allt som ändras skrivs först i en återställningslogg och sätts **alltid** tillbaka, även om ett test misslyckas eller EnergyWizard startar om mitt i (då återställs det vid nästa start).
- Batteritestet kräver att batteriet står på **styr**. Står det på samarbete (ett annat system styr) görs inget.
- Styrtesterna skickar **riktiga kommandon även i skuggläge**, men bara från testet och bara för det du kryssat i. All övrig styrning förblir i skuggläge. Du får en bekräftelseruta först. Väljer du inga styrtester körs bara läsningarna.
- EnergyWizards egen batteristyrning pausas medan testet pågår. Bara ägaren kan starta det.

## Om något inte fungerar

Resultatet visar per enhet vad som fungerade, varnar eller misslyckades och varför. *Skicka resultatet till utvecklaren* skickar supportunderlaget (med en rad om testet) och ger en referens att skriva i ett ärende. Så får vi veta om en förinställning (till exempel Sigenergy) inte fungerar på riktig hårdvara.

## Tekniskt

`smartbox/system_check.py` (del A, ren logik) och `smartbox/system_test.py` (del B och körningen), med tester i `tests/test_system_check.py` och `tests/test_system_test.py`. Webben begär testet via överstyrningen `system_test_request` (JSON med valda test-id) och läser förloppet ur `system_test_status`. Motorn kör testet i en egen tråd. `shadow.bypass()` är trådlokal.
