"""Public validation messages are selected from constants, never exception text."""
_MESSAGES = [
    "Sju dagar behövs",
    "Ogiltig entitet för HDO-schema",
    "Ange ett fast pris när fast avtal är valt",
    "Ogiltig priskälla för HDO",
    "Välj Tjeckien och ett HDO-schema för NT/VT-priser",
    "Ange båda slutpriserna för NT och VT",
    "Ange båda distributionsavgifterna när HDO används",
    "ČEZ HDO saknar giltiga priser för NT och VT. Ange priserna manuellt eller konfigurera dem i integrationen.",
]
_MESSAGES += [f"Ogiltigt värde: {field}" for field in (
    "buy_mode", "sell_mode", "buy_fixed", "sell_fixed", "distribution_nt", "distribution_vt", "buy_nt", "buy_vt")]
_VALIDATION = {message: message for message in _MESSAGES}


def validation_message(error):
    return _VALIDATION.get(str(error), "Ogiltigt värde")
