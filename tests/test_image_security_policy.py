"""Security gates fail closed on missing evidence and retain unresolved findings."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest
import argparse
import subprocess
import sys

spec = importlib.util.spec_from_file_location('audit_image', Path(__file__).resolve().parents[1] / 'scripts/audit_image.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)


def catalog(**updates):
    return {'dateReleased': '2026-11-10T12:00:00Z', 'count': 1,
            'vulnerabilities': [{'cveID': 'CVE-2026-12345'}], **updates}


def finding(identifier='CVE-2026-99999', namespace='debian:distro:debian:13', fixed=True):
    return {'vulnerability': {'id': identifier, 'namespace': namespace,
                              'fix': {'state': 'fixed' if fixed else 'not-fixed',
                                      'versions': ['2.0'] if fixed else []}},
            'artifact': {'name': 'example', 'version': '1.0'}}


def report(*matches, valid=True):
    return {'descriptor': {'db': {'status': {'valid': valid}}}, 'matches': list(matches)}


def test_recent_catalog_and_identifiers():
    assert audit.validate_kev(catalog(), NOW) == {'CVE-2026-12345'}


@pytest.mark.parametrize('updates', [
    {'dateReleased': '2026-10-01T00:00:00Z'},
    {'dateReleased': '2026-12-01T00:00:00Z'},
    {'dateReleased': '2026-11-10T00:00:00'},
    {'vulnerabilities': [], 'count': 0}, {'count': 2},
    {'vulnerabilities': [{'cveID': 'not-a-cve'}]},
])
def test_stale_or_invalid_catalog_cannot_be_clean(updates):
    with pytest.raises(ValueError):
        audit.validate_kev(catalog(**updates), NOW)


def test_debian_backport_fix_blocks_at_any_severity():
    match = finding()
    assert audit.policy_findings(report(match), set())[0]['id'] == match['vulnerability']['id']


def test_kev_blocks_without_available_fix_and_matches_related_alias():
    match = finding(identifier='GHSA-example', namespace='github:language:python', fixed=False)
    match['relatedVulnerabilities'] = [{'id': 'CVE-2026-12345'}]
    assert audit.policy_findings(report(match), {'CVE-2026-12345'})[0]['kev'] == ['CVE-2026-12345']


def test_unfixed_and_generic_cpe_findings_are_retained_for_review_not_dropped():
    matches = report(finding(fixed=False), finding(namespace='nvd:cpe'))
    assert audit.policy_findings(matches, set()) == []
    assert len(matches['matches']) == 2


def test_invalid_or_missing_scan_evidence_fails():
    with pytest.raises(ValueError):
        audit.policy_findings(report(valid=False), set())
    with pytest.raises(KeyError):
        audit.policy_findings({}, set())


def test_inventory_is_pinned_and_rejects_requirement_injection():
    assert audit.requirements([{'name': 'pip', 'version': '26.3'}]) == 'pip==26.3\n'
    with pytest.raises(ValueError):
        audit.requirements([{'name': '--index-url', 'version': 'evil'}])
    with pytest.raises(ValueError):
        audit.requirements([{'name': 'pip', 'version': '26.3\nmalicious'}])
    with pytest.raises(ValueError):
        audit.requirements([])


def test_scanner_cache_names_cannot_be_paths_or_mount_options():
    assert audit.cache_volume('ew-benchmark-123') == 'ew-benchmark-123'
    for value in ['/var/run/docker.sock', 'cache:/secret', '../home', '', 'x' * 129]:
        with pytest.raises(argparse.ArgumentTypeError):
            audit.cache_volume(value)


def test_failed_online_cache_refresh_is_fatal_and_not_an_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['audit_image.py', 'test-image', '--output', str(tmp_path/'reports'),
                                    '--grype-cache-dir', str(tmp_path/'downloads'), '--refresh-cache-only'])
    seen=[]
    def fail(command, **kwargs):
        seen.append(command)
        assert command[-2:]==['db','update'] and kwargs['check'] is True
        raise subprocess.CalledProcessError(1,command)
    monkeypatch.setattr(audit.subprocess,'run',fail)
    with pytest.raises(subprocess.CalledProcessError):
        audit.main()
    assert len(seen)==1 and not (tmp_path/'reports/summary.json').exists()
