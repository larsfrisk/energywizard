"""Verify split UI images against isolated synthetic HA/DB and stale host code."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

POSTGRES = 'postgres:16@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f'


def docker(*args, **kwargs):
    return subprocess.check_output(['docker', *args], text=True, **kwargs).strip()


def verify(ewapp_image, webdashboard_image):
    prefix = 'ew-ui-verify-' + uuid.uuid4().hex[:12]
    network, db, ha, mobile, web = [prefix + suffix for suffix in ('-net', '-db', '-ha', '-mobile', '-web')]
    containers = []
    try:
        docker('network', 'create', '--internal', network)
        with tempfile.TemporaryDirectory(prefix='ew-ui-fixture-') as folder:
            root = Path(folder)
            (root / 'house.json').write_text(json.dumps({'house_id': 'runtime-verification', 'evs': [
                {'id': 'runtime_car', 'name': 'Runtime car', 'driver': 'generic_ev',
                 'battery_kwh': 60, 'entities': {'soc': 'sensor.runtime_soc'},
                 'charger': {'driver': 'generic', 'entities': {'status': 'sensor.runtime_charger'}}}]}))
            stale = root / 'stale'
            stale.mkdir()
            for module in ('webauth', 'local_sql', 'public_errors'):
                (stale / (module + '.py')).write_text("raise RuntimeError('Stale host module imported')\n")
            containers.append(db)
            docker('run', '-d', '--name', db, '--network', network,
                   '-e', 'POSTGRES_PASSWORD=isolated-ui-test', '-e', 'POSTGRES_DB=ui_test', POSTGRES)
            deadline = time.monotonic() + 60
            while subprocess.run(['docker', 'exec', db, 'pg_isready', '-U', 'postgres'], capture_output=True).returncode:
                if time.monotonic() > deadline:
                    raise RuntimeError('Test PostgreSQL did not start')
                time.sleep(1)
            server = """import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  body = [{'entity_id':'sensor.runtime_soc','state':'65','attributes':{}},
          {'entity_id':'sensor.runtime_charger','state':'connected','attributes':{}}] if self.path.endswith('/states') else {'time_zone':'Europe/Stockholm','language':'en'}
  self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(body).encode())
HTTPServer(('0.0.0.0',8123),Handler).serve_forever()
"""
            containers.append(ha)
            docker('run', '-d', '--name', ha, '--network', network, '--entrypoint', 'python', ewapp_image, '-c', server)
            env = {'POSTGRES_HOST': db, 'POSTGRES_USER': 'postgres', 'POSTGRES_PASSWORD': 'isolated-ui-test',
                   'POSTGRES_DB': 'ui_test', 'DASHBOARD_PASSWORD': 'isolated-ui-test',
                   'HOUSE_CONFIG_PATH': '/fixture/house.json', 'HA_URL': f'http://{ha}:8123',
                   'HA_TOKEN': 'synthetic-test-only', 'EW_NO_WATCH': '1', 'EWAPP_URL': f'http://{mobile}:8502'}
            common = ['--network', network, '-v', f'{root}:/fixture:ro', '-v', f'{stale}:/smartbox:ro']
            for key, value in env.items():
                common += ['-e', f'{key}={value}']
            bootstrap = """import sys
sys.path.insert(0,'/opt/energywizard/smartbox')
import logger,settings
logger.init_log_db(); logger.init_overrides_db(); settings.init_settings_db()
settings.get_ev_schedule(['runtime_car']); settings.get_climate_schedule(['runtime_car'])
with logger.get_db() as conn:
 with conn.cursor() as cur:
  cur.execute('CREATE TABLE IF NOT EXISTS elpriser(time_start timestamptz PRIMARY KEY,sek_per_kwh numeric)')
  cur.execute('CREATE TABLE IF NOT EXISTS ev_plan_slots(car_id text,t_slot timestamp,kw real,start_soc real,end_soc real)')
  cur.execute('INSERT INTO sensor_log(timestamp) VALUES(now())')
 conn.commit()
"""
            docker('run', '--rm', *common, '--entrypoint', 'python', ewapp_image, '-c', bootstrap)
            for name, image in ((mobile, ewapp_image), (web, webdashboard_image)):
                containers.append(name)
                docker('run', '-d', '--name', name, *common, image)
            probe = """import requests
def session(port):
 base='http://127.0.0.1:'+str(port)
 login=requests.post(base+'/api/login',json={'password':'isolated-ui-test'},timeout=3)
 assert login.status_code==200, login.status_code
 headers={'Cookie':'; '.join(k+'='+v for k,v in login.cookies.items())}
 return base,headers
base,headers=session(PORT)
def get(path):
 r=requests.get(base+path,headers=headers,timeout=10); assert r.status_code==200,(path,r.status_code,r.text[:150]); return r.json()
if PORT==8502:
 state=get('/api/state'); assert state['ok'] and state['cars'][0]['key']=='runtime_car' and state['cars'][0]['soc']==65,state
 r=requests.post(base+'/api/schedule',headers=headers,json={'car':'runtime_car','day':0,'time':'07:30','soc':80,'enabled':True},timeout=10)
 assert r.status_code==200,r.text
 assert get('/api/schedule')['runtime_car']['0']['soc']==80
else:
 data=get('/api/car'); assert data['ok'] and data['cars'][0]['id']=='runtime_car' and data['cars'][0]['soc']==65,data
 assert get('/api/schedule')['runtime_car']['0']['soc']==80
import sys
sys.path.insert(0,'/opt/energywizard/smartbox')
import webauth,public_errors,local_sql
assert all(m.__file__.startswith('/opt/energywizard/smartbox/') for m in [webauth,public_errors,local_sql])
"""
            for name, port in ((mobile, 8502), (web, 8503)):
                deadline = time.monotonic() + 90
                while True:
                    result = subprocess.run(['docker', 'exec', name, 'python', '-c', f'PORT={port}\n' + probe], capture_output=True, text=True)
                    if result.returncode == 0:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError(f'{name}: runtime verification failed: {result.stderr[-2000:]}')
                    time.sleep(2)
            return {'mobile_state': 'passed', 'schedule_roundtrip': 'passed', 'desktop_ev_proxy': 'passed',
                    'stale_host_mount': 'ignored', 'ewapp_image': ewapp_image, 'webdashboard_image': webdashboard_image}
    finally:
        for name in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', network], capture_output=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ewapp-image', required=True)
    parser.add_argument('--webdashboard-image', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.ewapp_image, args.webdashboard_image)))
