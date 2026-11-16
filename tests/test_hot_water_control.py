"""Real-command lifecycle with fake transport; no hardware access."""
from copy import deepcopy

import pytest

from hot_water_control import BoostController


CONTEXT = 'a' * 64


class Heater:
    value = False
    deliver = True

    def __init__(self):
        self.calls = []

    def read_hot_water_boost(self):
        return self.value

    def set_hot_water_boost(self, active):
        self.calls.append(active)
        if self.deliver:
            self.value = active
        return False  # readback, rather than an acknowledgement, decides


def setup():
    heater, journal = Heater(), {}

    def save(state):
        journal.clear()
        journal.update(deepcopy(state))

    controller = BoostController(heater, lambda: deepcopy(journal), save, context_id=CONTEXT)
    controller.arm(now=0, start=10, end=100, deadline=120, target_c=60,
                   max_runtime_s=50, max_age_s=30, allow_receipt=True)
    return controller, heater, journal, save


def tick(controller, now=10, temp=40, **guards):
    options = dict(shadow=False, ownership_confirmed=True, permitted=True)
    options.update(guards)
    return controller.tick({'value_c': temp, 'sample_at': now,
                            'timestamp_basis': 'local_receipt'}, now=now, **options)


def test_start_then_target_release_once():
    c, h, _, _ = setup()
    assert tick(c, 9)['state'] == 'planned'
    assert tick(c)['state'] == 'active'
    assert tick(c, 11, 60)['state'] == 'complete'
    tick(c, 12)
    assert h.calls == [True, False]


@pytest.mark.parametrize('now,guards,reason', [
    (60, {}, 'runtime_limit'), (11, {'cancel': True}, 'cancelled'),
    (11, {'away': True}, 'guard_lost'), (11, {'permitted': False}, 'guard_lost'),
    (5, {}, 'restart_or_clock_recovery'),
])
def test_owned_stops(now, guards, reason):
    c, h, _, _ = setup()
    tick(c)
    assert tick(c, now, **guards)['reason'] == reason
    assert h.calls == [True, False]


@pytest.mark.parametrize('guard', ['shadow', 'manual', 'hygiene', 'ownership_confirmed'])
def test_authority_change_never_writes_or_resumes(guard):
    c, h, _, _ = setup()
    tick(c, **{guard: guard != 'ownership_confirmed'})
    tick(c, 11)
    assert h.calls == []


def test_stale_observation_releases_owned_cycle():
    c, h, _, _ = setup()
    tick(c)
    result = c.tick({'value_c': 40, 'sample_at': 0, 'timestamp_basis': 'source'},
                    now=40, shadow=False, ownership_confirmed=True, permitted=True)
    assert result['reason'] == 'freshness_lost'
    assert h.calls == [True, False]


def test_ambiguous_start_not_replayed_and_late_delivery_released():
    c, h, _, _ = setup()
    h.deliver = False
    assert tick(c)['state'] == 'start_pending'
    tick(c, 70)
    assert h.calls == [True]
    h.value, h.deliver = True, True
    assert tick(c, 71)['state'] == 'complete'
    assert h.calls == [True, False]


def test_ambiguous_release_not_replayed():
    c, h, _, _ = setup()
    tick(c)
    h.deliver = False
    assert tick(c, 60)['state'] == 'release_pending'
    tick(c, 61)
    assert h.calls == [True, False]
    h.value = False
    assert tick(c, 62)['state'] == 'complete'


def test_restart_owned_boost_only_releases():
    c, h, journal, save = setup()
    tick(c)
    recovered = BoostController(h, lambda: journal.copy(), save, context_id=CONTEXT)
    assert recovered.status()['recovery_required']
    assert tick(recovered, 11)['state'] == 'complete'
    assert h.calls == [True, False]


def test_restart_planned_does_not_start():
    c, h, journal, save = setup()
    recovered = BoostController(h, lambda: journal.copy(), save, context_id=CONTEXT)
    tick(recovered)
    assert h.calls == []


def test_storage_failure_prevents_command():
    c, h, _, _ = setup()

    def fail(state):
        raise OSError('private detail')

    c.save = fail
    assert tick(c)['state'] == 'storage_error'
    assert h.calls == []


def test_external_boost_is_not_owned():
    c, h, _, _ = setup()
    h.value = True
    assert tick(c)['reason'] == 'external_boost'
    tick(c, 70)
    assert h.calls == []


@pytest.mark.parametrize('field,value', [('mode', 'shadow'), ('context_id', 'b'*64),
                                         ('max_runtime_s', float('nan')), ('phase', 'bogus')])
def test_invalid_journals_cannot_authorize_writes(field, value):
    c, h, journal, save = setup()
    journal[field] = value
    recovered = BoostController(h, lambda: journal.copy(), save, context_id=CONTEXT)
    assert tick(recovered)['state'] == 'storage_error'
    assert h.calls == []


def test_late_start_keeps_original_end():
    c, h, _, _ = setup()
    assert tick(c, 90)['state'] == 'active'
    assert tick(c, 100)['state'] == 'complete'
    assert h.calls == [True, False]


def test_journal_intent_precedes_transport():
    c, h, journal, _ = setup()
    original = h.set_hot_water_boost

    def send(active):
        assert journal['phase'] == ('start_pending' if active else 'release_pending')
        return original(active)

    h.set_hot_water_boost = send
    tick(c)
    tick(c, 60)
    assert h.calls == [True, False]


@pytest.mark.parametrize('now,temp,boost', [(100, 40, False), (10, 60, False), (10, 40, None)])
def test_no_start_for_expired_satisfied_or_unknown(now, temp, boost):
    c, h, _, _ = setup()
    h.value = boost
    tick(c, now, temp)
    assert h.calls == []


def test_restart_pending_release_only_observes():
    c, h, journal, save = setup()
    tick(c)
    h.deliver = False
    tick(c, 60)
    recovered = BoostController(h, lambda: journal.copy(), save, context_id=CONTEXT)
    tick(recovered, 61)
    assert h.calls == [True, False]
    h.value = False
    assert tick(recovered, 62)['state'] == 'complete'


def test_target_requires_observation_after_start():
    c, h, _, _ = setup()
    tick(c)
    tick(c, 10, 60)
    assert h.calls == [True]
