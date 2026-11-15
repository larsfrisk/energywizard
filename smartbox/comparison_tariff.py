"""Explicit linear tariffs for hypothetical snapshots; no settings or I/O."""
import math

NUMBERS = ('buy_spot_factor', 'buy_extra', 'sell_positive_spot_factor',
           'sell_negative_spot_factor', 'sell_extra')
FIELDS = {'currency', 'spot_includes_vat', *NUMBERS}


def validate(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        raise ValueError('Complete comparison tariff model required')
    currency = raw['currency']
    if not isinstance(currency, str) or len(currency) != 3 or not all('A' <= c <= 'Z' for c in currency):
        raise ValueError('Explicit currency code required')
    if type(raw['spot_includes_vat']) is not bool:
        raise ValueError('Explicit spot VAT basis required')
    for key in NUMBERS:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Finite tariff assumptions required')
        if key.endswith('factor') and not 0 <= value <= 10:
            raise ValueError('Invalid tariff factor')
    return dict(raw)


def prices(model, spot):
    if isinstance(spot, bool) or not isinstance(spot, (int, float)) or not math.isfinite(spot):
        raise ValueError('Finite input spot required')
    factor = model['sell_positive_spot_factor'] if spot >= 0 else model['sell_negative_spot_factor']
    buy = spot*model['buy_spot_factor']+model['buy_extra']
    sell = spot*factor+model['sell_extra']
    if not math.isfinite(buy) or not math.isfinite(sell):
        raise ValueError('Invalid effective tariff')
    return buy, sell
