"""charge_now.py - "Ladda nu till X %" som avslutas av sig själv (#394).

"Ladda nu" laddade förut tills användaren själv valde Auto igen, även på dyra timmar. Nu avslutas det av sig själv när
bilen är full (slutade ladda själv) eller kabeln dras ur, med eller utan mål. Med ett mål avslutas det också när bilen når
målet och efter MAX_S (24 h). Därefter tar planen över. Säkringsskyddet gäller hela tiden, och bilens vanliga mål och klar-tid ändras
inte. Idé från Darkstars "Charge now" (github.com/ergetie/darkstar), egen implementation.

Överstyrningar (logger.set_override): <bil>_charge_now_target (procent) och <bil>_charge_now_until (unix-tid)."""

MAX_S = 24 * 3600


def target(overrides: dict, car: str):
    try:
        v = int(str(overrides.get(f"{car}_charge_now_target") or "").strip())
    except ValueError:
        return None
    return v if 1 <= v <= 100 else None


def until(overrides: dict, car: str):
    try:
        return float(str(overrides.get(f"{car}_charge_now_until") or "").strip())
    except ValueError:
        return None


def should_end(overrides: dict, car: str, soc, connected: bool, now_ts: float, completed: bool = False):
    """(True, orsak) när en pågående "Ladda nu" ska avslutas, annars (False, None).

    Ladda nu laddar tills bilen är full (den slutade ladda själv, completed) eller kabeln dras ur, med eller utan mål (Emil
    2026-11-20). Med ett mål (X %) avslutas det också vid målet och efter MAX_S. Utan avslut låg tvånget kvar efter urdragen
    kabel och slog till igen nästa gång bilen kopplades in."""
    forced = str(overrides.get(f"{car}_force_amps") or "0").strip()
    forced_on = forced.isdigit() and int(forced) > 0
    t = target(overrides, car)
    if t is None:
        if not forced_on:
            return False, None                       # inget Ladda nu pågår
        if not connected:
            return True, "unplugged"
        if completed:
            return True, "full"
        return False, None
    if not forced_on:
        return True, "stopped"                       # stoppad eller Auto på annat sätt: städa bara upp
    if soc is not None and float(soc) >= t:
        return True, "target"
    if not connected:
        return True, "unplugged"
    if completed:
        return True, "full"
    u = until(overrides, car)
    if u is not None and now_ts >= u:
        return True, "timeout"
    return False, None


def clear_keys(car: str) -> dict:
    """Överstyrningarna som återställer bilen till planen."""
    return {f"{car}_force_amps": "0", f"{car}_force_phases": "0", f"{car}_charge_now_target": "",
            f"{car}_charge_now_until": "", "force_ev_recalc": "true"}
