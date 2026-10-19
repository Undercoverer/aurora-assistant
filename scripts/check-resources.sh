#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
binary="${1:-./build/aurora-voice-overlay}"
if [[ ! -x "$binary" ]]; then
  echo "Executable not found: $binary" >&2
  exit 1
fi
expected="$(sha256sum qml/Overlay.qml | awk '{print $1}')"
output="$($binary --check-resources 2>&1)"
printf '%s\n' "$output"
actual="$(printf '%s\n' "$output" | sed -n 's/^QML_SHA256= *//p' | tr -d '"')"
if [[ "$expected" != "$actual" ]]; then
  echo "MISMATCH: source QML=$expected compiled QML=$actual" >&2
  exit 2
fi
echo "PASS: embedded QML bytes exactly match qml/Overlay.qml"
