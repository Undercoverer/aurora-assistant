#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 scripts/test-package.py
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./scripts/check-resources.sh
./scripts/check-shader.sh

printf '\nBuild and resource checks passed. Run ./build/aurora-voice-overlay\n'
