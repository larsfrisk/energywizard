"""ev_schedule_auto.py - vilken laddnivå ett automatiskt skapat laddschema ska få (#576).

När en bil kopplas in utan något aktivt framtida schema skapar motorn ett för nästa avfärd. Förut fick det alltid 100 % och
skrev över dagens sparade rad, så användare som satt en lägre nivå (t.ex. 50 % för vardagsladdning) fick tillbaka 100 % varje
gång. Nu behålls användarens egen nivå: dagens sparade nivå om den är lägre än 100, annars den vanligaste lägre nivån bland
bilens övriga dagar, annars 100. Ren logik, testas i tests/test_ev_schedule_auto.py.
"""
from collections import Counter


def soc_for(week: dict, day: int) -> int:
    """week: {dag 0-6: {"target_soc": int, ...}} för en bil (som settings.get_ev_schedule ger)."""
    def val(d):
        try:
            return int((week.get(d) or {}).get("target_soc"))
        except (TypeError, ValueError):
            return 100
    own = val(day)
    if own < 100:
        return max(20, own)
    others = [val(d) for d in range(7) if d != day and val(d) < 100]
    if others:
        return max(20, Counter(others).most_common(1)[0][0])
    return 100
