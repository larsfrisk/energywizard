"""Independent receipt evidence and scheduled native maintenance; no live I/O."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

import meter_frame
from drivers.ferroamp_modules import ModuleTelemetry
from test_battery_balance import slots, PARAMS
from battery_plan import optimize
from test_personal_battery_cutover import device
from test_ferroamp_drivers import hub, MODBUS
from drivers.ferroamp_modbus import float_words


def frame():
    now = meter_frame.dsmr_stamp('261116120000W')
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    states = {'frame': {'state': '261116120000W', 'last_reported': stamp}}
    entities = dict(frame_timestamp='frame', frame_coherent=True, max_age_s=30)
    for role, number, unit in [('import_w', '1.2', 'kW'), ('export_w', '0', 'kW'),
                               *[(f'current_l{i}', '2', 'A') for i in (1, 2, 3)]]:
        entities[role] = role
        states[role] = dict(state=number, last_reported='2026-11-15T00:00:00+00:00',
                            attributes={'unit_of_measurement': unit})
    return now, entities, states


def test_explicit_frame_keeps_unchanged_zero_and_source_time():
    now, entities, states = frame()
    result = meter_frame.read(entities, states, now+1)
    assert result['net_power_w'] == 1200
    assert result['sample_at'] == result['phase_sample_at'] == now
    assert meter_frame.read(entities, states, now+31) is None
    entities['frame_coherent'] = False
    assert meter_frame.read(entities, states, now+1) is None


@pytest.mark.parametrize('mutation', ['missing', 'unavailable', 'unit', 'future', 'nan', 'stale_frame'])
def test_frame_fails_closed(mutation):
    now, entities, states = frame()
    if mutation == 'missing': del states['export_w']
    elif mutation == 'unavailable': states['export_w']['state'] = 'unavailable'
    elif mutation == 'unit': states['import_w']['attributes']['unit_of_measurement'] = 'kWh'
    elif mutation == 'future': states['import_w']['last_reported'] = '2026-11-17T00:00:00Z'
    elif mutation == 'nan': states['export_w']['state'] = 'nan'
    else: states['frame']['last_reported'] = '2026-11-15T00:00:00Z'
    assert meter_frame.read(entities, states, now+1) is None


def test_dsmr_dst_and_invalid_timestamps():
    assert meter_frame.dsmr_stamp('261025023000W')-meter_frame.dsmr_stamp('261025023000S') == 3600
    for value in ['261116120000', '261332120000W', True, 'unavailable']:
        with pytest.raises(ValueError): meter_frame.dsmr_stamp(value)


class Client:
    def __init__(self): self.calls = []
    def connect_async(self, *args): self.calls.append('connect')
    def loop_start(self): self.on_connect(self, None, None, 0)
    def subscribe(self, topic, qos):
        assert topic == 'extapi/data/eso' and qos == 0
        self.calls.append('subscribe')
        return 0, 1
    def disconnect(self): self.calls.append('disconnect')
    def loop_stop(self): self.calls.append('stop')


def observer():
    clock = [100]
    client = Client()
    reader = ModuleTelemetry(dict(host='192.0.2.1', module_ids=['one', 'two']),
                             clock=lambda: clock[0], client_factory=lambda: client)
    assert client.calls == []
    reader.start()
    return reader, client, clock


def message(reader, identifier='one', soc=100, **kw):
    reader._message(None, None, SimpleNamespace(topic='extapi/data/eso', retain=False,
        dup=False, **kw, payload=json.dumps({'id': {'val': identifier}, 'soc': {'val': soc}}).encode()))


def test_module_receipts_complete_fresh_private_and_not_cache_refreshed():
    reader, client, clock = observer()
    message(reader)
    assert len(reader.snapshot()) == 2 and {} in reader.snapshot().values()
    message(reader, 'two', 99)
    assert all(v['sample_at'] == 100 for v in reader.snapshot().values())
    assert 'one' not in reader.snapshot() and 'two' not in reader.snapshot()
    clock[0] = 221
    assert all(v == {} for v in reader.snapshot().values())
    reader.stop()
    reader.start()
    assert reader.snapshot() == {} and client.calls == ['connect', 'subscribe', 'disconnect', 'stop']


@pytest.mark.parametrize('flag', ['retain', 'dup'])
def test_replayed_deliveries_do_not_establish_freshness(flag):
    reader, _, _ = observer()
    msg = SimpleNamespace(topic='extapi/data/eso', retain=False, dup=False,
                          payload=b'{"id":"one","soc":{"val":100}}')
    setattr(msg, flag, True)
    reader._message(None, None, msg)
    assert all(v == {} for v in reader.snapshot().values())


def test_unknown_invalid_and_reconnect_block_evidence():
    reader, client, _ = observer()
    message(reader); message(reader, 'two')
    message(reader, soc=True)
    assert {} in reader.snapshot().values()
    message(reader, 'unexpected')
    assert reader.snapshot() == {}
    reader._disconnect(client, None)
    reader._connect(client, None, None, 0)
    assert reader.snapshot() == {}  # Unexpected inventory remains blocked until explicit restart.


def test_native_maintenance_waits_and_uses_actual_standby_then_releases_ceiling():
    params = dict(PARAMS, allowed=('auto', 'charge', 'standby'), balance_standby=True,
                  standby_kw=.01, balance_deadline_slots=5)
    result = optimize(slots([5, 5, 1, 1, 2, 2]), **params)
    assert [r['action'] for r in result['rows'][:2]] == ['auto', 'auto']
    dwell = [r for r in result['rows'] if r.get('balance_hold')]
    assert dwell and all(r['action'] == 'standby' and r['battery_kw'] == -.01 for r in dwell)
    assert not result['rows'][-1]['balance_ceiling']
    import plan_snapshot
    data = slots([5, 5, 1, 1, 2, 2])
    assert plan_snapshot.replay(plan_snapshot.build(data, params, result, data[0]['t']))['matches']


def test_excess_standby_drift_cannot_force_maintenance():
    result = optimize(slots([1]*20), **dict(PARAMS, allowed=('auto', 'charge', 'standby'),
        balance_standby=True, standby_kw=.05, balance_hold_slots=16))
    assert result['balance_feasible'] is False and result['rows'] == []


def test_maintenance_ceiling_is_transient_and_explicit(hub):
    hub.inputs[6016] = float_words(95)
    ordinary = device(max_soc=90)
    ordinary.set_balancing(True)
    assert not ordinary.supports_maintenance() and not ordinary.apply_intent('charge', 500)
    approved = device(max_soc=90, maintenance_soc=100)
    assert approved.supports_maintenance()
    assert not approved.apply_intent('charge', 500)
    approved.set_balancing(True)
    assert approved.apply_intent('charge', 500)
    assert approved.apply_intent('auto')
    approved.set_balancing(False)
    assert not approved.apply_intent('charge', 500)


def test_factory_requires_both_physical_qualifications():
    from house_config import build_battery_driver
    cfg = dict(battery=dict(enabled=True, driver='ferroamp_modbus', modbus=MODBUS, control='styr', default_mode_verified=True,
        standby_reference_w=10, standby_verified=True, balance=dict(enabled=True,
        full_charge_verified=True, standby_dwell_verified=True)))
    assert build_battery_driver(cfg).supports_maintenance()
    for key in ('full_charge_verified', 'standby_dwell_verified', 'enabled'):
        for value in (False, 'true', 1):
            changed = {'battery': {**cfg['battery'], 'balance': {**cfg['battery']['balance'], key: value}}}
            assert not build_battery_driver(changed).supports_maintenance()


def test_module_start_failure_cleans_up_and_can_retry():
    class Failing(Client):
        def loop_start(self): raise OSError('unavailable')
    client = Failing()
    reader = ModuleTelemetry(dict(host='192.0.2.1', module_ids=['one', 'two']),
                             client_factory=lambda: client)
    reader.start()
    assert reader.snapshot() == {} and client.calls == ['connect', 'disconnect', 'stop']
    reader.factory = Client
    reader.start()
    assert reader.client is not None and reader.connected
    reader.stop()


def test_driver_module_snapshot_is_read_only_and_closeable(hub):
    reader, client, _ = observer()
    message(reader); message(reader, 'two')
    driver = device()
    driver._modules = reader
    state = driver.read_state()
    assert len(state['modules']) == 2 and all(state['modules'].values())
    assert state['soc_pct'] == 60 and hub.writes == []
    driver.close()
    assert reader.snapshot() == {} and client.calls[-1] == 'stop'


def test_frame_contract_reaches_ha_reader(monkeypatch):
    import homeassistant as ha
    from house_config import power_meter_entities
    now, entities, states = frame()
    config = {'power_meter': {'entities': {k:v for k,v in entities.items()
              if k not in ('frame_timestamp', 'frame_coherent', 'max_age_s')},
              **{k:entities[k] for k in ('frame_timestamp','frame_coherent','max_age_s')}}}
    monkeypatch.setattr(ha, 'POWER_METER', power_meter_entities(config))
    monkeypatch.setattr(ha, '_states_cache', states)
    monkeypatch.setattr(ha.time, 'time', lambda: now+1)
    assert ha.read_power_meter()['sample_at'] == now
