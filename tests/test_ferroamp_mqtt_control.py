"""Native MQTT command transaction contract; command sinks and isolated journals only."""
import json
import os
from types import SimpleNamespace

import pytest

import battery_commands
import shadow
from drivers.ferroamp_mqtt import CommandClient
from drivers.battery_ferroamp import FerroampBatteryDriver
from drivers.ferroamp_modbus import float_words
from house_config import build_battery_driver
from test_ferroamp_drivers import hub, MODBUS


class Client:
    def __init__(self, replies=('response', 'result')):
        self.replies = replies
        self.sent = []
        self.started = self.stopped = False
        self.codes = [0, 0]
        self.credentials = self.tls = None

    def connect_async(self, *args): self.started = True
    def loop_start(self):
        self.on_connect(self, None, None, 0)
        self.on_subscribe(self, None, 7, self.codes)
    def subscribe(self, topics):
        assert topics == [(t, 0) for t in CommandClient.TOPICS]
        return 0, 7
    def username_pw_set(self, *args): self.credentials = args
    def tls_set(self, **kwargs): self.tls = kwargs
    def publish(self, topic, payload, *, qos, retain):
        assert topic == 'extapi/control/request' and qos == 0 and retain is False
        data = json.loads(payload)
        self.sent.append(data)
        for reply in self.replies:
            self.deliver(reply, data['transId'])
        return SimpleNamespace(rc=0)
    def deliver(self, reply, identifier=None, status='ack', retain=False, dup=False):
        self.on_message(self, None, SimpleNamespace(topic='extapi/control/'+reply,
            retain=retain, dup=dup, payload=json.dumps({'transId': identifier or self.sent[-1]['transId'],
            'status': status, 'msg': 'ignored remote text'}).encode()))
    def disconnect(self): self.stopped = True
    def loop_stop(self): self.stopped = True


def channel(tmp_path, replies=('response', 'result'), **changes):
    fake = Client(replies)
    config = {'host':'192.0.2.1','timeout_s':.1,'journal_path':str(tmp_path/'command.json'),**changes}
    return CommandClient(config, client_factory=lambda: fake), fake


def test_constructor_and_passive_start_do_not_publish_or_write_journal(tmp_path):
    command, fake = channel(tmp_path)
    assert not fake.started and not list(tmp_path.iterdir())
    command.start()
    assert command.ready and fake.sent == [] and not list(tmp_path.iterdir())
    command.close()


@pytest.mark.parametrize('name,watts,expected', [('charge',500,{'name':'charge','arg':'500'}),
    ('discharge',1000,{'name':'discharge','arg':'1000'}),('auto',None,{'name':'auto'})])
def test_complete_transaction_and_private_no_credentials_journal(tmp_path, name, watts, expected):
    command, fake = channel(tmp_path)
    assert command.request(name, watts) and command.protocol_acknowledged
    assert fake.sent[0]['cmd'] == expected
    saved = json.loads((tmp_path/'command.json').read_text())
    assert saved['phase'] == 'complete' and saved['transaction_id'] == fake.sent[0]['transId']
    assert '192.0.2.1' not in json.dumps(saved)
    assert (tmp_path/'command.json').stat().st_mode & 0o777 == 0o600
    command.close()


@pytest.mark.parametrize('replies', [(), ('response',), ('result',)])
def test_timeout_does_not_republish_or_switch_commands_and_blocks_restart(tmp_path, replies):
    command, fake = channel(tmp_path, replies)
    assert not command.request('charge', 500)
    assert not command.request('charge', 500)
    assert not command.request('auto') and len(fake.sent) == 1
    assert json.loads((tmp_path/'command.json').read_text())['phase'] == 'pending'
    command.close()
    restarted, other = channel(tmp_path)
    assert not restarted.request('charge', 500) and not other.started
    restarted.close()


def test_late_completion_reconciles_without_resending_and_order_is_irrelevant(tmp_path):
    command, fake = channel(tmp_path, ())
    assert not command.request('charge', 500)
    fake.deliver('result'); fake.deliver('response')
    assert command.request('charge', 500) and command.protocol_acknowledged and len(fake.sent) == 1
    fake.replies = ('result', 'response')
    assert command.request('auto') and len(fake.sent) == 2
    command.close()


def test_rejection_is_latched_until_a_completed_release(tmp_path):
    command, fake = channel(tmp_path, ())
    assert not command.request('charge', 500)
    fake.deliver('response', status='nak')
    fake.deliver('result')  # A later ack must not erase a negative response.
    assert not command.request('charge', 500) and not command.request('discharge', 500)
    fake.replies = ('response','result')
    assert command.request('auto') and len(fake.sent) == 2
    assert command.request('charge', 500)
    command.close()


@pytest.mark.parametrize('case', ['wrong_id','retained','duplicate','wrong_topic'])
def test_unrelated_or_replayed_messages_cannot_confirm(tmp_path, case):
    command, fake = channel(tmp_path, ())
    assert not command.request('charge', 500)
    for reply in ('response','result'):
        fake.deliver('request' if case=='wrong_topic' else reply,
                     identifier='other' if case=='wrong_id' else None,
                     retain=case=='retained',dup=case=='duplicate')
    assert not command.request('charge', 500) and len(fake.sent) == 1
    command.close()


def test_subscription_failure_and_storage_failure_never_publish(tmp_path):
    command, fake = channel(tmp_path)
    fake.codes = [0, 128]
    assert not command.request('charge', 500) and fake.sent == []
    command.close()
    command, fake = channel(tmp_path)
    assert command._journal()
    command.journal.save = lambda state: (_ for _ in ()).throw(OSError('disk full'))
    assert not command.request('charge', 500) and fake.sent == []
    command.close()


def test_journal_lock_corruption_and_changed_identity_block_new_writer(tmp_path):
    command, fake = channel(tmp_path)
    assert command.request('auto')
    contender, other = channel(tmp_path)
    assert not contender.request('charge', 500) and not other.started
    contender.close(); command.close()
    command, fake = channel(tmp_path, port=1884)
    assert not command.request('auto') and fake.sent == []
    command.close()
    (tmp_path/'command.json').write_text('not-json')
    command, fake = channel(tmp_path)
    assert not command.request('auto') and fake.sent == []
    command.close()


def test_credentials_tls_are_environment_only(tmp_path, monkeypatch):
    monkeypatch.setenv('EW_TEST_MQTT_USER','synthetic-user')
    monkeypatch.setenv('EW_TEST_MQTT_PASS','synthetic-password')
    command, fake = channel(tmp_path, username_env='EW_TEST_MQTT_USER', password_env='EW_TEST_MQTT_PASS', tls=True)
    assert command.request('auto')
    assert fake.credentials == ('synthetic-user','synthetic-password') and fake.tls == {'ca_certs':None}
    assert 'synthetic' not in (tmp_path/'command.json').read_text()
    command.close()


def device(tmp_path, **changes):
    return FerroampBatteryDriver(**{**dict(modbus=MODBUS,control_enabled=True,
        command_transport='mqtt',mqtt_control_verified=True,live_control_confirmed=True,
        exclusive_owner_confirmed=True,mqtt=dict(host='192.0.2.1',timeout_s=.1,
        journal_path=str(tmp_path/'command.json'))),**changes})


def test_selected_mqtt_never_writes_modbus_and_preserves_caps_shadow_evidence(hub, tmp_path, monkeypatch):
    monkeypatch.setattr(shadow,'active',lambda:True)
    d = device(tmp_path, max_power_w=500)
    fake = Client(); d._mqtt.factory = lambda: fake
    events=[]; tracker=battery_commands.Tracker(events.append)
    assert battery_commands.apply(tracker,d,'charge',500)
    assert fake.sent[0]['cmd']=={'name':'charge','arg':'500'} and hub.writes==[]
    assert d.command_protocol_acknowledged and not d.command_reference_verified
    assert events[-1]['state']=='protocol_acknowledged' and events[-1]['driver_kind']=='ferroamp_mqtt'
    tracker.observe(tracker.current['command_id'],{'power_w':0,'power_sample_at':events[-1]['at']+1,
                    'soc_pct':50},events[-1]['at']+40)
    assert events[-1]['state']=='unconfirmed' and events[-1]['reason']=='settling'
    sent_at=tracker.current['sent_at']
    tracker.observe(tracker.current['command_id'],{'power_w':500,'power_sample_at':sent_at+60,
                    'soc_pct':50},sent_at+60)
    assert events[-1]['state']=='physically_applied'
    assert d.apply_intent('charge',1000) and fake.sent[-1]['cmd']['arg']=='500'
    assert d.apply_intent('auto') and fake.sent[-1]['cmd']=={'name':'auto'}
    d.close()


@pytest.mark.parametrize('changes',[{'mqtt_control_verified':False},{'exclusive_owner_confirmed':False},
                                    {'live_control_confirmed':False}])
def test_no_implicit_mqtt_authority_under_shadow(hub,tmp_path,monkeypatch,changes):
    monkeypatch.setattr(shadow,'active',lambda:True)
    monkeypatch.setattr(shadow,'record',lambda *a:None)
    d=device(tmp_path,**changes);fake=Client();d._mqtt.factory=lambda:fake
    d.apply_intent('charge',500)
    assert fake.sent==[] and not fake.started and hub.writes==[] and not list(tmp_path.iterdir())
    d.close()


def test_fresh_soc_and_standby_are_bounded_without_module_scaling(hub,tmp_path):
    d=device(tmp_path,standby_reference_w=10,standby_verified=True)
    fake=Client();d._mqtt.factory=lambda:fake
    hub.inputs[6016]=float_words(10)
    assert not d.apply_intent('discharge',500) and not d.apply_intent('standby')
    hub.inputs[6016]=float_words(50)
    assert d.apply_intent('standby') and fake.sent[-1]['cmd']=={'name':'discharge','arg':'10'}
    assert not d.apply_intent('hold') and not d.apply_intent('idle') and hub.writes==[]
    d.close()


def test_timeout_never_falls_back_to_modbus_and_release_survives_modbus_outage(hub,tmp_path):
    d=device(tmp_path);fake=Client(());d._mqtt.factory=lambda:fake
    assert not d.apply_intent('charge',500) and hub.writes==[]
    assert not d.apply_intent('charge',500) and len(fake.sent)==1
    fake.deliver('response');fake.deliver('result')
    fake.replies=('response','result')
    hub.connect=lambda:False
    assert d.apply_intent('auto') and hub.writes==[]
    d.close()


def test_factory_requires_separate_mqtt_verification(tmp_path):
    cfg={'battery':dict(enabled=True,driver='ferroamp_modbus',modbus=MODBUS,control='styr',
        command_transport='mqtt',default_mode_verified=True,mqtt=dict(host='192.0.2.1',journal_path=str(tmp_path/'x')))}
    assert not build_battery_driver(cfg).supports_control()
    cfg['battery']['mqtt_control_verified']=True
    assert build_battery_driver(cfg).supports_control()


def test_shadow_scope_reports_the_selected_transport_only():
    battery=dict(enabled=True,driver='ferroamp_modbus',control='styr',command_transport='mqtt',
                 exclusive_owner_confirmed=True,live_control_confirmed=True,default_mode_verified=True)
    assert shadow.scoped_controls({'battery':battery})==[]
    battery['mqtt_control_verified']=True
    assert shadow.scoped_controls({'battery':battery})==['battery']
    battery['command_transport']='invalid'
    assert shadow.scoped_controls({'battery':battery})==[]


@pytest.mark.parametrize('config',[{'host':''},{'port':True},{'timeout_s':float('nan')},
    {'timeout_s':121},{'username_env':'literal-user'},{'password_env':'PASSWORD'}, {'tls':'true'}])
def test_invalid_connection_configuration_is_rejected(tmp_path,config):
    with pytest.raises(ValueError):
        channel(tmp_path,**config)


def test_disconnect_after_publish_blocks_replay_until_matching_completion(tmp_path):
    command,fake=channel(tmp_path,())
    original=fake.publish
    def disconnecting(*args,**kwargs):
        result=original(*args,**kwargs)
        command._disconnect()
        return result
    fake.publish=disconnecting
    assert not command.request('charge',500) and len(fake.sent)==1
    assert not command.request('auto') and len(fake.sent)==1
    fake.publish=original
    command._connect(fake,None,None,0)
    command._subscribed(fake,None,7,[0,0])
    fake.deliver('response');fake.deliver('result')
    assert command.request('charge',500) and len(fake.sent)==1
    command.close()


def test_completion_storage_failure_does_not_release_or_repeat(tmp_path):
    command,fake=channel(tmp_path)
    assert command._journal()
    original=command.journal.save
    def save(state):
        if state['phase']=='complete':raise OSError('disk full')
        original(state)
    command.journal.save=save
    assert not command.request('charge',500)
    assert not command.request('auto') and len(fake.sent)==1
    assert json.loads((tmp_path/'command.json').read_text())['phase']=='pending'
    command.close()
