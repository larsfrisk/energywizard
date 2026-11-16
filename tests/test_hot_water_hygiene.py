from datetime import datetime, timezone
import pytest
from hot_water_hygiene import last_event
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import hot_water_hygiene


NOW = 1794851000.0


def test_explicit_reset_without_temperature_record():
    assert last_event(None, NOW, now=NOW).timestamp() == NOW


def test_newer_measurement_takes_precedence_and_naive_dates_are_utc():
    measured = datetime.fromtimestamp(NOW, timezone.utc)
    assert last_event(measured, NOW-86400, now=NOW) == measured
    assert last_event(measured.replace(tzinfo=None), NOW-86400, now=NOW) == measured
    assert last_event(measured, NOW+1, now=NOW+1).timestamp() == NOW+1


@pytest.mark.parametrize('reset', [None, True, 'now', -1, 0, float('nan'), float('inf'), NOW+1])
def test_invalid_or_future_reset_cannot_postpone_hygiene(reset):
    assert last_event(None, reset, now=NOW) is None
    measured = datetime.fromtimestamp(NOW-86400, timezone.utc)
    assert last_event(measured, reset, now=NOW) == measured


def test_engine_and_dashboard_use_same_explicit_reset_without_temperature_history():
    root = Path(__file__).resolve().parents[1]
    reset = datetime.now(timezone.utc).timestamp() - 60
    config = {'heat_pump': {'hygiene_reset_at': reset}}
    cursor = MagicMock(); cursor.__enter__.return_value = cursor; cursor.fetchone.return_value = (None,)
    connection = MagicMock(); connection.__enter__.return_value = connection; connection.cursor.return_value = cursor
    scope = {'house_cfg': config, 'logger': SimpleNamespace(get_db=lambda: connection),
             'hot_water_hygiene': hot_water_hygiene}
    def load(path, name, scope):
        node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
        return scope[name]
    engine = load(root/'smartbox/main.py', 'get_last_legionella', scope)
    assert engine(60).timestamp() == reset
    connection.execute.return_value.first.return_value = (None,)
    scope = {'text': lambda sql: sql, 'HOUSE_CONFIG_FILE': 'synthetic',
             'house_config': SimpleNamespace(load_house_config=lambda path: config)}
    dashboard = load(root/'webdashboard/app.py', '_legionella_last', scope)
    assert dashboard(connection, 60).timestamp() == reset
