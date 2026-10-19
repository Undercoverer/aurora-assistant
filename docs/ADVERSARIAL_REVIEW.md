# Adversarial reliability review

Follow-up: [round two](ADVERSARIAL_REVIEW_ROUND2.md) adds lifecycle, review-policy, discovery, and approval-expiry fixes.

Review date: 2026-10-19. Scope: the Python controller, inference transport, D-Bus validation and scope, approval control, model manifests, speech output, and relevant Nix option descriptions. This is a source review with executable regression tests, not a penetration-test certification or proof that the complete desktop integration works.

## Findings and fixes

Severity describes the effect within the assistant's desktop account. None of these findings establishes a root privilege escalation.

| Finding | Impact and reproduction | Fix | Regression coverage |
|---|---|---|---|
| High: unbounded inference response retention | A malfunctioning local model server could return arbitrarily large JSON or audio. Normal HTTP read timeouts also permit a slow stream to continue indefinitely. | All inference requests use streamed response collection: 1 MiB for model/readiness responses and 40,000,000 bytes for speech. Each request has a total deadline (normally 90 seconds; Kev 15 seconds). Speech retries share a 120-second deadline. Responses exceeding the limit fail before JSON/audio decoding. | Oversized response; continuously dripping response; compressed response decoded exactly once. |
| High: PCM allocation before audio validation | A replacement TTS server could return excessive channels or duration; the entire PCM array was allocated before checking it. Non-finite samples could reach playback. | Inspect audio metadata first: 8–96 kHz, one or two channels, positive duration no longer than 120 seconds. Reject incomplete or non-finite decoded samples before opening playback. | Three-channel WAV rejected with the decoder patched to fail if called; floating-point WAV containing NaN rejected. |
| Medium: D-Bus namespace overmatch | Allowing `org.freedesktop.UPower` also allowed `org.freedesktop.UPowerEvil`. An empty prefix allowed everything except explicitly excluded services. Generic mutations still required approval, but discovery scope was broader than intended. | Entries match the exact namespace and dot-separated descendants. Empty entries match nothing. Nix descriptions explain this behavior. | Lookalike names rejected; exact and child names accepted; empty entries denied. |
| Medium: successful actions obscured by speech failure | Disconnecting the output device after execution made the controller report that the request could not be completed. Users could repeat an already completed action. | Keep the actual result on screen, append a speech-unavailable notice, and retain the action's success/failure state. Do not execute the action again. | Successful action followed by speech exception preserves its result and success state. |
| Medium: malformed model manifests accepted or poorly diagnosed | An empty file map passed the lightweight startup check. Relative traversal, absolute paths, and external symlinks could cause checks outside the selected generation. | Require an object containing a nonempty file map, valid SHA-256 strings, relative paths without traversal, and paths resolving within the generation. | Empty map, traversal, malformed digest, and external symlink rejected. Existing atomic provisioning/corruption tests still pass. |
| Medium: approval deadline excluded notification | A stalled overlay notification prevented the approval timeout from starting, leaving the turn stuck. | The deadline covers notification and the approval wait; timeout clears the pending request and cancels its future. | A notification that never returns expires with no approval. |
| Low: approval control robustness | An unhashable command produced an incidental exception; a detail object could override the generated ID; a symlinked control directory was followed and chmodded. | Validate command type; generate the ID after copying details; reject a symlinked control directory before chmod. | Malformed command, attempted ID override, and directory symlink tests. |
| Low: numeric coercion and malformed action names | Boolean byte-array values became 0/1, boolean doubles passed numeric verification, and nonstring names could raise unrelated type errors. | Reject booleans in byte arrays/doubles and require string action names. | Nested byte arrays, doubles, and five malformed name types. |
| Low: configuration errors reached runtime | Invalid ports were accepted until HTTP use; URL parsing silently removed some control characters; `silence_seconds = true` was accepted as one second. | Validate URL type, whitespace, credentials, literal loopback address, and port at load. Require a numeric nonboolean silence duration. | Invalid/out-of-range/zero ports, malformed IPv6, empty credentials, missing host, control characters, and boolean duration. |

## Compatibility notes

Existing default D-Bus scopes continue to work. Custom prefixes now have namespace semantics: `org.kde` or `org.kde.` matches `org.kde.KWin`, whereas `org.k` does not. An empty entry no longer means unrestricted discovery. Use explicit namespaces.

The speech limits permit normal assistant replies while bounding response retention and decoded PCM size. A replacement TTS server outside these limits must be configured to produce supported audio. Timed speech still falls back to ordinary OpenAI-compatible speech on HTTP 404/405.

The pinned overlay D-Bus contract is unchanged. All changes are in backend behavior, tests, and documentation.

## Verification

Run from the repository in its development environment:

```sh
python -m unittest discover -s tests
python scripts/test-package.py
python -m compileall -q backend
```

Observed result: **89 tests run, 87 passed, two live D-Bus tests skipped**. Seventeen new regression tests were added. Static overlay/package checks and Python compilation passed. Tests used Python 3.11 matching the project, with installed dependencies; no inference models were loaded.

A live session-bus run was attempted:

```sh
dbus-run-session -- python -m unittest discover -s tests
```

The environment rejected socket creation (`Operation not permitted`), so this did not validate live D-Bus behavior. Nix evaluation/build, KDE/Wayland, sound hardware, real model inference, and systemd activation were not verified here. In particular, this review does not establish that the previously reported torchaudio Nix build problem is resolved on the target host.

## Boundaries and follow-up validation

- Generic D-Bus introspection establishes signatures, not intent or safety. Generic writes/calls still require human approval even when Kev's reviewer says allow. Name filters are not a sandbox against an already compromised desktop account.
- Multi-action execution is sequential, not transactional. A later failure stops remaining actions; earlier changes remain applied. Existing tests cover stopping after failure and running microphone mute last.
- Desktop preparation tokens expire after 120 seconds. Review plus a long approval wait can exceed that lifetime; execution then fails closed. The user must issue a fresh request. No stale token is silently refreshed after approval.
- Speech models, native decoders, and inference services remain trusted local components. HTTP byte limits bound retained responses, not every transient allocation inside compression/native libraries. Process memory limits and native-library isolation would be separate hardening work.
- Startup model checks validate manifest structure and file presence. Full content hashing remains a provisioning check; the quick startup check does not detect every same-size corruption. The manifest itself is not a signed trust boundary against its owner.
- The search summarizer has no action tools and web results do not feed the system-action planner. This limits executable consequences of snippet instructions; it does not guarantee factual summaries or correct citations.
- Audio caption timing uses the device clock, but real-device underruns, unplug/replug, and alignment quality still require hardware testing. No word-perfect synchronization claim is made from mocked tests.

On a disposable KDE account, the remaining acceptance run should include service restart during approval, audio-device removal after a successful action, mixed-action partial failure, slow or unavailable Ollama/TTS, model provisioning failure, login/logout, and a Nix rebuild with the pinned lock file. Keep these distinct from the regression suite's verified results.
