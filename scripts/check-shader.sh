#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
shader="$(find build -name 'aurora.frag.qsb' -type f -print -quit)"
if [[ -z "$shader" ]]; then
    echo "ERROR: no generated aurora.frag.qsb found" >&2; exit 1
fi
if command -v qsb >/dev/null 2>&1; then
    echo "QSB reflection:"
    qsb -d "$shader" | sed -n '/Reflection info:/,/Shader 0:/p' | head -105
else
    echo "QSB binary created: $shader"
    echo "Qt's 'qsb' CLI not on PATH; reflection inspection skipped."
fi
