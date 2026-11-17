"""Cache and builder experiments preserve release/security boundaries."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_tooling_uses_one_pinned_install_without_remote_cache_overhead():
    action = yaml.load((ROOT / '.github/actions/audit-image/action.yml').read_text(), Loader=yaml.BaseLoader)
    steps = action['runs']['steps']
    setup = next(s for s in steps if 'setup-python@' in s.get('uses',''))['with']
    assert 'cache' not in setup
    install = next(s for s in steps if s.get('name') == 'Install audit tooling')
    assert '-r "$EW_AUDIT_REQUIREMENTS"' in install['run']
    assert install['run'].count('pip ')==1
    assert any('audit_image.py' in str(step) for step in action['runs']['steps'])
    # No cache action restores scans, feeds, inventories or built image layers.
    assert not any('actions/cache@' in step.get('uses', '') for step in action['runs']['steps'])
    assert 'pip-audit==2.10.1' in (ROOT / '.github/actions/audit-image/requirements.txt').read_text()


def test_benchmark_covers_native_architectures_without_publication_or_fork_privilege():
    workflow = yaml.load((ROOT / '.github/workflows/build-benchmarks.yml').read_text(), Loader=yaml.BaseLoader)
    job = workflow['jobs']['builders']
    assert job['strategy']['matrix']['arch'] == ['amd64', 'arm64']
    assert set(job['strategy']['matrix']['context']) == set(module('benchmark_image_builders').CONTEXTS)
    assert "head.repo.full_name == github.repository" in job['if']
    assert 'ubuntu-24.04-arm' in job['runs-on']
    assert workflow['permissions'] == {'contents': 'read'}
    assert set(workflow['on']) == {'workflow_dispatch'}
    assert not any('login-action' in str(step) or 'setup-qemu' in str(step) for step in job['steps'])
    assert next(s for s in job['steps'] if 'setup-buildx-action' in s.get('uses',''))['with']['version'] == 'v0.39.0'


@pytest.mark.parametrize('failed_audit', [False, True])
def test_each_trial_rebuilds_imports_starts_and_audits_exact_image(tmp_path, monkeypatch, failed_audit):
    b = module('benchmark_image_builders')
    calls = []
    monkeypatch.setattr(b, 'native_arch', lambda: 'amd64')
    monkeypatch.setattr(b, 'output', lambda *args: 'sha256:exact-built-id' if 'inspect' in args else 'test-version')
    monkeypatch.setattr(b, 'image_identity', lambda *args: {'source_sha256':'source','os_sha256':'os'})
    starts = []
    monkeypatch.setattr(b, 'startup', lambda *args: starts.append(args[0]))

    def run(*args, **kwargs):
        calls.append(args)
        if args[0] == b.sys.executable:
            if failed_audit:
                raise subprocess.CalledProcessError(1, args)
            folder = Path(args[-1]);folder.mkdir(parents=True, exist_ok=True)
            (folder/'inventory.json').write_text(json.dumps([{'name':'test','version':'1'}]))
        if args[:2] == ('docker','load'):
            pass
        # Simulate archive creation by either exporter.
        for arg in args:
            if arg.startswith('type=docker,dest='):
                Path(arg.split('dest=')[1]).touch()
            elif arg.startswith('docker-archive:/out/'):
                (tmp_path/arg.split('/out/')[1].split(':')[0]).touch()
        return subprocess.CompletedProcess(args,0)

    monkeypatch.setattr(b,'run',run)
    qualified=b.benchmark('ewapp',tmp_path,'a'*40,'feature','https://github.com/owner/repo')
    assert qualified is not failed_audit
    rows=json.loads((tmp_path/'benchmark.json').read_text())['results']
    assert len(rows)==8 and len(starts)==8
    assert sum('audit_image.py' in str(c) for c in calls)==8
    assert all(c[2]=='sha256:exact-built-id' for c in calls if c[0]==b.sys.executable)
    audits=[c for c in calls if c[0]==b.sys.executable]
    caches=[c[c.index('--grype-cache-volume')+1] for c in audits]
    assert len(set(caches))==4 and all(caches.count(c)==2 for c in set(caches))
    builds=[c for c in calls if 'bud' in c or c[:3]==('docker','buildx','build')]
    assert len(builds)==8 and all('--no-cache' in c for c in builds)
    assert all('--pull' in c or '--pull=always' in c for c in builds)
    assert not any(c[:2]==('docker','push') for c in calls)
    exports=[arg for c in calls for arg in c if arg.startswith('docker-archive:')]
    assert len(exports)==4 and all(x.startswith('docker-archive:/out/') for x in exports)
    assert all(row['qualified'] is not failed_audit for row in rows)


def test_non_native_runner_is_rejected(monkeypatch):
    b=module('benchmark_image_builders')
    monkeypatch.setattr(b.platform,'machine',lambda:'unsupported')
    with pytest.raises(ValueError):
        b.native_arch()


def test_tooling_cache_comparison_rejects_dependency_drift(tmp_path,monkeypatch):
    b=module('benchmark_audit_tooling')
    monkeypatch.setattr(b.subprocess,'run',lambda *a,**kw:None)
    answers=iter(['[{"name":"tool","version":"1"}]','[{"name":"tool","version":"2"}]'])
    monkeypatch.setattr(b.subprocess,'check_output',lambda *a,**kw:next(answers))
    with pytest.raises(ValueError,match='not comparable'):
        b.measure(tmp_path,repeats=1)
