# EnergyWizard-kort för Home Assistant

Tre kort som visar EnergyWizard direkt i Home Assistant: **Hemmet** (energiflöde, elpris med plan, bilar), **Värme** (termostatratt, varmvatten, billiga och dyra pass) och **Bil** (laddnivå och planerade pass över elpriset).
De ser ut som appen och fungerar likadant för **HA-tillägget** och för **Docker**, eftersom de bara läser en sensor,
`sensor.energywizard_kort`, som EnergyWizard publicerar. Kortet når aldrig EnergyWizards egen webb och behöver ingen inloggning.

## Krav

- EnergyWizard med kortsensorn (1.2.125 eller senare). Kontrollera i HA: Utvecklarverktyg → Tillstånd →
  sök `energywizard_kort`. Sensorn uppdateras varje minut.
- Home Assistant 2024.1 eller senare.

## Installera

**Marknadsplatsen i Home Assistant (HA 2026.11 eller senare, enligt andra integrationers README, ej provat här)**
Öppna Inställningar → Marknadsplats, lägg till `https://github.com/murre87/energywizard` som eget arkiv (kategori Dashboard) och installera *EnergyWizard cards*. Befintliga HACS-installationer ska flyttas över automatiskt.

**HACS (HA 2026.10 och äldre)**
1. HACS → ⋮ → Anpassade arkiv → lägg till `https://github.com/murre87/energywizard`, kategori **Dashboard**.
2. Sök efter *EnergyWizard cards* och installera. Det är samma arkiv som EnergyWizard själv; HACS hämtar bara `dist/energywizard-cards.js`.
3. Ladda om webbläsaren (Ctrl+F5).

**Manuellt**
1. Kopiera `dist/energywizard-cards.js` till `/config/www/`.
2. Inställningar → Dashboards → ⋮ → Resurser → lägg till `/local/energywizard-cards.js` som *JavaScript-modul*.

## Lägg till korten

```yaml
type: custom:energywizard-house-card
entity: sensor.energywizard_kort   # valfritt, det här är standard
title: Hemmet                      # valfritt
tab: now                           # now | plan | cars, startflik (valfritt)
language: sv                       # sv | en, annars HA:s språk
```

**Hemmet** har tre flikar:

- **Nu**: sol, elnät, hemmet och det som drar el, med rörliga prickar dit elen går, och varför motorn gör som den gör.
- **Plan**: dygnets elpris kvart för kvart som en klocka (som i appen) eller som staplar, med bilens laddning och solprognosen.
- **Bilar**: varje bil med laddnivå, effekt och status.

**Värme** och **Bil** läggs till på samma sätt:

```yaml
type: custom:energywizard-heat-card
```

```yaml
type: custom:energywizard-car-card
car: tesla          # bilens id, valfritt (annars visas alla bilar)
```

Korten läser bara. Styrning (starta, pausa, strategi) sker i EnergyWizard.

Tider visas alltid som 24-timmarsklocka (TT:MM), aldrig AM/PM.

## Utveckling

Källan är `ha-cards/energywizard-cards.js`. Efter en ändring kopieras den till `dist/` (det är den filen HACS hämtar), annars stoppar testet `tests/test_ha_cards_dist.py`.

`preview.html` visar kortet med exempeldata, utan Home Assistant. Öppna den i en webbläsare. Parametrar: `?theme=light`,
`?tab=plan`, `?lang=en`, `?empty=1` (ingen data), `?missing=1` (sensorn saknas).

?card=heat och ?card=car visar de andra korten.

Sensorns schema står överst i `smartbox/ha_card_feed.py`.
