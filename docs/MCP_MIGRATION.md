# D-Bus MCP migration: implementation status

MCP is the default controller transport for generic calls/properties, fixed
shortcuts and desktop adapter requests. The server derives wire types from live
introspection. The fixed desktop_query tool allows only Describe, Read and Prepare
on org.aurora.Desktop1; it cannot Apply or invoke arbitrary endpoints. Prepare
creates an expiring token but performs no desktop effect. Apply uses the same
strict call_method confirmation boundary as generic mutations. Adapter plans,
owner, token arguments and the shorter adapter expiry are bound to plan approval.
The pending PR still requires plan approval for all MCP actions. This is an interim
limitation, not the requested final device-assistant policy. Destructive-only approval
and spoken authorization remain a separate acceptance gate before merging the new
default. Model confidence must not override required approval.

Live discovery starts with current service names and follows relevant objects on
demand within request/round bounds; no startup crawl or persisted service inventory
is used in realtime mode. Discovery scope defaults to all running well-known services. Generic
prepare and server invocation introspect again, and server confirmation rechecks
owner/schema. Native utilities inside the desktop service remain implementation
details of that service. The overlay keeps its pinned D-Bus IPC contract.

`programs.aurora-assistant.execution.backend` defaults to `"mcp"` and
`settings.discoveryMode` to `"realtime"`. Explicit `"direct"`, `"startup"` and
`"periodic"` settings remain legacy rollback choices, never automatic fallbacks.
The server executable is a Nix store path; no runtime package installation occurs.
Non-Nix installations must install the locked `mcp` extra and configure an
absolute `execution.executable` path (or install aurora-mcdbus on PATH).

The controller approves the complete prepared list, then grants one-use consent
for each exact action. Each elicitation must match the active nonce, endpoint,
owner, signature, values and expiry. System-bus calls require a second explicit
prompt. Expiry is rechecked by the server before dispatch. Cancellation and
failure stop later actions without automatic retries or a direct fallback.
Existing desktop tokens are retained. Multi-action execution can partially succeed.

The optional offline recall worker and evaluation CLI are implemented separately
from execution. They retain lexical candidates and leave Kev routing unchanged.
Cross-encoder selection and selected-schema generation are not implemented;
accuracy, ambiguity and target-CPU measurements are prerequisites. See
[RECALL_EVALUATION.md](RECALL_EVALUATION.md).

Build and test evidence is recorded in [ACCEPTANCE.md](ACCEPTANCE.md). Automated
checks do not establish full desktop voice acceptance or model quality.

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

The MCP boundary emits mcp.call.duration and mcp.call.outcome with request
correlation and stable transport errors. Future selection and selected-schema
generation must emit select.score, select.margin, select.outcome,
qwen.args.duration and qwen.args.valid at their real component boundaries.
Those components do not exist yet; synthetic observations would falsely imply
migration coverage.
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

0. Instrumentation: run tests, inspect real correlated events, define baseline.
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
The earlier unpublished startup-only catalog work was not copied into this migration.

## Verification

From the repository root in the development environment:

```sh
PYTHONPATH=backend python -m unittest discover -s tests -p 'test_migration_telemetry.py'
PYTHONPATH=backend python -m unittest discover -s tests
```

Then exercise successful, refused, expired, partial-failure and cancelled turns on
a test desktop and inspect aurora-report. Existing snapshot retention is bounded;
use journal output for longer benchmark runs. Do not interpret missing future-stage
events as passing acceptance. Nix builds run in CI; live desktop checks remain required.

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
