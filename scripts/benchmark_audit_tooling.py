"""Compare empty/warm download caches using new, otherwise identical audit venvs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REQUIREMENTS = Path(__file__).resolve().parents[1] / '.github/actions/audit-image/requirements.txt'


def measure(root, repeats=2):
    results = []
    for repeat in range(repeats):
        cache = root / f'cache-{repeat}'
        inventories = []
        for state in ('cold', 'warm'):
            env = root / f'env-{repeat}-{state}'
            subprocess.run([sys.executable, '-m', 'venv', str(env)], check=True)
            python = str(env / 'bin/python')
            start = time.monotonic()
            subprocess.run([python, '-m', 'pip', '--disable-pip-version-check', 'install',
                            '--cache-dir', str(cache), '-r', str(REQUIREMENTS)], check=True)
            duration = time.monotonic() - start
            inventory = json.loads(subprocess.check_output([python, '-m', 'pip', 'list', '--format=json'], text=True))
            inventories.append(sorted(inventory, key=lambda x: x['name'].lower()))
            results.append({'repeat': repeat, 'cache': state, 'install_s': round(duration, 3),
                            'inventory': inventories[-1], 'cached_files': sum(p.is_file() for p in cache.rglob('*'))})
        if inventories[0] != inventories[1]:
            raise ValueError('Dependency resolution changed; cold/warm measurements are not comparable')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ew-audit-tooling-') as root:
        results = measure(Path(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'python': sys.version, 'results': results}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
