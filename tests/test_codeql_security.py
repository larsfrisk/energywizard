"""Behavioral regressions for repository code-scanning remediation."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
import subprocess
import subprocess

import pytest
from fastapi import FastAPI, HTTPException

import i18n_routes
from public_errors import validation_message
import webauth

ROOT = Path(__file__).resolve().parents[1]


def test_spa_sheet_dom_input_is_escaped():
    subprocess.run(['node', 'tests/test_codeql_dom.cjs'], cwd=ROOT, check=True)


def test_spa_sheet_dom_input_is_escaped():
    subprocess.run(['node', 'tests/test_codeql_dom.cjs'], cwd=ROOT, check=True)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Request:
    def __init__(self, body=None, cookies=None):
        self.body = body or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.client = SimpleNamespace(host='127.0.0.1')

    async def json(self):
        return self.body


@pytest.fixture(scope='module')
def apps():
    with pytest.MonkeyPatch.context() as patch:
        # Generated icon assets are not needed for direct route/security tests.
        from starlette.staticfiles import StaticFiles
        original_init = StaticFiles.__init__
        patch.setattr(StaticFiles, '__init__', lambda self, *args, **kwargs:
                      original_init(self, *args, **{**kwargs, 'check_dir': False}))
        patch.setenv('DASHBOARD_PASSWORD', 'security-tests-only')
        patch.setattr(webauth, 'PASSWORD', 'security-tests-only')
        patch.chdir(ROOT / 'ewapp')
        ew = load_module('security_ewapp', ROOT / 'ewapp/app.py')
        patch.chdir(ROOT / 'webdashboard')
        web = load_module('security_web', ROOT / 'webdashboard/app.py')
        yield ew, web


def test_session_domain_separation_rotation_and_proxy_compatibility(apps, monkeypatch):
    ew, web = apps
    assert web._EWAPP_SECRET == ew.SECRET == webauth.session_key('security-tests-only', 'ewapp')
    assert ew._session(Request(cookies={'ew': web._ewapp_cookie()})) == ('owner', 'owner')
    auth = webauth.Auth('security-test')
    old = auth.sign(int(time.time()) + 60)
    assert auth.session(Request(cookies={'ew': old})) == ('owner', 'owner')
    monkeypatch.setattr(webauth, 'PASSWORD', 'new-security-test-value')
    assert auth.session(Request(cookies={'ew': old})) == (None, None)
    assert webauth.session_key('same', 'ewapp') != webauth.session_key('same', 'webdash')


def test_setting_identifiers_cannot_reach_sql(apps, monkeypatch):
    ew, _ = apps
    seen = []

    class Engine:
        def begin(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, query, params):
            seen.append((str(query), params))

    monkeypatch.setattr(ew, 'ENGINE', Engine())
    monkeypatch.setattr(ew, 'logact', lambda *args: None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(ew.set_setting(Request({'key': 'temp_cheap = 0; DROP TABLE system_settings; --', 'value': 20})))
    assert error.value.status_code == 400 and not seen
    assert asyncio.run(ew.set_setting(Request({'key': 'temp_cheap', 'value': 20})))['ok']
    assert seen == [('UPDATE system_settings SET temp_cheap = :v WHERE id = 1', {'v': 20.0})]


def test_translation_files_use_existing_directory_entries(tmp_path, monkeypatch):
    root = tmp_path / 'i18n'
    root.mkdir()
    (root / 'en.json').write_text('{}')
    secret = tmp_path / 'private.json'
    secret.write_text('private')
    monkeypatch.setattr(i18n_routes, 'DIR', str(root))
    app = FastAPI()
    i18n_routes.register(app)
    endpoint = next(r.endpoint for r in app.routes if r.path == '/i18n/{name}')
    assert Path(endpoint('en.json').path) == root / 'en.json'
    for name in ['../private.json', '/etc/passwd', 'en.json\n', 'en.json\x00', 'en.json/../../private.json']:
        assert endpoint(name).status_code == 404
    try:
        (root / 'cs.json').symlink_to(secret)
    except OSError:
        return
    assert endpoint('cs.json').status_code == 404


def test_public_errors_never_echo_unknown_exception_details(apps, monkeypatch):
    ew, web = apps
    private = 'private-host:password /server/config.py Traceback: SELECT credentials'
    assert validation_message(ValueError(private)) == 'Ogiltigt värde'
    assert validation_message(ValueError('Sju dagar behövs')) == 'Sju dagar behövs'

    def fail(*args, **kwargs):
        raise RuntimeError(private)

    monkeypatch.setattr(ew, 'states', fail)
    assert private not in json.dumps(ew.state(Request()))
    monkeypatch.setattr(web.requests, 'get', fail)
    assert private not in json.dumps(asyncio.run(web.price_entities()))


def test_setup_rejects_oversized_entity_without_changing_valid_mapping(apps):
    _, web = apps
    oversized = '_' * 200_000
    selected = {'heat_pump': {'driver': 'ha_entities', 'entities': {'room_temp': oversized}}}
    assert oversized not in web._build_house_config_yaml(selected)
    selected['heat_pump']['entities']['room_temp'] = 'sensor.living_room'
    assert 'room_temp: sensor.living_room' in web._build_house_config_yaml(selected)


def test_authorization_utility_keeps_credentials_out_of_terminal(tmp_path, monkeypatch, capsys):
    mod = load_module('security_authorize', ROOT / 'scripts/myuplink_authorize.py')
    target = tmp_path / 'myuplink.env'
    monkeypatch.setattr(mod, 'CLIENT_ID', 'test-client-id')
    monkeypatch.setattr(mod, 'CLIENT_SECRET', 'synthetic-client-secret')
    monkeypatch.setattr(mod.sys, 'argv', ['authorize', '--output', str(target)])
    monkeypatch.setattr('builtins.input', lambda *args: 'test-code')
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'refresh_token': 'synthetic-refresh-token'})
    monkeypatch.setattr(mod.requests, 'post', lambda *args, **kwargs: response)
    mod.main()
    out = capsys.readouterr().out
    assert 'synthetic-client-secret' not in out and 'synthetic-refresh-token' not in out
    assert 'synthetic-refresh-token' in target.read_text()
    if os.name != 'nt':
        assert target.stat().st_mode & 0o777 == 0o600
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        mod.save_credentials(target, 'replacement')
    assert target.read_bytes() == original
