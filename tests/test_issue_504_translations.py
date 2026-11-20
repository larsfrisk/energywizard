"""Translate reachable catalog entries and the messages the UI actually receives."""
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

import decision_summary
import i18n_py

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('lang', ['en', 'cs'])
def test_every_catalog_entry_is_reachable(lang):
    catalog = json.loads((ROOT / f'smartbox/i18n/{lang}.json').read_text(encoding='utf-8'))
    for source, expected in catalog.items():
        if source.startswith('_'):
            continue
        assert expected, f'{lang}: empty translation: {source}'
        assert i18n_py.tr(source, lang) == expected, f'{lang}: unreachable translation: {source}'


@pytest.mark.parametrize('lang', ['en', 'cs'])
def test_log_catalog_also_covers_displayed_summary_forms(lang):
    catalog = json.loads((ROOT / f'smartbox/i18n/{lang}.json').read_text(encoding='utf-8'))
    for source, target in catalog.items():
        # Only the priority number is substituted; body placeholders stay intact.
        sample = re.sub(r'^(.*?Prio )[#.]+', lambda m: m[1] + '1', source)
        tag, body = decision_summary._parse(sample)
        if tag not in decision_summary._TAG_TO_KEY or body == sample or ': ' not in target:
            continue
        displayed = decision_summary._tidy(body)
        expected = decision_summary._tidy(target.split(': ', 1)[1])
        assert i18n_py.tr(displayed, lang) != displayed or displayed == expected, f'{lang}: {displayed}'


@pytest.mark.parametrize('lang', ['en', 'cs'])
def test_displayed_decision_forms_have_complete_translations(lang):
    # Engine prefixes are removed/normalized before these reach both UIs.
    logs = [
        '💧 Prio 6 (VV-FAILSAFE): Vattnet är kritiskt svalt (37.9°C). Tvingar varmvatten oavsett elpris och effekttak!',
        '🛑 Prio 5 (HUS): För varmt inne (22.6°C >= 22.5°C). Mjukt kompressor-stopp aktiverat (-3.5°C).',
        '🚗 Prio 3 (EV Plan): Laddar enligt schema. Husets säkring tillåter 14A. Sätter Auto <1>: 0A, Moje auto: 14A.',
        '⚙️ Prio 8 (KOMPRESSOR): Anti-Short-Cycle – Låst i läge CHEAP till 03:52, börvärde 22.0 °C.',
        '☀️ Prio 2 (SOL-PI): Minuspris. Netto: -500W. Fel: 500. Justering: -0.25%. Ny gräns: 85%.',
        '🛁 Prio 4 (SPA): Minuspris -> Värmer bad till max för termisk lagring.',
    ]
    forbidden = ('Vattnet', 'Tvingar', 'För varmt', 'Mjukt', 'Husets', 'Sätter', 'Byter', 'Låst', 'Minuspris', 'Värmer', 'Ny gräns')
    for log in logs:
        item = decision_summary.summarize([log])['items'][0]
        translated = i18n_py.tr(item['text'], lang)
        assert translated != item['text']
        assert not any(word in translated for word in forbidden), translated
        if 'Auto <1>' in log:
            assert 'Auto <1>: 0A, Moje auto: 14A' in translated
        if '-500W' in log:
            assert '-500W' in translated and '-0.25%' in translated


@pytest.mark.parametrize('lang', ['en', 'cs'])
def test_notification_paragraphs_preserve_line_endings_and_names(lang):
    source = '🚗 Bilen laddar\r\n\r\nLaddningen av Auto <1> har startat med 3.7 kW.'
    translated = i18n_py.tr(source, lang)
    assert 'Bilen' not in translated and 'Laddningen' not in translated
    assert '\r\n\r\n' in translated
    assert 'Auto <1>' in translated and '3.7' in translated


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js required for browser checks')
def test_browser_catalogs_and_rendered_ui_text():
    result = subprocess.run(['node', 'tests/test_issue_504_translations.cjs'], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('lang', ['en', 'cs'])
@pytest.mark.parametrize('changed', [
    {}, {'indoor_temp': 23.0}, {'indoor_temp': 17.0}, {'water_temp': 30.0},
    {'indoor_temp': None}, {'current_price': -0.4},
])
def test_actual_engine_decisions_translate(smartbox, lang, changed):
    from gpm import GlobalPriorityManager

    state = {'now': datetime(2026, 11, 17, 18), 'current_price': 2.0,
             'all_prices': [0.3] * 32 + [2.0] * 64, 'dynamic_limit': 0.3, 'hysteresis': 0.2,
             'car_ids': [], 'peak_shaving_enabled': False, 'indoor_temp': 21.0,
             'indoor_min': 19.0, 'indoor_max': 22.5, 'outdoor_avg_5d': 0.0}
    actions = GlobalPriorityManager().evaluate(state | changed)
    items = decision_summary.summarize(actions['log'], actions)['items']
    assert items
    for item in items:
        translated = i18n_py.tr(item['text'], lang)
        assert translated != item['text'], f"{lang}: {item['text']}"
        assert not any(word in translated for word in (
            'Vattnet', 'Tvingar', 'För varmt', 'Mjukt', 'Husets', 'Sätter', 'Byter', 'låser',
            'Minuspris', 'Värmer', 'Ny gräns', 'Utan innegivare', 'Värmepump styrs', 'Håller badet',
        )), translated
