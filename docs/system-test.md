# Testa ditt system

Knappen **Testa ditt system** kontrollerar att batteriet faktiskt gör det EnergyWizard ber om. Den erbjuds som **sista steget i installationsguiden**, efter att installationen och alla val har sparats, och finns kvar under **System**. Idén kommer från Energy Pilot.

## Vad som händer

| Steg | Beställning | Godkänt när |
|---|---|---|
| Håll | batteriet ska stå still | effekten ligger under 150 W i två avläsningar i rad |
| Ladda | ladda med högst 1 kW | effekten är minst 200 W i två avläsningar i rad |
| Ladda ur | ladda ur med högst 1 kW | effekten är minst 200 W åt andra hållet i två avläsningar i rad |

Varje steg får högst två minuter och avslutas så fort det lyckats. Därefter sätts batteriet **alltid** tillbaka i sitt normala läge (auto), även om ett steg misslyckats. Om EnergyWizard startar om mitt under testet återställs batteriet vid nästa start.

Steg som inte går att prova hoppas över med en förklaring: laddning provas inte när batteriet är fullt (97 % eller mer), urladdning inte när laddnivån ligger nära reserven, och lägen som drivrutinen saknar provas inte.

## Säkerhet

- Testet kräver att batteriet står på **styr** i installationen. Står det på samarbete (ett annat system styr) eller bara läsning görs inget.
- Det skickar **riktiga kommandon även i skuggläge**, men bara från testet. All övrig styrning förblir i skuggläge. Du får en bekräftelseruta först.
- Högst 1 kW. EnergyWizards egen batteristyrning pausas medan testet pågår.
- Bara ägaren kan starta det.

## Om något inte fungerar

Resultatet visar vilket steg som misslyckades och vad som mättes. Knappen **Skicka resultatet till utvecklaren** skickar supportunderlaget (med en rad om testet) och ger en referens att skriva i ett ärende. Det är så vi får veta om en batteriförinställning (till exempel Sigenergy) inte fungerar på riktig hårdvara.

## Tekniskt

`smartbox/system_test.py` (logik, tester i `tests/test_system_test.py`). Webben begär testet via överstyrningen `system_test_request` och läser förloppet ur `system_test_status`; motorn kör testet i en egen tråd. `shadow.bypass()` är trådlokal.
