"""Native ARM builds preserve both-platform security and publication gates."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'),
                     Loader=yaml.BaseLoader)


def test_security_matrix_uses_native_arm_without_losing_coverage():
    job = workflow('security.yml')['jobs']['images']
    assert job['runs-on'] == "${{ matrix.platform == 'linux/arm64' && 'ubuntu-24.04-arm' || 'ubuntu-latest' }}"
    entries = job['strategy']['matrix']['include']
    assert {e['name'] for e in entries} == {
        'smartbox', 'webdashboard', 'ewapp', 'telemetry', 'addon-amd64', 'addon-arm64',
    }
    assert next(e for e in entries if e['name'] == 'addon-arm64')['platform'] == 'linux/arm64'
    assert not any('setup-qemu' in s.get('uses', '') for s in job['steps'])
    assert job['steps'][-1]['uses'] == './.github/actions/audit-image'


def test_release_retains_fresh_audited_images_and_both_architecture_gate():
    jobs = workflow('docker.yml')['jobs']
    build = jobs['allt-i-ett-bygg']
    assert build['runs-on'] == "${{ matrix.arch == 'arm64' && 'ubuntu-24.04-arm' || 'ubuntu-latest' }}"
    assert build['strategy']['matrix']['arch'] == ['amd64', 'arm64']
    assert build['needs'] == 'tester'
    steps = build['steps']
    assert not any('setup-qemu' in s.get('uses', '') for s in steps)
    image = next(s for s in steps if 'docker/build-push-action@' in s.get('uses', ''))
    assert image['with']['platforms'] == 'linux/${{ matrix.arch }}'
    assert image['with']['pull'] == image['with']['no-cache'] == 'true'
    assert image['with']['push'] == 'false'
    audit = next(i for i, s in enumerate(steps) if s.get('uses') == './.github/actions/audit-image')
    login = next(i for i, s in enumerate(steps) if 'docker/login-action@' in s.get('uses', ''))
    assert audit < login
    assert jobs['allt-i-ett']['needs'] == 'allt-i-ett-bygg'
    assert jobs['tillagg']['needs'] == 'allt-i-ett'
