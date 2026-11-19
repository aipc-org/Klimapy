"""Verify every Cargo vendor checksum; optionally require every input in Git.

Run before release: python tools/check_vendor.py --git-index
This catches ignored upstream build/ or dist/ directories missing from checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--git-index', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tracked = None
    if args.git_index:
        tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0'))
    manifests = list((root / 'rust/vendor-crates').glob('*/.cargo-checksum.json'))
    if not manifests:
        raise RuntimeError('Cargo vendor inputs are missing')
    count = 0
    for manifest in manifests:
        paths = json.loads(manifest.read_text())['files']
        for name, expected in paths.items():
            source = manifest.parent / name
            relative = source.relative_to(root).as_posix()
            if tracked is not None and relative not in tracked:
                raise RuntimeError('Required Cargo input is not tracked: ' + relative)
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Missing or changed Cargo input: ' + relative)
            count += 1
    print(f'Verified {count} files from {len(manifests)} Cargo vendor packages')


if __name__ == '__main__':
    main()
