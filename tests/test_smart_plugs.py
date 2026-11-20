from unittest.mock import Mock

import pytest
from smart_plugs import Controller,run,policy_price,watts

T=1794528000.


def snapshot(state='on',context='initial'):
    return dict(entity_id='switch.tv',state=state,context={'id':context},last_changed='2026-11-01T00:00:00+00:00')


def config(**changes):
    return dict(enabled=True,devices=[dict(enabled=True,nonessential=True,switch='switch.tv',
        off_above=2.,restore_below=1.,min_on_minutes=5,min_off_minutes=5,**changes)])


def test_fallback_missing_and_invalid_prices_are_not_used():
    transform=Mock(return_value=2.)
    for spot,strategy in [(None,{}),(float('nan'),{'price_fallback':False}),
                           (1,{}),(1,{'price_fallback':True})]:
        assert policy_price(spot,strategy,T,transform) is None
    transform.assert_not_called()
    assert policy_price(-1,{'price_fallback':False},T,transform)==2
    transform.assert_called_once_with(-1,T)


def test_disabled_adapter_has_no_ha_or_shadow_calls(monkeypatch):
    import homeassistant as ha,shadow
    get=Mock();active=Mock()
    monkeypatch.setattr(ha.requests,'get',get);monkeypatch.setattr(shadow,'active',active)
    run(Controller(None),3,T)
    get.assert_not_called();active.assert_not_called()


def test_defaults_critical_and_always_on_are_excluded():
    assert not Controller(None).devices
    c=config();c['enabled']=False
    assert not Controller(c).devices
    for key,value in [('nonessential',False),('always_on',True),('enabled',False)]:
        c=config();c['devices'][0][key]=value
        assert not Controller(c).devices


@pytest.mark.parametrize('key,value',[('off_above',float('nan')),('restore_below',2),
    ('min_on_minutes',0),('min_off_minutes',True),('switch','switch.tv, switch.fridge')])
def test_invalid_policy_is_rejected(key,value):
    c=config();c['devices'][0][key]=value
    with pytest.raises(ValueError):Controller(c)
    c=config();c['devices']*=2
    with pytest.raises(ValueError):Controller(c)


def test_price_hysteresis_dwell_and_owned_restoration():
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=snapshot('off','ew-off'))
    c.tick(3,T,read,write)
    c.tick(3,T+299,read,write);write.assert_not_called()
    c.tick(2,T+300,read,write);write.assert_not_called()
    c.tick(3,T+300,read,write);write.assert_called_once_with('switch.tv',False)
    read.return_value=snapshot('off','ew-off');write.reset_mock()
    c.tick(.5,T+599,read,write);write.assert_not_called()
    c.tick(1.5,T+600,read,write);write.assert_not_called()
    write.return_value=snapshot('on','ew-on')
    c.tick(.5,T+600,read,write);write.assert_called_once_with('switch.tv',True)


def test_initially_off_and_restart_never_gain_restore_authority():
    for c in (Controller(config()),Controller(config())):
        write=Mock();read=Mock(return_value=snapshot('off'))
        c.tick(.1,T,read,write);c.tick(.1,T+1000,read,write)
        write.assert_not_called()


@pytest.mark.parametrize('observation',[None,snapshot('unavailable'),snapshot('on','manual'),snapshot('off','manual')])
def test_manual_changes_and_missing_evidence_suspend_without_retry(observation):
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=snapshot('off','ew-off'))
    c.tick(3,T,read,write);c.tick(3,T+300,read,write);write.reset_mock()
    read.return_value=observation
    c.tick(.1,T+600,read,write)
    read.return_value=snapshot('off','ew-off')
    c.tick(.1,T+1200,read,write)
    write.assert_not_called()


@pytest.mark.parametrize('response',[None,{},snapshot('off','initial')])
def test_ambiguous_write_is_not_retried_or_restored(response):
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=response)
    c.tick(3,T,read,write);c.tick(3,T+300,read,write)
    c.tick(3,T+1000,read,write)
    assert write.call_count==1


def test_shadow_and_missing_price_never_write_or_keep_authority():
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=snapshot('off','ew-off'))
    c.tick(3,T,read,write);c.tick(3,T+300,read,write);write.reset_mock()
    c.tick(None,T+600,read,write);write.assert_not_called()
    c.tick(.1,T+900,read,write,shadow=True)
    assert c.state=={}
    read.return_value=snapshot('off','ew-off')
    c.tick(.1,T+1200,read,write);c.tick(.1,T+1800,read,write)
    write.assert_not_called()


def test_adapter_uses_fresh_get_and_changed_state_context(monkeypatch):
    import homeassistant as ha,shadow
    monkeypatch.setattr(shadow,'active',lambda:False)
    get=Mock(return_value=Mock(json=Mock(return_value=snapshot())))
    post=Mock(return_value=Mock(json=Mock(return_value=[snapshot('off','ew-off')])))
    monkeypatch.setattr(ha.requests,'get',get);monkeypatch.setattr(ha.requests,'post',post)
    c=Controller(config());run(c,3,T);run(c,3,T+300)
    assert get.call_count==2
    assert post.call_args.kwargs['json']=={'entity_id':'switch.tv'}
    assert post.call_args.kwargs['verify']==ha._VERIFY
    assert c.state['switch.tv']['owned']


def test_power_units_and_invalid_limits():
    assert watts({'state': '0.004', 'attributes': {'unit_of_measurement': 'kW'}}) == pytest.approx(4)
    assert watts({'state': '3.2', 'attributes': {'unit_of_measurement': 'W'}}) == pytest.approx(3.2)
    assert watts({'state': '3'}) == pytest.approx(3)
    for raw in ('on', 'unavailable', '-1', 'nan', True):
        assert watts({'state': raw, 'attributes': {'unit_of_measurement': 'W'}}) is None
    assert watts({'state': '3', 'attributes': {'unit_of_measurement': 'A'}}) is None
    for extra in (dict(power='switch.tv'), dict(power='sensor.tv_power', standby_below_w=0),
                  dict(power='sensor.tv_power', standby_minutes=4), dict(standby_below_w=5)):
        with pytest.raises(ValueError):
            Controller(config(**extra))
    device = Controller(config(power='sensor.tv_power')).devices[0]
    assert device['standby_w'] == 5 and device['standby_s'] == 30 * 60


def test_standby_is_reported_once_and_never_switches():
    notes = []
    c = Controller(config(power='sensor.tv_power', standby_below_w=5, standby_minutes=5))
    read = Mock(return_value=snapshot())
    write = Mock()

    def record(*args):
        notes.append(args)

    power = Mock(return_value=3.2)
    c.tick(1.5, T, read, write, power=power, record=record)
    c.tick(1.5, T + 299, read, write, power=power, record=record)
    assert notes == [] and write.call_count == 0
    c.tick(1.5, T + 300, read, write, power=power, record=record)
    c.tick(1.5, T + 600, read, write, power=power, record=record)
    assert notes == [('switch.tv', 'standby about 3 W')]
    write.assert_not_called()
    power.return_value = 40
    c.tick(1.5, T + 601, read, write, power=power, record=record)
    power.return_value = 2
    c.tick(1.5, T + 602, read, write, power=power, record=record)
    c.tick(1.5, T + 902, read, write, power=power, record=record)
    assert notes[-1] == ('switch.tv', 'standby about 2 W')
    assert len(notes) == 2


def test_missing_off_and_unknown_power_do_not_count_as_standby():
    notes = []
    c = Controller(config(power='sensor.tv_power', standby_minutes=5))
    write = Mock()
    c.tick(1.5, T, Mock(return_value=snapshot('off')), write, power=lambda _e: 0, record=notes.append)
    c.tick(1.5, T + 1000, Mock(return_value=snapshot()), write, power=lambda _e: None, record=notes.append)
    c.tick(1.5, T + 2000, Mock(return_value=snapshot()), write, power=lambda _e: None, record=notes.append)
    assert notes == []
    write.assert_not_called()
    called = []
    Controller(config()).tick(1.5, T, Mock(return_value=snapshot()), Mock(), power=lambda e: called.append(e))
    assert called == []


def test_shadow_reports_standby_without_keeping_switch_authority():
    notes = []
    c = Controller(config(power='sensor.tv_power', standby_minutes=5))
    read = Mock(return_value=snapshot())
    write = Mock(return_value=snapshot('off', 'ew-off'))
    c.tick(3, T, read, write, shadow=True, power=lambda _e: 1, record=lambda *a: notes.append(a))
    c.tick(3, T + 300, read, write, shadow=True, power=lambda _e: 1, record=lambda *a: notes.append(a))
    assert notes == [('switch.tv', 'standby about 1 W')]
    assert c.state == {} and write.call_count == 0
    read.return_value = snapshot('off', 'ew-off')
    c.tick(0.1, T + 900, read, write)
    c.tick(0.1, T + 1800, read, write)
    write.assert_not_called()


def test_expensive_price_still_switches_once_while_standby_is_only_logged():
    notes = []
    c = Controller(config(power='sensor.tv_power', standby_minutes=5))
    read = Mock(return_value=snapshot())
    write = Mock(return_value=snapshot('off', 'ew-off'))
    c.tick(3, T, read, write, power=lambda _e: 2, record=lambda *a: notes.append(a))
    c.tick(3, T + 300, read, write, power=lambda _e: 2, record=lambda *a: notes.append(a))
    assert write.call_args_list == [(('switch.tv', False),)]
    assert notes == [('switch.tv', 'standby about 2 W')]


def test_standby_log_failure_does_not_block_the_price_switch():
    c = Controller(config(power='sensor.tv_power', standby_minutes=5))
    read = Mock(return_value=snapshot())
    write = Mock(return_value=snapshot('off', 'ew-off'))

    def boom(*_args):
        raise RuntimeError('log')

    c.tick(3, T, read, write, power=lambda _e: 1, record=boom)
    c.tick(3, T + 300, read, write, power=lambda _e: 1, record=boom)
    assert write.call_args_list == [(('switch.tv', False),)]


def test_adapter_reads_the_power_sensor_and_does_not_post(monkeypatch):
    import homeassistant as ha
    import shadow
    monkeypatch.setattr(shadow, 'active', lambda: False)

    def get(url, **kwargs):
        assert kwargs['verify'] == ha._VERIFY and kwargs['timeout'] == 5
        if url.endswith('/sensor.tv_power'):
            body = {'entity_id': 'sensor.tv_power', 'state': '2.2',
                    'attributes': {'unit_of_measurement': 'W'}}
        else:
            body = snapshot()
        return Mock(json=Mock(return_value=body))

    get_mock = Mock(side_effect=get)
    post = Mock()
    monkeypatch.setattr(ha.requests, 'get', get_mock)
    monkeypatch.setattr(ha.requests, 'post', post)
    c = Controller(config(power='sensor.tv_power', standby_minutes=5))
    run(c, 1.5, T)
    run(c, 1.5, T + 300)
    urls = [call.args[0] for call in get_mock.call_args_list]
    assert any(url.endswith('/sensor.tv_power') for url in urls)
    assert any(url.endswith('/switch.tv') for url in urls)
    post.assert_not_called()
