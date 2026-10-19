#!/usr/bin/env python3
"""Record or verify an offline speech-model directory. Never accesses a network."""
import argparse
import hashlib
import json
from pathlib import Path


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            with path.open('rb') as file:
                result[path.relative_to(root).as_posix()] = hashlib.file_digest(file, 'sha256').hexdigest()
    if not result:
        raise ValueError('Model directory is empty')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['record', 'verify'])
    parser.add_argument('root', type=Path)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    if args.manifest.resolve().is_relative_to(args.root.resolve()):
        parser.error('Keep the manifest outside the model directory')
    current = inventory(args.root)
    if args.operation == 'record':
        args.manifest.write_text(json.dumps(current, indent=2) + '\n')
        print(f'Recorded {len(current)} model files')
    else:
        expected = json.loads(args.manifest.read_text())
        if current != expected:
            raise SystemExit('Model manifest mismatch: modified, missing, or extra files')
        print(f'Verified {len(current)} model files')


if __name__ == '__main__':
    main()
