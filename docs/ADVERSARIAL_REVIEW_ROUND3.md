# Iterative adversarial review: round three

Date: 2026-10-19. This review used successive inspect/fix/retest passes. The final focused pass found no additional reproducible failure in the cancellation, approval-race, and configuration-boundary cases tested below. This is a bounded stopping point, not a claim that all possible defects have been removed.

## Pass 1: speech and configuration faults

| Finding | Effect | Fix and evidence |
|---|---|---|
| Microphone failure during transcription could return incomplete text | The capture-error check happened before `recorder.text()`. A device failure during that call could abort recording yet return text to the controller as a command. | Check capture failure again after transcription and raise instead of returning text. A closed capture also returns no command. Two regression cases inject failure or closure during transcription. |
| TTS request cancellation could release the synthesis lock too early | The old cancellation handler awaited the worker task without shielding it. A further cancellation could cancel that task and exit the lock context while the native worker thread still ran. | An independent task owns and releases the lock. The HTTP request awaits it through a shield and may exit without releasing the worker's lock. Tests cancel the request, reject overlapping work, finish the worker, and accept the next request. Synthesis exceptions also release the lock. |
| Runtime JSON accepted invalid policy types and limits | Strings such as `"false"` are truthy; invalid wake thresholds and excessive planning limits bypassed the intended Nix option constraints in manually supplied JSON. Zero wake threshold activates even on zero-confidence scores. | Validate policy booleans, numeric bounds, result/round limits, discovery-prefix container types, and local search URLs at load. Match Nix bounds and reject a zero wake threshold in both paths. Boundary and malformed-value matrices exercise the checks. |

The worker lock fix protects against HTTP caller cancellation. It does not provide process isolation for a hung native inference library, and it does not guarantee graceful completion if the whole event loop or process is forcibly stopped.

## Pass 2: request handling and test-environment faults

- A slow speech request could keep the body-reading coroutine open indefinitely. Body collection now has a ten-second deadline and returns HTTP 408. The 8 KiB size limit is checked before appending each incoming chunk. The stalled-body and oversize tests run through the real FastAPI routes with an in-process ASGI transport.
- Whitespace-only speech requests are rejected with HTTP 400. A valid request before engine readiness returns HTTP 503. Tests verify both outcomes.
- Empty or non-finite synthesis output was converted to PCM before its quality was checked. Reject it before WAV encoding. Tests inject empty, NaN, and infinite arrays. A positive test synthesizes valid timed audio through a fake engine, decodes the returned WAV, and verifies chunk timing.
- The Nix backend check only installed `httpx` and `dbus-next`, although the earlier audio regression tests require NumPy and SoundFile. The expanded HTTP tests also require FastAPI. These dependencies are now included in that check.
- The configuration test initially depended on the working directory. It now resolves the repository fixture relative to its source, or uses `AURORA_TEST_CONFIG`. The Nix check sets that variable to the example configuration's store path.

The Nix check changes were inspected but could not be evaluated or built here. Their successful target-host execution remains an acceptance requirement.

## Pass 3: focused recheck

After the fixes, the complete suite ran **118 tests: 116 passed and two live D-Bus tests were skipped**. Thirteen new test methods were added in this round; the configuration matrix contains additional subcases. Static overlay/package checks and Python compilation passed.

The final focused run repeated synthesis cancellation, approval concurrency, and configuration-boundary suites five times from a different working directory: **35 test executions passed**. No new failure was observed in this pass. This finite run cannot exhaust thread schedules or establish correctness outside those cases.

```sh
python -m unittest discover -s tests
python scripts/test-package.py
python -m compileall -q backend
```

Tests used Python 3.11. FastAPI was installed in the local test environment for the new HTTP checks; no project dependency or lock-file update was needed because FastAPI is already a declared voice dependency. The speech engine was replaced with a test double. No real model inference or sound playback was performed.

## Configuration and deployment changes

- `wakeThreshold` must now be at least `0.01`; configurations using zero must change.
- Manually supplied JSON must use actual booleans and numeric values within the documented Nix limits. Strings such as `"false"` or `"5"` are not accepted as boolean or numeric substitutes.
- The pinned overlay D-Bus interface is unchanged.

## Remaining acceptance work

Nix evaluation/build, the torchaudio build on the target host, actual KDE/Wayland behavior, live D-Bus calls, real microphone disconnects, native-library shutdown hangs, real synthesis/alignment, and systemd login/logout behavior remain unverified here. The two D-Bus tests require socket creation, which this environment does not permit. Multi-action execution remains sequential and cannot roll back earlier effects if a later step fails. See [round one](ADVERSARIAL_REVIEW.md) and [round two](ADVERSARIAL_REVIEW_ROUND2.md) for the other tested boundaries and limitations.
