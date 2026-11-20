from unittest.mock import Mock

import pytest

from plug_presence import Watch, present, run, vacation_on

T = 1794528000.


def config(**changes):
    device = dict(enabled=True, nonessential=True, switch='switch.tv', occupied='binary_sensor.office')
    device.update(changes.pop('device', {}))
    base = dict(enabled=True, devices=[device])
    base.update(changes)
    return base


def snap(entity, state):
    return dict(entity_id=entity, state=state)


def test_presence_states():
    assert present(snap('binary_sensor.office', 'on')) is True
    assert present(snap('input_boolean.home', 'off')) is False
    assert present(snap('person.emil', 'home')) is True
    assert present(snap('device_tracker.phone', 'not_home')) is False
    for entity, state in (
        ('binary_sensor.office', 'unavailable'),
        ('binary_sensor.office', 'unknown'),
        ('person.emil', 'work'),
        ('sensor.office', 'off'),
        ('binary_sensor.office', 'ON'),
    ):
        assert present(snap(entity, state)) is None
    assert present(None) is None
    assert present({'state': 'off'}) is None
    assert vacation_on(snap('input_boolean.vacation', 'on')) is True
    assert vacation_on(snap('input_boolean.vacation', 'off')) is False
    assert vacation_on(snap('person.emil', 'home')) is False
    assert vacation_on(snap('binary_sensor.vacation', 'unknown')) is False


def test_defaults_and_invalid_occupancy():
    room = Watch(config()).rooms[0]
    assert room['delay'] == 15 * 60 and room['label'] == '15'
    assert not Watch(None).active
    assert not Watch(dict(enabled=False, home='nope')).active
    for changes in (
        dict(device=dict(occupied='switch.tv')),
        dict(device=dict(occupied='binary_sensor.Bad')),
        dict(device=dict(unoccupied_minutes=4)),
        dict(device=dict(unoccupied_minutes=True)),
        dict(device=dict(occupied=None, unoccupied_minutes=15)),
        dict(away_minutes=15),
        dict(home='person.Bad'),
        dict(home='binary_sensor.home', away_minutes=4),
        dict(vacation='person.emil'),
        dict(vacation='input_boolean.Vacation'),
    ):
        with pytest.raises(ValueError):
            Watch(config(**changes))
    skipped = config(device=dict(always_on=True, occupied='not a sensor'))
    assert not Watch(skipped).active


def record_into(notes):
    def record(*args):
        notes.append(args)
    return record


def test_room_empty_is_logged_once_and_unknown_is_not_empty():
    notes = []
    watch = Watch(config(device=dict(occupied='binary_sensor.office', unoccupied_minutes=5)))
    states = {'binary_sensor.office': 'off'}

    def read(entity):
        return snap(entity, states[entity])

    record = record_into(notes)
    watch.tick(T, read, record)
    watch.tick(T + 299, read, record)
    assert notes == []
    watch.tick(T + 300, read, record)
    watch.tick(T + 600, read, record)
    assert notes == [('switch.tv', 'room empty for 5 min')]
    states['binary_sensor.office'] = 'on'
    watch.tick(T + 601, read, record)
    states['binary_sensor.office'] = 'unavailable'
    watch.tick(T + 602, read, record)
    watch.tick(T + 1000, read, record)
    assert notes == [('switch.tv', 'room empty for 5 min')]
    states['binary_sensor.office'] = 'off'
    watch.tick(T + 1001, read, record)
    watch.tick(T + 1301, read, record)
    assert notes[-1] == ('switch.tv', 'room empty for 5 min')
    assert len(notes) == 2


def test_clock_backwards_restarts_the_wait_and_a_failed_log_retries():
    notes = []
    watch = Watch(config(device=dict(unoccupied_minutes=5)))
    read = lambda entity: snap(entity, 'off')
    record = record_into(notes)
    watch.tick(T + 100, read, record)
    watch.tick(T, read, record)
    watch.tick(T + 299, read, record)
    assert notes == []
    watch.tick(T + 300, read, record)
    assert len(notes) == 1

    def boom(*_args):
        raise RuntimeError('log')

    again = Watch(config(device=dict(unoccupied_minutes=5)))
    again.tick(T, read, boom)
    again.tick(T + 300, read, boom)
    again.tick(T + 301, read, record)
    assert notes[-1][0] == 'switch.tv'


def test_home_and_vacation_log_without_a_plug_write():
    notes = []
    watch = Watch(config(home='person.emil', away_minutes=5, vacation='input_boolean.vacation'))
    states = {'binary_sensor.office': 'on', 'person.emil': 'home', 'input_boolean.vacation': 'off'}

    def read(entity):
        return snap(entity, states[entity])

    record = record_into(notes)
    watch.tick(T, read, record)
    states['person.emil'] = 'not_home'
    states['input_boolean.vacation'] = 'on'
    watch.tick(T, read, record)
    watch.tick(T + 299, read, record)
    assert notes == [('vacation', 'vacation')]
    watch.tick(T + 300, read, record)
    watch.tick(T + 600, read, record)
    assert notes == [('vacation', 'vacation'), ('home', 'home empty for 5 min')]
    states['input_boolean.vacation'] = 'unknown'
    watch.tick(T + 601, read, record)
    states['input_boolean.vacation'] = 'on'
    watch.tick(T + 602, read, record)
    assert notes[-1] == ('vacation', 'vacation')
    assert all(note[0] != 'write' for note in notes)


def test_read_errors_do_not_count_as_empty_and_disabled_run_is_silent(monkeypatch):
    import homeassistant as ha
    get = Mock(side_effect=OSError('down'))
    post = Mock()
    monkeypatch.setattr(ha.requests, 'get', get)
    monkeypatch.setattr(ha.requests, 'post', post)
    watch = Watch(config(device=dict(unoccupied_minutes=5), home='binary_sensor.home'))
    run(watch, T)
    run(watch, T + 1000)
    post.assert_not_called()
    assert get.call_count == 4
    run(Watch(dict(enabled=True, devices=[])), T)
    assert get.call_count == 4


def test_adapter_gets_the_named_entity_and_never_posts(monkeypatch, capsys):
    import homeassistant as ha
    watch = Watch(config(device=dict(occupied='binary_sensor.office', unoccupied_minutes=5),
                         vacation='input_boolean.vacation'))

    def get(url, **kwargs):
        assert kwargs['verify'] == ha._VERIFY and kwargs['timeout'] == 5
        entity = url.rsplit('/', 1)[-1]
        if entity == 'binary_sensor.office':
            get.office += 1
            body = snap('binary_sensor.other', 'off') if get.office > 1 else snap(entity, 'off')
        else:
            body = snap(entity, 'on')
        return Mock(json=Mock(return_value=body))

    get.office = 0
    get_mock = Mock(side_effect=get)
    post = Mock()
    monkeypatch.setattr(ha.requests, 'get', get_mock)
    monkeypatch.setattr(ha.requests, 'post', post)
    run(watch, T)
    run(watch, T + 300)
    urls = [call.args[0] for call in get_mock.call_args_list]
    assert any(url.endswith('/binary_sensor.office') for url in urls)
    assert any(url.endswith('/input_boolean.vacation') for url in urls)
    post.assert_not_called()
    err = capsys.readouterr().out
    assert 'Smart plugs: vacation' in err
    assert 'room empty' not in err
