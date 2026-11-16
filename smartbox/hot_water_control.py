"""Bounded single-writer boost controller; no default engine hook or cloud path."""
from math import isfinite

from hot_water_observation import assess


def _number(value):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError("Finite control value required")
    return value


class BoostController:
    """Caller owns exclusive heater authority and private atomic journal callbacks.

    One instance per heater, called serially. A restart never resumes heating:
    it permits only reconciliation/release with explicitly confirmed ownership.
    Shadow-cycle journals are not accepted as control authority.
    """
    def __init__(self, driver, load, save, *, context_id):
        if (not isinstance(context_id, str) or len(context_id) != 64
                or any(c not in '0123456789abcdef' for c in context_id)):
            raise ValueError("Explicit control context required")
        self.driver, self.save, self.context = driver, save, context_id
        self.state = {}
        self.storage_error = False
        self.recovery = False
        try:
            saved = load()
            if not isinstance(saved, dict):
                raise ValueError("Invalid control journal")
            if saved:
                if (saved.get('schema') != 1 or saved.get('mode') != 'control'
                        or saved.get('context_id') != context_id
                        or saved.get('phase') not in {'planned', 'start_pending', 'active',
                                                       'release_pending', 'complete', 'interrupted'}):
                    raise ValueError("Unknown control journal")
                for field in ('start', 'end', 'deadline', 'target_c', 'max_runtime_s',
                              'max_age_s', 'last_at'):
                    _number(saved[field])
                if (not saved['start'] < saved['end'] <= saved['deadline']
                        or not 0 < saved['target_c'] <= 65
                        or not 0 < saved['max_runtime_s'] <= 21600
                        or saved['max_age_s'] <= 0 or type(saved['allow_receipt']) is not bool):
                    raise ValueError("Invalid saved policy")
                if saved['phase'] in {'start_pending', 'active', 'release_pending'}:
                    _number(saved['attempted_at'])
                self.state = saved
                self.recovery = saved['phase'] in {'start_pending', 'active', 'release_pending'}
                if saved['phase'] == 'planned':
                    self._store(phase='interrupted', reason='restart_before_start')
        except Exception:
            self.storage_error = True

    def _store(self, **fields):
        state = {**self.state, **fields}
        try:
            self.save(dict(state))
        except Exception:
            self.storage_error = True
            return False
        self.state = state
        return True

    def status(self):
        return {'state': 'storage_error' if self.storage_error else self.state.get('phase', 'empty'),
                'reason': self.state.get('reason'), 'recovery_required': self.recovery}

    def arm(self, *, now, start, end, deadline, target_c, max_runtime_s,
            max_age_s, allow_receipt=False):
        now, start, end, deadline, target_c, runtime, age = map(
            _number, (now, start, end, deadline, target_c, max_runtime_s, max_age_s))
        if (not now <= start < end <= deadline or deadline - now > 36 * 3600
                or not 0 < target_c <= 65 or not 0 < runtime <= 21600 or age <= 0
                or type(allow_receipt) is not bool):
            raise ValueError("Explicit bounded boost policy required")
        if not self.storage_error and not self.state:
            self._store(schema=1, mode='control', context_id=self.context, phase='planned',
                        start=start, end=end, deadline=deadline, target_c=target_c,
                        max_runtime_s=runtime, max_age_s=age, allow_receipt=allow_receipt,
                        last_at=now)
        return self.status()

    def _read(self):
        try:
            value = self.driver.read_hot_water_boost()
            return value if type(value) is bool else None
        except Exception:
            return None

    def _send(self, active, now, reason):
        # Durable intent precedes transport. Never repeat an ambiguous attempt.
        if self._store(phase='start_pending' if active else 'release_pending',
                       attempted_at=now, reason=reason):
            try:
                self.driver.set_hot_water_boost(active)
            except Exception:
                pass
            actual = self._read()
            if actual is active:
                if self._store(phase='active' if active else 'complete') and not active:
                    self.recovery = False
        return self.status()

    def tick(self, observation, *, now, shadow, ownership_confirmed, permitted,
             manual=False, away=False, hygiene=False, cancel=False):
        now = _number(now)
        if any(type(v) is not bool for v in
               (shadow, ownership_confirmed, permitted, manual, away, hygiene, cancel)):
            raise ValueError("Explicit boolean control guards required")
        if self.storage_error or not self.state or self.state['phase'] in {'complete', 'interrupted'}:
            return self.status()
        # Shadow must never create or execute actuator authority. A caller must
        # also keep the global transport guard enabled; this is an extra gate.
        if shadow or not ownership_confirmed or manual or hygiene:
            self._store(phase='interrupted', reason='authority_changed')
            return self.status()
        if now < self.state['last_at']:
            self.recovery = True  # stop-only reconciliation; never extend heating
        if not self._store(last_at=now):
            return self.status()
        phase = self.state['phase']
        actual = self._read()
        if actual is None:
            return self.status()
        if phase == 'release_pending':
            if actual is False:
                self._store(phase='complete')
                self.recovery = False
            return self.status()
        if phase in {'active', 'start_pending'}:
            if actual is False:
                # An uncertain start might still arrive later. Keep its latch;
                # never re-start or claim a safe release from an old observation.
                if phase == 'active':
                    self._store(phase='complete', reason='externally_released')
                    self.recovery = False
                return self.status()
            if phase == 'start_pending' and not self._store(phase='active'):
                return self.status()
            evidence = assess(observation, now=now, max_age_s=self.state['max_age_s'],
                              allow_receipt=self.state['allow_receipt'])
            fresh = evidence['state'] == 'fresh'
            reason = ('restart_or_clock_recovery' if self.recovery else
                      'cancelled' if cancel else 'guard_lost' if not permitted or away else
                      'runtime_limit' if now >= min(self.state['end'], self.state['deadline'],
                                                    self.state['attempted_at'] + self.state['max_runtime_s']) else
                      'freshness_lost' if not fresh else
                      'target_observed' if observation['sample_at'] > self.state['attempted_at']
                      and observation['value_c'] >= self.state['target_c'] else None)
            if reason:
                return self._send(False, now, reason)
            return self.status()
        if cancel or away or self.recovery or now >= self.state['end']:
            self._store(phase='complete', reason='cancelled_or_window_expired')
        elif actual is True:
            self._store(phase='interrupted', reason='external_boost')
        elif now >= self.state['start'] and permitted:
            evidence = assess(observation, now=now, max_age_s=self.state['max_age_s'],
                              allow_receipt=self.state['allow_receipt'])
            if evidence['state'] == 'fresh':
                if observation['value_c'] >= self.state['target_c']:
                    self._store(phase='complete', reason='target_already_observed')
                else:
                    return self._send(True, now, 'scheduled_start')
        return self.status()
