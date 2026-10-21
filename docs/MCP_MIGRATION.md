# D-Bus MCP migration: implementation status

Stages 0 and the strict-server prerequisite are merged. The Nix server package
and its installed stdio transport passed CI in PR #3. Aurora keeps the direct
backend by default. The experimental client migrates generic dbus_call/dbus_set
execution and introspection; desktop adapters, fixed shortcuts and overlay IPC
still use their existing paths.

Enable with `programs.aurora-assistant.execution.backend = "mcp";`. Revert to
`"direct"` and restart the controller to roll back. The server executable is a
Nix store path; no runtime package installation occurs. Non-Nix installations
must install the locked `mcp` extra and configure an absolute
`execution.executable` path.

The controller approves the complete prepared list, then grants one-use consent
for each exact action. Each elicitation must match the active nonce, endpoint,
owner, signature, values and expiry. System-bus calls require a second explicit
prompt. Expiry is rechecked by the server before dispatch. Cancellation and
failure stop later actions without automatic retries or a direct fallback.
Existing desktop tokens are retained. Multi-action execution can partially succeed.

Local client validation: backend suite 208 tests, three private-bus skips;
MCP protocol/process suite 28 tests, four private-bus skips. The private-bus client
integration runs in CI. These counts describe this change before CI acceptance,
not KDE hardware validation. Target CPU benchmarks, semantic recall/reranking,
and full desktop voice acceptance remain outstanding.

## Measurement boundaries

Existing phase events and kev.selection / kev.escalate remain unchanged.
New events use the existing structured journal and diagnostic snapshot.

| Event | Fields | Meaning |
| --- | --- | --- |
| turn.end_to_end_ms | value, unit=ms, completion, boundary=controller_lifecycle | Starts after the controller acquires its visual lock and receives final transcription; ends after its handler returns or raises. Includes approval wait, speech, error/result dwell and overlay cleanup. Excludes audio capture, STT and lock wait. |
| turn.processing_ms | value, unit=ms, completion, boundary=agent_run | Existing SettingsAgent.run duration, including discovery, model calls, approval and action execution. Excludes final spoken response and result dwell. Absent in the legacy non-agent path. |
| apply.failure.reason | reason, completed_actions | policy, not_approved, expired, cancelled, or execution_error at known execution boundaries. not_approved includes denial and approval timeout because the existing approval API returns only a boolean. |

Timing completion=returned describes control flow, not successful execution:
the controller handles some errors internally. completion=raised includes cancellation.
Use request.failed and execution events alongside timings.
completed_actions counts successful returned calls; a failed call may already have
changed state. Plans are not atomic transactions. Exceptions are never classified
as owner mismatch by matching their message text.

Future stages must emit mcp.call.duration (milliseconds), mcp.call.outcome,
select.score, select.margin, select.outcome, qwen.args.duration (milliseconds),
and qwen.args.valid at real component boundaries. These components do not exist
yet; synthetic production observations would falsely imply migration coverage.
Owner mismatch and MCP-specific errors require typed transport failures in Stage 1.
No sub-500ms latency or reranker calibration claim is established.

## Corrections to the proposed guide

- The existing agent prepares a list of individual action tokens and obtains one
  approval over that list. Preserve expiry and ownership guarantees; do not describe
  this as an atomic plan token or rollback transaction.
- The audited upstream mcdbus release does not enforce strict elicitation.
  Environment flags cannot repair that contract. Aurora's strict entry point
  denies unsupported, malformed, timed-out or declined confirmation. See
  MCDBUS_SOURCE_AUDIT.md for the inspected source and exact differences.
- Bind approval to exact bus, unique owner, object path, interface, member, typed
  arguments and token. A well-known-name owner check before invocation still has
  a race. Verify the server can execute against the approved unique owner; otherwise
  patch the server before migrating mutations.
- Do not auto-accept arbitrary elicitation based only on an approved plan token.
  Correlate the active call and exact arguments; unknown or mismatched prompts deny.
  Automatic reuse of plan consent does not constitute independent human review.
- Parse complete D-Bus types from each XML arg. Signature string indexing fails
  for arrays, dictionaries, structs and variants. Introspection alone does not
  reveal safe numeric ranges, units or whether a method mutates state.
- A Kev decision forward pass is not a generative text decode. Compare measured
  task accuracy and CPU latency before replacing it. Async risk auditing cannot
  prevent an action that has already executed; deterministic policy must remain.
- llama.cpp --jinja concerns chat templates. Structured output requires the
  server's supported response schema/grammar API and independent validation.
- Keep lexical recall. Treat reranker floors and margins as evaluation parameters,
  not calibrated probabilities. Evaluate ambiguous and no-match queries too.
- Aurora's overlay uses D-Bus IPC as well. Preserve that public contract; removing
  direct desktop action invocation does not mean removing overlay communication.

## Separate changes and acceptance gates

0. Instrumentation (this draft): run tests, inspect real correlated events, define baseline.
1. MCP execution: pinned packaged server, exact discovered tools/list contract,
   typed conversion tests, correlated elicitation, owner binding, partial failure
   reporting; disabled by default with tested rollback.
2. Discovery: startup scan and comparison, bounded service/object/time budgets,
   introspection-derived records; retain old discovery behind rollback.
3. Recall/rerank: offline provisioned models, lexical merge, bounded promotion,
   measured recall/accuracy and CPU p95 versus the existing route.
4. Argument generation: selected schema only, validated async completion and
   immediate feedback. Existing async planning should be reused where possible.
5. Freshness: add targeted invalidation only if startup comparison and pre-apply
   checks prove insufficient. Keep this small and independently removable.

Each stage gets its own PR and rollback checks. Do not remove the working backend
before the replacement passes acceptance. Prefer nixpkgs dependencies; pin and
package missing dependencies in Nix, without runtime uvx/pip or model downloads.
The earlier startup-only catalog simplification is not included in this PR.

## Verification

From the repository root in the development environment:

```sh
PYTHONPATH=backend python -m unittest discover -s tests -p 'test_migration_telemetry.py'
PYTHONPATH=backend python -m unittest discover -s tests
```

Then exercise successful, refused, expired, partial-failure and cancelled turns on
a test desktop and inspect aurora-report. Existing snapshot retention is bounded;
use journal output for longer benchmark runs. Do not interpret missing future-stage
events as passing acceptance. Nix evaluation and live desktop checks remain required.

## Follow-up review

Cancellation during an action now emits reason=cancelled and propagates the
cancellation. The in-flight action may have changed state; later actions do not run.
Ten focused tests cover duration, correlation, policy block, refusal, expiry,
partial failure, cancellation and private exception text.

The migration-telemetry workflow runs the focused suite on Python 3.11 without
installing application dependencies or models. Actions are pinned to commit IDs
and the job has read-only repository access. This is a focused instrumentation
check, not full-suite, Nix, MCP or desktop acceptance. Check the workflow result
for the exact PR head; adding a workflow does not establish that it passed.

## Source inspection follow-up

The pinned wheel source is now available. See [MCDBUS_SOURCE_AUDIT.md](MCDBUS_SOURCE_AUDIT.md) for verified contract mismatches and the separate strict-server prerequisite. The baseline suite now passes locally (197 tests, three live-bus tests skipped); the initial execution-environment limitation above is historical. No completed execution migration is claimed.
