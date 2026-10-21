# Acceptance evidence and remaining gates

## Automated evidence

PRs #1–#7 deliver telemetry, the strict server and installed stdio transport,
opt-in generic execution with exact consent correlation, Nix deployment checks,
bounded startup discovery, and optional offline recall/evaluation.

For PR #7 head `019b4cf9f18561114c20e3ecc0e6f57585d2a590`:

- [Nix deployment run](https://github.com/Undercoverer/aurora-assistant/actions/runs/39598354534)
  passed assistant, overlay, generated documentation, module evaluation and backend
  checks. The private-bus backend check ran 222 tests with no skips or failures.
- [MCP run](https://github.com/Undercoverer/aurora-assistant/actions/runs/39598354529)
  passed private-bus protocol/client tests and installed-package stdio checks.
- [Telemetry run](https://github.com/Undercoverer/aurora-assistant/actions/runs/39598354607)
  passed the focused instrumentation suite.

Python 3.11 remains the controller/runtime and protocol CI target. The Nix backend
check and standalone MCP package use locked nixpkgs' default Python (3.14 in this
revision). These checks establish package and isolated protocol behavior; they do
not establish model accuracy, hardware performance or a deployed NixOS session.

## Target-host acceptance

Use a test Plasma Wayland account and reversible settings. Record the exact flake
revision, NixOS/Plasma versions, CPU, RAM, audio devices, named model revisions and
configuration with each result. Keep the prior NixOS generation available.

1. Follow [QUICKSTART.md](QUICKSTART.md), verify model provisioning completes and
   collect `aurora-report --since '10 minutes ago'`. Check that all user services
   are running under the intended desktop user and the controller owns its socket.
2. After provisioning, disconnect external networking while retaining loopback.
   Verify wake detection, progressive transcription, final recognition, local
   reasoning and speech. Optional web search should remain disabled for this test.
3. Exercise a clarification and reply without another wake phrase. Confirm that
   escalation feedback appears during slow planning and response words track audio.
   Observe the overlay through processing, speech, result dwell and an induced
   recoverable error. Verify text remains readable and the pinned overlay D-Bus
   methods still work. Record actual wake-to-first-feedback timing separately from
   controller/agent duration metrics.
4. With the default MCP backend, request a harmless single action and a plan of
   two reversible actions. Inspect actual desktop state. Test ambiguous targets,
   human denial and approval expiry. A returned handler or success-shaped sentence
   alone does not prove an action happened.
5. Confirm `execution.backend = "mcp"` and `settings.discoveryMode = "realtime"`. Verify a
   discovered generic call and property change, inspect the exact pending plan,
   and confirm approval executes only those arguments. System-bus mutations need
   the second explicit prompt; use only a harmless test fixture. Do not test by
   changing host-critical system settings.
6. On a controlled fixture, restart the service or alter a property between prepare
   and approval, cancel during confirmation, and fail the second action. Confirm
   stale consent is rejected, later actions stop and partial effects are reported.
   Do not repeat a timed-out mutation until its actual effect has been inspected.
7. Set `execution.backend = "direct"` again and restart. Verify the same basic
   actions and voice flow work. MCP startup failure must remain visible and must
   not silently fall back to direct execution.
8. If evaluating retrieval, explicitly choose/provision a compatible named model,
   then follow [RECALL_EVALUATION.md](RECALL_EVALUATION.md) on the target CPU with
   representative labeled queries, ambiguities and unrelated requests. Compare
   lexical/hybrid recall and latency; keep retrieval disabled until acceptable.

Save observations, failures and reports for both backend configurations. No target
host is connected to development CI, so these checks remain outstanding.

## Implementation still gated

Cross-encoder selection, selected-schema argument generation and replacing Kev
require measured task accuracy, ambiguity behavior and target-CPU latency. The
current evaluator measures recall only; it cannot justify action selection on its
own. No replacement model or calibrated thresholds have been selected.

The default MCP path covers controller adapter requests, fixed shortcuts, generic
execution and discovery. Desktop service implementations still perform native
operations internally. Overlay IPC remains intact. Legacy direct transport is
retained only as an explicit rollback setting pending desktop acceptance.
Per-action tokens permit partial execution; no atomic plan transaction or rollback
is claimed. The strict mcdbus adaptation remains Aurora-maintained code.
