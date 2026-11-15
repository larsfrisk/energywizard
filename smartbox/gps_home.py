"""Bilens hemkomst ur GPS: är bilen på väg hem? Då förallokeras laddningen (laddplanen räknar med bilen).

2026-11-15: efter en omstart var förra avståndet okänt (999 km), så första avläsningen räknades som "närmar sig" för
båda bilarna. De stod hemma, men hemmets position låg 1,77 km fel (weather.py), och flaggan släpptes aldrig eftersom
avståndet varken blev under 0,5 km eller ändrades. En urkopplad bil räknades då som inkopplad i realtidsstyrningen.

Regler:
  - "närmar sig": 0,5-15 km bort och minst 0,2 km närmare än referensen (som måste vara känd)
  - släpps: hemma (<= 0,5 km), långt bort (>= 15 km), inkopplad, eller ingen närmande på APPROACH_TIMEOUT
"""
from datetime import timedelta

NEAR_KM = 0.5
FAR_KM = 15.0
STEP_KM = 0.2
APPROACH_TIMEOUT = timedelta(minutes=10)


def approaching(was, dist, ref, closer_at, connected, now):
    """Returnerar (närmar_sig, senaste_närmande, ny_referens). ref = avståndet vi jämför med: flyttas när bilen kommit
    STEP_KM närmare eller rört sig bort, så att även ett långsamt närmande (många små steg) räknas."""
    if dist is None or dist >= 900:
        return False, None, ref
    new_ref = dist if ref is None or ref >= 900 or dist > ref else ref
    if connected or dist <= NEAR_KM or dist >= FAR_KM:
        return False, None, dist
    if ref is not None and ref < 900 and dist < ref - STEP_KM:
        return True, now, dist
    if was and closer_at is not None and now - closer_at < APPROACH_TIMEOUT:
        return True, closer_at, new_ref
    return False, None, new_ref
