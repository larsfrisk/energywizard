#!/bin/bash
# Exporterar kvartsdata för värmepumpens backtester (model.py, pause.py, setpoint.py).
#   scripts/backtest_heat/export.sh [utkatalog] [från-datum]
# Kvartsaggregerat och med statement_timeout: en långsam fråga mot sensor_log får aldrig låsa motorns
# ALTER TABLE (2026-11-14 hängde motorn ~20 min av en avbruten export). Innetemperaturen exakt 20,0 tas bort:
# det är pumpens fasta värde när rumsgivarna saknas (Thermia/Husdata), inte en mätning.
set -e
OUT=${1:-$(dirname "$0")/data}; FROM=${2:-2026-03-01}
mkdir -p "$OUT"
PSQL=(docker exec postgres-smartbox psql -U postgres -d smartbox_database -At -F ',')
Q="date_trunc('hour', timestamp) + floor(extract(minute from timestamp)/15)*interval '15 min'"
"${PSQL[@]}" -c "SET statement_timeout='120s';" -c "
SELECT to_char($Q,'YYYY-MM-DD\"T\"HH24:MI'),
  round(avg(price)::numeric,4), round(avg(nullif(indoor_temp,20))::numeric,2), round(avg(outdoor_temp)::numeric,1),
  round(avg(compressor_running)::numeric,3), mode() within group (order by active_mode),
  round(max(water_temp)-min(water_temp),1), round(avg(cop)::numeric,2), count(*)
FROM sensor_log WHERE timestamp >= '$FROM' GROUP BY 1 ORDER BY 1" | grep -v '^SET$' > "$OUT/q.csv"
"${PSQL[@]}" -c "SET statement_timeout='60s';" -c "
SELECT to_char($Q,'YYYY-MM-DD\"T\"HH24:MI'), round(avg(pump_w)::numeric)
FROM load_breakdown WHERE timestamp >= '$FROM' GROUP BY 1 ORDER BY 1" | grep -v '^SET$' > "$OUT/pump.csv"
"${PSQL[@]}" -c "SET statement_timeout='120s';" -c "
SELECT to_char($Q,'YYYY-MM-DD\"T\"HH24:MI'),
  round(avg(calc_forward_temp)::numeric,2), round(avg(room_temp_setpoint)::numeric,2), round(avg(forward_temp)::numeric,2)
FROM sensor_log WHERE timestamp >= '$FROM' GROUP BY 1 ORDER BY 1" | grep -v '^SET$' > "$OUT/sp.csv"
wc -l "$OUT"/q.csv "$OUT"/pump.csv "$OUT"/sp.csv
