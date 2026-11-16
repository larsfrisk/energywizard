"""Read-only native ESO MQTT receipts. No control topics, publishes or fallback."""
import hashlib
import json
import math
import os
import re
import threading
import time


def module_key(identifier):
    return 'module_' + hashlib.sha256(identifier.encode()).hexdigest()[:20]


class ModuleTelemetry:
    def __init__(self, config, *, clock=time.time, client_factory=None):
        self.config, self.clock, self.factory = dict(config), clock, client_factory
        self.host = config.get('host')
        self.port = config.get('port', 1883)
        ids = config.get('module_ids')
        if (not isinstance(self.host, str) or not self.host.strip() or type(self.port) is not int
                or not 1 <= self.port <= 65535 or not isinstance(ids, list) or not 2 <= len(ids) <= 64
                or any(not isinstance(v,str) or not 1 <= len(v) <= 128 or v.strip()!=v for v in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Explicit broker and complete unique module IDs required')
        self.ids = set(ids)
        self.samples = {}
        self.connected = False
        self.unexpected = False
        self.client = None
        self.closed = False
        self.starting = False
        self.lock = threading.RLock()

    def start(self):
        with self.lock:
            if self.client is not None or self.closed or self.starting:
                return
            self.starting = True
        client = None
        try:
            if self.factory is None:
                import paho.mqtt.client as mqtt
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='', protocol=mqtt.MQTTv311)
            else:
                client = self.factory()
            for name in ('username_env','password_env'):
                if self.config.get(name) and not re.fullmatch(r'[A-Z_][A-Z0-9_]*', self.config[name]):
                    raise ValueError('Explicit credential environment name required')
            user = os.environ.get(self.config.get('username_env',''))
            password = os.environ.get(self.config.get('password_env',''))
            if self.config.get('username_env') and not user or self.config.get('password_env') and not password:
                raise ValueError('Configured broker credential unavailable')
            if user:
                client.username_pw_set(user,password)
            if self.config.get('tls') is True:
                client.tls_set(ca_certs=self.config.get('tls_ca'))
            client.on_connect, client.on_disconnect, client.on_message = self._connect, self._disconnect, self._message
            with self.lock:
                if self.closed:
                    return
                self.client = client
            client.connect_async(self.host,self.port,30)
            client.loop_start()
        except Exception:
            with self.lock:
                self.client = None
                self.connected = False
                self.samples.clear()
            if client is not None:
                try:
                    client.disconnect()
                except Exception:
                    pass
                try:
                    client.loop_stop()
                except Exception:
                    pass
        finally:
            with self.lock:
                self.starting = False

    def _connect(self, client, userdata, flags, reason, properties=None):
        with self.lock:
            self.samples.clear()
            self.connected = reason == 0 and not self.closed
        if reason == 0:
            result, _ = client.subscribe('extapi/data/eso',qos=0)
            if result != 0:
                self._disconnect(client,None,None,None)

    def _disconnect(self, client, userdata, flags=None, reason=None, properties=None):
        with self.lock:
            self.connected = False
            self.samples.clear()

    def _message(self, client, userdata, message):
        if message.topic != 'extapi/data/eso' or message.retain or message.dup or len(message.payload) > 16384:
            return
        try:
            payload = json.loads(message.payload)
            identifier = next((payload.get(k) for k in ('id','serialNo','deviceId') if payload.get(k) is not None),None)
            if isinstance(identifier,dict):
                identifier = identifier.get('val',identifier.get('value'))
            if isinstance(identifier,bool) or not isinstance(identifier,(str,int)):
                return
            identifier = str(identifier)
            with self.lock:
                if not self.connected:
                    return
                if identifier not in self.ids:
                    self.unexpected = True
                    return
                raw = payload.get('soc')
                raw = raw.get('val',raw.get('value')) if isinstance(raw,dict) else None
                try:
                    value = float(raw)
                    if type(raw) is bool or not math.isfinite(value) or not 0 <= value <= 100:
                        raise ValueError('Invalid module SOC')
                except (TypeError,ValueError):
                    self.samples.pop(identifier,None)
                    return
                self.samples[identifier] = {'soc_pct':value,'sample_at':self.clock(),'timestamp_basis':'mqtt_receipt'}
        except (ValueError,TypeError,AttributeError):
            return

    def snapshot(self):
        now = self.clock()
        with self.lock:
            if not self.connected or self.unexpected:
                return {}
            return {module_key(v):dict(self.samples[v]) if v in self.samples and
                    0 <= now-self.samples[v]['sample_at'] <= 120 else {} for v in self.ids}

    def stop(self):
        with self.lock:
            self.closed = True
            client, self.client = self.client, None
            self.connected = False
            self.samples.clear()
        if client:
            try:
                client.disconnect()
            finally:
                client.loop_stop()
