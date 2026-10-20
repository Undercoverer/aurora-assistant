# D-Bus MCP migration: implementation status

Stage 0 draft, based on ea8536460f28da7accb82a6bf4298b86a2d17105.
No execution backend, routing policy, dependency or Nix option changes here.
Tests are authored but have not run: the editing session has no execution environment.
This stage is not accepted until the test suite and representative journal capture pass.

## Measurement boundaries

Existing phase events and kev.selection / kev.escalate remain unchanged.
New events use the existing structured journal and diagnostic snapshot.

| Event | Fields | Meaning |
| --- | --- | --- |
| turn.end_to_end_ms | value, unit=ms, completion, boundary=controller_lifecycle | Starts after the controller acquires its visual lock and receives final transcription; ends after its handler returns or raises. Includes approval wait, speech, error/result dwell and overlay cleanup. Excludes audio capture, STT and lock wait. |
| turn.processing_ms | value, unit=ms, completion, boundary=agent_run | Existing SettingsAgent.run duration, including discovery, model calls, approval and action execution. Excludes final spoken response and result dwell. Absent in the legacy non-agent path. |
| apply.failure.reason | reason, completed_actions | policy, not_approved, expired, or execution_error at known execution boundaries. not_approved includes denial and approval timeout because the existing approval API returns only a boolean. |

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
- mcdbus's published documentation has an allow-with-warning confirmation fallback.
  Stage 1 must require MCDBUS_REQUIRE_ELICITATION=1, then inspect the pinned source
  and test timeout, disconnect, unsupported elicitation, malformed response and
  explicit denial. MCDBUS_NOTIFY_CONFIRM=1 alone is not a fail-closed guarantee.
  Documentation: https://pypi.org/project/mcdbus/ (release 2026.3.6.3).
  The source link redirected to an inaccessible host during this review; exact
  tool schemas and exception behavior remain unverified.
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
