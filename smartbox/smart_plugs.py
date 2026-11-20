"""Explicit nonessential plug price policy. No discovery enrollment.

A configured power sensor can report standby. That reading never switches the plug.
"""
from datetime import datetime
import math
import re


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def watts(snapshot):
    """Power sensor state in watts. kW is converted. Other units and words are unknown."""
    if not isinstance(snapshot,dict):return None
    raw=snapshot.get('state')
    if isinstance(raw,bool):return None
    try:value=float(raw)
    except (TypeError,ValueError):return None
    if not math.isfinite(value) or value<0:return None
    attributes=snapshot.get('attributes')
    unit=str(attributes.get('unit_of_measurement') or 'W').strip() if isinstance(attributes,dict) else 'W'
    if unit=='W':return value
    if unit=='kW':return value*1000
    return None


def policy_price(spot,strategy,at,transform):
    if not finite(spot) or not isinstance(strategy,dict) or strategy.get('price_fallback') is not False:return None
    price=transform(spot,at)
    return price if finite(price) else None


class Controller:
    def __init__(self,config):
        self.devices=[];self.state={};self.standby={}
        if not isinstance(config,dict) or config.get('enabled') is not True:return
        devices=config.get('devices',[])
        if not isinstance(devices,list) or len(devices)>32:raise ValueError('At most 32 smart plugs supported')
        seen=set()
        for item in devices:
            if not isinstance(item,dict):raise ValueError('Invalid smart plug entry')
            if item.get('enabled') is not True or item.get('nonessential') is not True or item.get('always_on',False) is not False:continue
            entity=item.get('switch','')
            high=item.get('off_above');low=item.get('restore_below')
            on=item.get('min_on_minutes',15);off=item.get('min_off_minutes',15)
            if (not isinstance(entity,str) or not re.fullmatch(r'switch\.[a-z0-9_]+',entity)
                    or entity in seen or not all(finite(v) for v in (high,low,on,off))
                    or low>=high or not 5<=on<=1440 or not 5<=off<=1440):
                raise ValueError('Invalid smart plug thresholds, dwell or switch')
            sensor=item.get('power')
            standby_w=item.get('standby_below_w',5);standby_m=item.get('standby_minutes',30)
            if sensor is not None or 'standby_below_w' in item or 'standby_minutes' in item:
                if (not isinstance(sensor,str) or not re.fullmatch(r'sensor\.[a-z0-9_]+',sensor)
                        or not finite(standby_w) or not finite(standby_m)
                        or not 0<standby_w<=100 or not 5<=standby_m<=1440):
                    raise ValueError('Invalid smart plug power sensor or standby limits')
            else:
                sensor=None
            seen.add(entity)
            self.devices.append(dict(entity=entity,high=high,low=low,on_s=on*60,off_s=off*60,
                                     power=sensor,standby_w=standby_w,standby_s=standby_m*60))

    @staticmethod
    def identity(snapshot):
        if not isinstance(snapshot,dict) or snapshot.get('state') not in ('on','off'):return None
        context=snapshot.get('context')
        if not isinstance(context,dict):return None
        context=context.get('id')
        changed=snapshot.get('last_changed')
        if not isinstance(context,str) or not context or not isinstance(changed,str):return None
        try:
            dt=datetime.fromisoformat(changed)
            if dt.utcoffset() is None:return None
        except ValueError:return None
        return snapshot['state'],context,changed

    def _note_standby(self,now,read,power,record):
        """Report an on plug that stays at or below its watt limit. Never writes."""
        if power is None or not finite(now):return
        for device in self.devices:
            sensor=device.get('power')
            if not sensor:continue
            entity=device['entity']
            try:
                identity=self.identity(read(entity))
                reading=power(sensor)
            except Exception:
                identity,reading=None,None
            low=bool(identity and identity[0]=='on' and finite(reading) and reading<=device['standby_w'])
            prev=self.standby.get(entity)
            if not low:
                self.standby.pop(entity,None)
                continue
            since=prev['since'] if prev and now>=prev['since'] else now
            noted=bool(prev and prev.get('noted') and prev['since']==since)
            if not noted and now-since>=device['standby_s'] and record:
                try:record(entity,f'standby about {reading:.0f} W')
                except Exception:noted=False
                else:noted=True
            self.standby[entity]={'since':since,'noted':noted}

    def tick(self,price,now,read,write,shadow=False,power=None,record=None):
        """read is a fresh HA GET; write returns the changed state, never an ACK.

        Missing evidence, manual changes and ambiguous writes suspend that device
        until restart. Ownership is never restored from disk or inferred from off.
        Standby is a log line only, including while shadow mode blocks writes.
        """
        self._note_standby(now,read,power,record)
        if shadow:
            self.state.clear()
            return
        if not finite(price) or not finite(now):return
        for device in self.devices:
            entity=device['entity']
            previous=self.state.get(entity)
            if previous and previous.get('paused'):continue
            try:identity=self.identity(read(entity))
            except Exception:identity=None
            if identity and datetime.fromisoformat(identity[2]).timestamp()>now+5:identity=None
            if identity is None:
                if previous:self.state[entity]={'paused':True}
                continue
            if previous is None:
                self.state[entity]={'identity':identity,'since':now,'owned':False}
                continue
            if identity!=previous['identity'] or now<previous['since']:
                self.state[entity]={'paused':True}
                continue
            turn_on=None
            if identity[0]=='on' and price>device['high'] and now-previous['since']>=device['on_s']:
                turn_on=False
            elif (identity[0]=='off' and previous['owned'] and price<device['low']
                  and now-previous['since']>=device['off_s']):
                turn_on=True
            if turn_on is None:continue
            # A failed/ambiguous transport may have changed the relay. Do not
            # retry it or infer restoration authority from the next observation.
            self.state[entity]={'paused':True}
            try:changed=self.identity(write(entity,turn_on))
            except Exception:continue
            expected='on' if turn_on else 'off'
            if changed and changed[0]==expected and changed[1]!=identity[1]:
                self.state[entity]={'identity':changed,'since':now,'owned':not turn_on}


def run(controller,price,now):
    """Isolated opt-in adapter; shares the existing HA TLS/auth/shadow safeguards."""
    if not controller.devices:return
    import homeassistant as ha
    import shadow
    def read(entity):
        response=ha.requests.get(f'{ha._BASE}/states/{entity}',headers=ha._HEADERS,timeout=5,verify=ha._VERIFY)
        response.raise_for_status()
        snapshot=response.json()
        return snapshot if isinstance(snapshot,dict) and snapshot.get('entity_id')==entity else None
    def write(entity,on):
        response=ha.requests.post(f"{ha._BASE}/services/switch/turn_{'on' if on else 'off'}",
            headers=ha._HEADERS,json={'entity_id':entity},timeout=5,verify=ha._VERIFY)
        response.raise_for_status()
        changed=response.json()
        if not isinstance(changed,list):return None
        return next((s for s in changed if isinstance(s,dict) and s.get('entity_id')==entity),None)
    def read_power(entity):
        response=ha.requests.get(f'{ha._BASE}/states/{entity}',headers=ha._HEADERS,timeout=5,verify=ha._VERIFY)
        response.raise_for_status()
        snapshot=response.json()
        return watts(snapshot) if isinstance(snapshot,dict) and snapshot.get('entity_id')==entity else None
    def record(entity,detail):
        print(f'Smart plug {entity}: {detail}')
    powered=any(device.get('power') for device in controller.devices)
    before={entity:dict(state) for entity,state in controller.state.items()}
    controller.tick(price,now,read,write,shadow=shadow.active(),
                    power=read_power if powered else None,record=record if powered else None)
    for entity,state in controller.state.items():
        if state.get('paused') and not before.get(entity,{}).get('paused'):
            print(f'Smart plug {entity}: suspended until restart; state or command ownership is uncertain')
        elif state.get('identity')!=before.get(entity,{}).get('identity'):
            print(f"Smart plug {entity}: observed {state.get('identity',('unknown',))[0]}")
