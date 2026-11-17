"""Native, unpublished builder comparison with release-style cache policy.

Both cold and warm builds force fresh RUN steps. Warm means reusing only the
builder's existing base/download state, not bypassing apt/pip with old layers.
Every exported image is imported, started in isolation and independently audited.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import uuid

BUILDAH = 'quay.io/buildah/stable@sha256:2e09edafc6f60f08d6e4091f1bbaedb1e9baddc3cc940732efb351990197fef0'
BUILDKIT = 'moby/buildkit@sha256:aa632b921ef07411d2cb77292cd34213d4f7b384001d6fceef1e1f25bf9752bb'
POSTGRES = 'postgres:16@sha256:dd2bf3ce2dc83a81674cf7f217fcfd8a5009a4b325dda5b843bfee82a06cff6f'
CONTEXTS = ('smartbox', 'ewapp', 'webdashboard', 'telemetry-collector', 'ha-addon/smartbox')
ROOT = Path(__file__).resolve().parents[1]


def run(*args, capture=False, check=True):
    return subprocess.run(list(args), check=check, text=True, capture_output=capture)


def output(*args):
    return run(*args, capture=True).stdout.strip()


def native_arch():
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if arch is None:
        raise ValueError('Native amd64 or arm64 runner required')
    return arch


def image_identity(image, context, commit):
    # Compare installed OS/Python inputs and source contents, not image IDs or
    # timestamps, which can legitimately differ between builders.
    os_inventory = output('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'dpkg-query',
                          image, '-W', '-f=${Package} ${Version}\n')
    folders = ['/smartbox', '/ewapp', '/webdashboard'] if context == 'ha-addon/smartbox' else [
        {'smartbox': '/app', 'ewapp': '/ew', 'webdashboard': '/wd', 'telemetry-collector': '/app'}[context]]
    if context in ('ewapp', 'webdashboard'):
        folders.append('/opt/energywizard/smartbox')
    code = ("import hashlib,json,pathlib; "
            f"roots={folders!r}; "
            "print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() "
            "for root in roots for p in pathlib.Path(root).rglob('*.py')}))")
    sources = json.loads(output('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3', image, '-c', code))
    expected = {}
    for directory in folders:
        source = ROOT / 'smartbox' if directory == '/opt/energywizard/smartbox' else (
            ROOT / directory.strip('/') if context == 'ha-addon/smartbox' else ROOT / context)
        for path in source.rglob('*.py'):
            expected[directory + '/' + str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if sources != expected:
        raise ValueError('Image source does not match the checked-out benchmark commit')
    return {'os_sha256': hashlib.sha256(os_inventory.encode()).hexdigest(),
            'source_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
            'commit': commit}


def startup(image, context, name):
    """No published ports or external network; never touch installation devices."""
    args = ['docker', 'run', '-d', '--name', name, '--network', 'none',
            '-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_PASSWORD=benchmark-only',
            '-e', 'POSTGRES_DB=benchmark', '-e', 'POSTGRES_HOST=127.0.0.1',
            '-e', 'DASHBOARD_PASSWORD=benchmark-only', '-e', 'EW_NO_WATCH=1']
    network, db = name + '-net', name + '-db'
    if context == 'smartbox':
        run('docker', 'network', 'create', '--internal', network)
        run('docker', 'run', '-d', '--name', db, '--network', network,
            '-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_PASSWORD=benchmark-only',
            '-e', 'POSTGRES_DB=benchmark', POSTGRES)
        args[args.index('none')] = network
        args[args.index('POSTGRES_HOST=127.0.0.1')] = 'POSTGRES_HOST=' + db
    args.append(image)
    try:
        run(*args)
        port = {'ewapp': 8502, 'webdashboard': 8503, 'telemetry-collector': 8504}.get(context)
        if context == 'ha-addon/smartbox':
            ports = [8502, 8503]
        else:
            ports = [port] if port else []
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if output('docker', 'inspect', '--format', '{{.State.Running}}', name) != 'true':
                raise RuntimeError('Image exited before startup readiness')
            if ports:
                endpoint = '/api/stats' if context == 'telemetry-collector' else '/'
                code = ("import urllib.request; " + '; '.join(
                    f"assert urllib.request.urlopen('http://127.0.0.1:{p}{endpoint}',timeout=2).status==200" for p in ports))
                if run('docker', 'exec', name, 'python3', '-c', code, capture=True, check=False).returncode == 0:
                    return
            elif 'Home Assistant är inte kopplat än' in output('docker', 'logs', name):
                return  # main reached its deliberate unconfigured-installation wait
            time.sleep(1)
        raise RuntimeError('Startup readiness timed out')
    finally:
        run('docker', 'logs', name, check=False)
        run('docker', 'rm', '-f', '-v', name, check=False)
        if context == 'smartbox':
            run('docker', 'rm', '-f', '-v', db, check=False)
            run('docker', 'network', 'rm', network, check=False)


def benchmark(context, folder, commit, ref, repo, repeats=2):
    arch = native_arch()
    folder.mkdir(parents=True, exist_ok=True)
    prefix = 'ew-bench-' + uuid.uuid4().hex[:12]
    rows = []
    metadata = {'commit': commit, 'context': context, 'arch': arch,
                'docker': output('docker', 'version', '--format', '{{.Server.Version}}'),
                'buildx': output('docker', 'buildx', 'version'), 'buildkit_image': BUILDKIT,
                'buildah_image': BUILDAH, 'cache_policy': 'pull plus no-cache for both cold/warm builds',
                'runner': {'machine': platform.machine(), 'cpu_count': os.cpu_count()}}
    metadata['tool_preparation_s'] = {}
    for tool, executable, image in [('buildah', 'buildah', BUILDAH), ('buildkit', 'buildkitd', BUILDKIT)]:
        start = time.monotonic()
        metadata[tool + '_version'] = output('docker', 'run', '--rm', '--entrypoint', executable, image, '--version')
        metadata['tool_preparation_s'][tool] = round(time.monotonic() - start, 3)
    baseline = None
    for repeat in range(repeats):
        # Alternate order to reduce warmed scanner/network bias.
        for builder in (('buildkit', 'buildah') if repeat % 2 == 0 else ('buildah', 'buildkit')):
            name = f'{prefix}-{repeat}-{builder}'
            storage = name + '-storage'
            scanner_cache = name + '-grype'
            # Each builder/repeat pays its own first feed download. A shared
            # scanner cache would incorrectly make the second builder look faster.
            run('docker', 'volume', 'create', scanner_cache)
            setup_at = time.monotonic()
            if builder == 'buildkit':
                run('docker', 'buildx', 'create', '--name', name, '--driver', 'docker-container',
                    '--driver-opt', 'image=' + BUILDKIT, '--bootstrap')
            else:
                run('docker', 'volume', 'create', storage)
            setup_s = time.monotonic() - setup_at
            buildah = ['docker', 'run', '--rm', '--privileged', '--security-opt', 'label=disable',
                       '-v', f'{ROOT}:/workspace:ro', '-v', f'{storage}:/var/lib/containers',
                       '-v', f'{folder.resolve()}:/out', '-w', '/workspace', '--entrypoint', 'buildah',
                       BUILDAH, '--storage-driver', 'overlay']
            try:
                for cache in ('cold', 'warm'):
                    trial = f'{repeat}-{builder}-{cache}'
                    image = prefix + ':' + trial
                    archive = folder / (trial + '.tar')
                    row = {'repeat': repeat, 'builder': builder, 'cache': cache,
                           'scanner_cache': cache,
                           'setup_s': round(setup_s if cache == 'cold' else 0, 3), 'qualified': False}
                    try:
                        start = time.monotonic()
                        common = ['--build-arg', 'APP_VERSION=' + commit,
                                  '--build-arg', 'ENERGYWIZARD_COMMIT=' + commit,
                                  '--build-arg', 'ENERGYWIZARD_REF=' + ref,
                                  '--build-arg', 'ENERGYWIZARD_REPO=' + repo]
                        build_context = '.' if context in ('ewapp', 'webdashboard') else context
                        dockerfile = str(ROOT / context / 'Dockerfile')
                        if builder == 'buildkit':
                            run('docker', 'buildx', 'build', '--builder', name, '--pull', '--no-cache',
                                '--platform', 'linux/' + arch, '--provenance=false', '--sbom=false',
                                '--output', f'type=docker,dest={archive.resolve()}', '-t', image,
                                *common, '-f', dockerfile, str(ROOT / build_context))
                        else:
                            run(*buildah, 'bud', '--isolation', 'chroot', '--format', 'docker', '--layers=false',
                                '--pull=always', '--no-cache', '-t', image, *common,
                                '-f', dockerfile.replace(str(ROOT), '/workspace'), build_context)
                            # This is only a local archive export, never a registry push.
                            run(*buildah, 'push', image, f'docker-archive:/out/{archive.name}:{image}')
                        row['build_export_s'] = round(time.monotonic() - start, 3)
                        start = time.monotonic()
                        run('docker', 'load', '-i', str(archive))
                        row['load_s'] = round(time.monotonic() - start, 3)
                        archive.unlink()
                        row['image_id'] = output('docker', 'image', 'inspect', '--format', '{{.Id}}', image)
                        identity = image_identity(image, context, commit)
                        start = time.monotonic()
                        startup(image, context, name + '-' + cache)
                        row['startup_s'] = round(time.monotonic() - start, 3)
                        start = time.monotonic()
                        report = folder / trial
                        run(sys.executable, str(ROOT / 'scripts/audit_image.py'), row['image_id'],
                            '--grype-cache-volume', scanner_cache, '--output', str(report))
                        row['audit_s'] = round(time.monotonic() - start, 3)
                        inventory = json.loads((report / 'inventory.json').read_text())
                        identity['python_sha256'] = hashlib.sha256(json.dumps(sorted(inventory, key=lambda x:x['name']), sort_keys=True).encode()).hexdigest()
                        row['identity'] = identity
                        if baseline is None:
                            baseline = identity
                        if identity != baseline:
                            raise ValueError('OS/Python/source inputs differ; timing comparison rejected')
                        row['qualified'] = True
                        row['total_s'] = round(sum(row[k] for k in ('setup_s', 'build_export_s', 'load_s', 'startup_s', 'audit_s')), 3)
                    except (subprocess.CalledProcessError, OSError, ValueError, RuntimeError) as error:
                        row['error'] = type(error).__name__ + ': ' + str(error)
                    finally:
                        archive.unlink(missing_ok=True)
                        run('docker', 'image', 'rm', '-f', image, check=False)
                        if builder == 'buildah':
                            run('docker', 'image', 'rm', '-f', 'localhost/' + image, check=False)
                        rows.append(row)
                        (folder / 'benchmark.json').write_text(json.dumps({'metadata': metadata, 'results': rows}, indent=2))
            finally:
                if builder == 'buildkit':
                    run('docker', 'buildx', 'rm', '-f', name, check=False)
                else:
                    run('docker', 'volume', 'rm', storage, check=False)
                run('docker', 'volume', 'rm', scanner_cache, check=False)
    return all(row['qualified'] for row in rows) and len(rows) == repeats * 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', choices=CONTEXTS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    commit = os.environ['EW_BENCH_COMMIT']
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or output('git', 'rev-parse', 'HEAD') != commit:
        parser.error('Benchmark checkout must match the exact source commit')
    return 0 if benchmark(args.context, args.output.resolve(), commit, os.environ['EW_BENCH_REF'],
                          os.environ['EW_BENCH_REPO']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
