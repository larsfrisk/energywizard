"""Opt-in local EnergyHub battery control; unverified on hardware.

Auto/charge/discharge and optional verified native standby are supported. RevD's default-mode description is
ambiguous; writes require explicit confirmation that mode 0 releases control on
the installation's firmware. Neither solar-only hold nor exact idle is assumed.
"""
import math
import time

from drivers.battery import BatteryDriver
from drivers.ferroamp_modbus import (
    EnergyHubConnection, read_float, read_words, shadow_write, write_float, write_word,
)


class FerroampBatteryDriver(BatteryDriver):
    def __init__(self, modbus=None, control_enabled=False, default_mode_verified=False,
                 max_power_w=5000.0, reserve_soc=20.0, max_soc=100.0,
                 live_control_confirmed=False, exclusive_owner_confirmed=False,
                 standby_reference_w=None, standby_verified=False, module_telemetry=None,
                 maintenance_soc=None, command_transport='modbus', mqtt=None, mqtt_control_verified=False):
        self._bus = EnergyHubConnection(modbus)
        if command_transport not in ('modbus', 'mqtt'):
            raise ValueError('Select modbus or mqtt explicitly; no automatic command fallback')
        self.command_transport = command_transport
        self._mqtt = None
        if command_transport == 'mqtt':
            from drivers.ferroamp_mqtt import CommandClient
            self._mqtt = CommandClient(mqtt, identity={'host': self._bus.host, 'port': self._bus.port,
                                                      'unit_id': self._bus.unit_id})
        verified = mqtt_control_verified if command_transport == 'mqtt' else default_mode_verified
        self._enabled = control_enabled is True and verified is True
        self._live_in_shadow = (self._enabled and live_control_confirmed is True
                                and exclusive_owner_confirmed is True)
        self._standby_w = None
        self._pending_reference = None
        self._pending_release = False
        self._maintenance = False
        self._maintenance_soc = None
        if maintenance_soc is not None:
            if type(maintenance_soc) not in (int,float) or not math.isfinite(maintenance_soc) or not 50 <= maintenance_soc <= 100:
                raise ValueError('Explicit verified maintenance SOC required')
            self._maintenance_soc = float(maintenance_soc)
        self._modules = None
        if (module_telemetry or {}).get('enabled') is True:
            from drivers.ferroamp_modules import ModuleTelemetry
            self._modules = ModuleTelemetry(module_telemetry)
        if standby_verified is True:
            if (type(standby_reference_w) not in (int,float) or not math.isfinite(standby_reference_w)
                    or not 0 < standby_reference_w <= 50):
                raise ValueError('Verified standby requires an explicit small positive reference')
            self._standby_w = float(standby_reference_w)
        self._max_power = float(max_power_w)
        self._reserve, self._max_soc = float(reserve_soc), float(max_soc)
        if not math.isfinite(self._max_power) or not 0 < self._max_power <= 1e9:
            raise ValueError("EnergyHub max_power_w must be finite and positive")
        if not 0 <= self._reserve < self._max_soc <= 100:
            raise ValueError("EnergyHub SOC limits must satisfy 0 <= reserve < max <= 100")
        if self._standby_w is not None and self._standby_w > self._max_power:
            raise ValueError('Standby reference exceeds configured maximum power')

    def supports_control(self):
        return bool(self._bus.host) and self._enabled

    def supported_intents(self):
        return ({"auto", "charge", "discharge"} | ({"standby"} if self._standby_w is not None else set())) if self.supports_control() else set()

    def read_state(self):
        state = {"soc_pct": None, "power_w": None, "capacity_kwh": None, "mode": None}
        if self._modules is not None:
            self._modules.start()
            state['modules'] = self._modules.snapshot()
        unit = self._bus.unit_id
        with self._bus.connect() as client:
            if client is None:
                return state
            soc = read_float(client, 6016, unit)
            state["soc_pct"] = soc if soc is not None and 0 <= soc <= 100 else None
            state["soc_sample_at"] = time.time() if state["soc_pct"] is not None else None
            state["soc_source"] = "modbus_received"
            power = read_float(client, 6100, unit)
            state["power_w"] = -power * 1000 if power is not None else None
            state["power_sample_at"] = time.time() if power is not None else None
            capacity = read_float(client, 6008, unit)
            state["capacity_kwh"] = capacity if capacity is not None and capacity > 0 else None
            mode = read_words(client, 6104, 1, unit)
            state["mode"] = str(mode[0]) if mode is not None else None
        return state

    def set_mode(self, mode):
        return self.apply_intent(mode)

    def supports_maintenance(self):
        return self.supports_control() and self._maintenance_soc is not None and self._standby_w is not None

    def set_balancing(self, active):
        self._maintenance = active is True and self.supports_maintenance()

    def close(self):
        try:
            if self._modules is not None:
                self._modules.stop()
        finally:
            if self._mqtt is not None:
                self._mqtt.close()

    def apply_intent(self, intent, power_w=None):
        self.command_reference_verified = False
        self.command_protocol_acknowledged = False
        if intent not in self.supported_intents():
            return False
        power = 0.0
        if intent == 'standby':
            if power_w is not None and (type(power_w) not in (int,float) or not math.isfinite(power_w)
                                        or abs(power_w-self._standby_w) > .001):
                return False
            power = min(self._standby_w, self._max_power) / 1000
        elif intent != "auto":
            if isinstance(power_w, bool):
                return False
            try:
                watts = self._max_power if power_w is None else float(power_w)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(watts) or watts <= 0:
                return False
            power = min(watts, self._max_power) / 1000
            if intent == "charge":
                power = -power
        if not self._live_in_shadow and shadow_write(f"battery {intent}, reference={power:g} kW"):
            return True
        if self._mqtt is not None and intent == 'auto':
            result = self._mqtt.request('auto')  # Release does not require available SOC/Modbus.
            self.command_protocol_acknowledged = self._mqtt.protocol_acknowledged
            return result
        unit = self._bus.unit_id
        with self._bus.connect() as client:
            if client is None:
                return False
            if self._pending_release:
                if read_words(client, 6104, 1, unit) != [0]:
                    return False
                self._pending_release = False
                self._pending_reference = None
                if intent == 'auto':
                    self.command_reference_verified = True
                    return True
            if intent == "auto":
                self.command_reference_verified = self._release(client)
                return self.command_reference_verified
            # Fresh device SOC on every forced request; never rely on an old plan.
            soc = read_float(client, 6016, unit)
            if soc is None or not 0 <= soc <= 100:
                return False
            ceiling = self._maintenance_soc if self._maintenance else self._max_soc
            if (intent in {"discharge", "standby"} and soc <= self._reserve) or (intent == "charge" and soc >= ceiling):
                return False
            if self._mqtt is not None:
                result = self._mqtt.request('discharge' if intent == 'standby' else intent, abs(power)*1000)
                self.command_protocol_acknowledged = self._mqtt.protocol_acknowledged
                return result
            if self._pending_reference is not None:
                if not self._matches(client, self._pending_reference):
                    return False
                confirmed = self._pending_reference
                self._pending_reference = None
                if abs(confirmed-power) <= .000001:
                    self.command_reference_verified = True
                    return True
            self._pending_reference = power
            if not write_float(client, 6064, power, unit):
                return False
            if write_word(client, 6000, 1, unit) and self._bus.verify(lambda: self._matches(client, power)):
                self.command_reference_verified = True
                self._pending_reference = None
                return True
            # If activation/verification failed, try to release, never report success.
            self._release(client)
        return False

    def _matches(self, client, power):
        mode = read_words(client, 6104, 1, self._bus.unit_id)
        reference = read_float(client, 6106, self._bus.unit_id)
        return mode == [1] and reference is not None and abs(reference - power) <= 0.001

    def _release(self, client):
        self._pending_release = True
        confirmed = write_word(client, 6000, 0, self._bus.unit_id) and self._bus.verify(
            lambda: read_words(client, 6104, 1, self._bus.unit_id) == [0])
        if confirmed:
            self._pending_release = False
            self._pending_reference = None
        return confirmed
