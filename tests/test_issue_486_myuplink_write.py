"""#486 ("Fel: skriv fel myUplink"): en enstaka read-timeout mot Supervisor-proxyn tappade
värmepumpens kurvförskjutning (number.offset_47011) som ett ❌ - men enligt filens egna
konvention (update_states: enstaka timeout är drift) ska den vara en varning med omprövning.
set_number/set_select får därför en omprövning vid timeout/avbrott/502-503-504 och
timeout=10 som övriga skrivningar. Mockar requests helt - rör aldrig en riktig HA."""
from unittest.mock import MagicMock, patch

import requests

import homeassistant


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        err = requests.HTTPError(f"HTTP {status_code}")
        err.response = r
        r.raise_for_status.side_effect = err
    return r


def _read_timeout():
    return requests.exceptions.ReadTimeout("Read timed out. (read timeout=5)")


def _no_states():
    """Läs-före-skriv (_already) svarar inte -> skriva oavsett."""
    return _read_timeout()


# ---------- set_number ----------

def test_timeout_forsta_gangen_forsoker_igen_och_lyckas():
    """Det exakta felfallet i #486: read-timeout mot supervisor, lyckas vid omprövningen."""
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep") as mock_sleep:
        mock_post.side_effect = [_read_timeout(), _resp()]
        assert homeassistant.set_number("number.offset_47011", 2) is True
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(2)
    # längre timeout än läsningar (20 s sedan #568) och samma payload som innan
    assert mock_post.call_args.kwargs["timeout"] == homeassistant._SERVICE_TIMEOUT_S == 20
    assert mock_post.call_args.kwargs["json"] == {"entity_id": "number.offset_47011", "value": "2"}


def test_timeout_ba_omgangar_ger_false():
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_post.side_effect = [_read_timeout(), _read_timeout()]
        assert homeassistant.set_number("number.offset_47011", 2) is False
    assert mock_post.call_count == 2   # en omprövning, inte mer


def test_502_fr_supervisor_forsoker_igen():
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_post.side_effect = [_resp(status_code=502), _resp()]
        assert homeassistant.set_number("number.offset_47011", -1) is True
    assert mock_post.call_count == 2


def test_riktigt_fel_404_forsoker_ingen_ggr():
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep") as mock_sleep:
        mock_post.side_effect = [_resp(status_code=404)]
        assert homeassistant.set_number("number.offset_47011", 2) is False
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()


def test_lyckad_skrivning_ingen_extra_anrop():
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep") as mock_sleep:
        mock_post.return_value = _resp()
        assert homeassistant.set_number("number.offset_47011", 0) is True
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()
    assert mock_post.call_args.args[0] == f"{homeassistant._BASE}/services/number/set_value"


# ---------- set_select (samma klass fel, samma fix) ----------

def test_set_select_timeout_forsoker_igen_och_lyckas():
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_post.side_effect = [_read_timeout(), _resp()]
        assert homeassistant.set_select("select.batteriläge", "ladda") is True
    assert mock_post.call_count == 2
    assert mock_post.call_args.kwargs["json"] == {"entity_id": "select.batteriläge", "option": "ladda"}


def test_set_select_504_och_dar_efter_lyckad():
    with patch("homeassistant.requests.get", side_effect=_no_states()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_post.side_effect = [_resp(status_code=504), _resp()]
        assert homeassistant.set_select("select.batteriläge", "auto") is True
    assert mock_post.call_count == 2


# ---------- drivrutinsnivå: myUplink-vägen via HA-entiteter (#158/#200) påverkas ej ----------

def test_nibe_kurvforskjutning_gar_igenom_set_number():
    from drivers.heatpump_ha_entities import HaEntitiesHeatPumpDriver
    d = HaEntitiesHeatPumpDriver({"curve_offset": "number.offset_47011"}, cfg={})
    with patch("homeassistant.set_number", return_value=True) as sn, \
         patch("shadow.active", return_value=False):
        assert d.set_room_temp(21.5)
        assert sn.call_args.args == ("number.offset_47011", 2)


def test_568_timeout_men_vardet_gick_igenom_ar_inget_fel():
    """#568: Tesla/myUplink svarar efter timeout fast kommandot gick igenom. Står entiteten på värdet är det ingen
    tappad styrsignal (ingen ❌ i loggen, därmed ingen felrapport)."""
    seen = _resp(200, {"state": "11"})
    with patch("homeassistant.requests.get", side_effect=[_no_states(), seen]), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_post.side_effect = [_read_timeout(), _read_timeout()]
        assert homeassistant.set_number("number.tesla_charging_amps", 11) is True
    assert mock_post.call_count == 2


def test_568_timeout_och_fel_varde_ar_fortfarande_ett_fel():
    other = _resp(200, {"state": "5"})
    with patch("homeassistant.requests.get", side_effect=[_no_states(), other]), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_post.side_effect = [_read_timeout(), _read_timeout()]
        assert homeassistant.set_number("number.tesla_charging_amps", 11) is False
