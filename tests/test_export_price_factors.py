"""Optional export tariff coefficients: Python, SQL and owner settings agree."""
import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest

import ew_settings
import nordpool as N


@pytest.fixture
def tariff(monkeypatch):
    values = {"price_country": "SE", "price_sell_extra": .07}
    monkeypatch.setattr(ew_settings, "get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(N, "prices_include_vat", lambda: False)
    monkeypatch.delenv("PRICE_SELL_FACTOR", raising=False)
    monkeypatch.delenv("PRICE_SELL_NEGATIVE_FACTOR", raising=False)
    return values


def test_legacy_defaults_and_import_cost_are_preserved(tariff):
    before = N.full_buy_cost(2)
    assert N.full_sell_income(2) == pytest.approx(2.07)
    assert N.full_sell_income(-2) == pytest.approx(-1.93)
    tariff.update(price_sell_factor=.95, price_sell_negative_factor=.5)
    assert N.full_sell_income(2) == pytest.approx(1.97)
    assert N.full_sell_income(-2) == pytest.approx(-.93)
    assert N.full_sell_income(0) == .07
    assert N.full_buy_cost(2) == before


@pytest.mark.parametrize("included", [False, True])
@pytest.mark.parametrize("sell_vat", [False, True])
def test_python_and_postgres_agree_for_each_sign_and_vat_basis(db, tariff, monkeypatch, included, sell_vat):
    monkeypatch.setattr(N, "prices_include_vat", lambda: included)
    tariff.update(price_sell_factor=.95, price_sell_negative_factor=.5, price_sell_vat=sell_vat)
    expression = N.sql_sell_income_expr("spot")
    for base, factor in ((-2, .5), (0, .95), (2, .95)):
        raw = base * 1.25 if included else base
        expected = base * (1.25 if sell_vat else 1) * factor + .07
        actual = db.execute(f"SELECT {expression} FROM (SELECT %s::numeric AS spot) q", (raw,)).fetchone()[0]
        assert float(actual) == pytest.approx(expected)
        assert N.full_sell_income(raw) == pytest.approx(expected)


def test_fixed_price_is_not_scaled_and_zero_factor_is_valid(tariff):
    tariff.update(price_sell_factor=0, price_sell_negative_factor=0)
    assert N.full_sell_income(2) == N.full_sell_income(-2) == .07
    tariff.update(price_sell_mode="fixed", price_sell_fixed=1.5)
    assert N.full_sell_income(-999) == pytest.approx(1.57)
    assert eval(N.sql_sell_income_expr("spot")) == pytest.approx(1.57)


@pytest.mark.parametrize("value", [-1, 11, "NaN", "inf", True, "bad"])
def test_invalid_external_factors_fall_back_without_inverting_prices(tariff, value):
    tariff.update(price_sell_factor=value, price_sell_negative_factor=value)
    assert N.cost_settings()["sell_factor"] == 1
    assert N.cost_settings()["sell_negative_factor"] == 1
    assert N.full_sell_income(-2) == pytest.approx(-1.93)


def test_environment_and_decimal_comma(tariff, monkeypatch):
    monkeypatch.setenv("PRICE_SELL_FACTOR", "0,95")
    monkeypatch.setenv("PRICE_SELL_NEGATIVE_FACTOR", "0.4")
    assert N.full_sell_income(2) == pytest.approx(1.97)
    assert N.full_sell_income(-2) == pytest.approx(-.73)


def test_owner_api_roundtrip_partial_update_and_rejection(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1] / "webdashboard")
    import webdashboard.app as app
    monkeypatch.setattr(app.AUTH, "session", lambda request: ("owner", "test"))
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "settings.json"))
    ew_settings._cache.update(mtime=None, data={})
    monkeypatch.setattr(N, "price_source", lambda: "elprisetjustnu")
    monkeypatch.setattr(N, "prices_include_vat", lambda: False)
    def request(body):
        async def json_body():
            return body
        return Mock(json=json_body)
    base = {"country": "SE", "area": "SE4"}
    assert asyncio.run(app.price_settings_set(request(base | {"sell_factor": "0,95", "sell_negative_factor": 1}))) == {"ok": True}
    result = asyncio.run(app.price_settings_get())
    assert result["sell_factor"] == .95 and result["sell_negative_factor"] == 1
    assert asyncio.run(app.price_settings_set(request(base))) == {"ok": True}
    assert N.cost_settings()["sell_factor"] == .95  # Old clients do not reset the new fields.
    for value in (-1, 11, "nan", "inf", True, "bad"):
        result = asyncio.run(app.price_settings_set(request(base | {"sell_factor": value})))
        assert result.status_code == 400
        assert N.cost_settings()["sell_factor"] == .95
    assert asyncio.run(app.price_settings_set(request(base | {"sell_factor": ""}))) == {"ok": True}
    assert N.cost_settings()["sell_factor"] == 1
    monkeypatch.setattr(app.AUTH, "session", lambda request: ("viewer", "test"))
    assert asyncio.run(app.price_settings_set(request(base | {"sell_factor": .2}))).status_code == 403
