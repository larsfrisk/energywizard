#!/bin/bash
# Körs av crontab (1 gång/månad) - räknar om besparingssiffrorna och pushar
# docs/data/stats.json till main. Bara en datafil, ingen kod - se
# scripts/export_public_stats.py och PR #17 för resonemang/formel.
set -euo pipefail
cd /home/emil/opt/Energywizz

docker cp scripts/export_public_stats.py smartbox:/tmp/export_public_stats.py
docker exec smartbox python3 /tmp/export_public_stats.py
docker exec smartbox cat /docs/data/stats.json > docs/data/stats.json

# Märken som körs hos installationerna (anonym telemetri, bara tillverkare och antal)
TELEMETRY_STATS_URL=$(docker exec webdashboard printenv TELEMETRY_STATS_URL) \
TELEMETRY_STATS_TOKEN=$(docker exec webdashboard printenv TELEMETRY_STATS_TOKEN) \
    python3 scripts/export_public_equipment.py || echo "Utrustningslistan kunde inte uppdateras, behåller förra."

if git diff --quiet -- docs/data/stats.json docs/data/utrustning.json; then
    echo "Inga ändrade siffror, hoppar över commit."
    exit 0
fi

git add docs/data/stats.json docs/data/utrustning.json
git commit -m "Uppdatera publika besparingssiffror ($(date +%Y-%m-%d))"
git push origin main
