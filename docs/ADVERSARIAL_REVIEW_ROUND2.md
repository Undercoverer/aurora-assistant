# Adversarial review: round two

Date: 2026-10-19. This review follows [round one](ADVERSARIAL_REVIEW.md). It focuses on shutdown, configuration-dependent policy, incomplete discovery, and approval lifetime. Tests inject failures and concurrent events without requiring KDE or model downloads.

## Findings and fixes

| Finding | Reproduction and effect | Fix | Regression tests |
|---|---|---|---|
| High: review skipped when discovery was disabled | Starting with JSON `settings.enable = false` selected the legacy executor path. A configured D-Bus alias could execute without the review and approval used by the settings agent. The Nix-generated configuration enabled settings, so this affected alternative JSON configurations. | The executable always constructs the review agent and starts approval control. Disabling settings now limits the available action schema; it does not select an unreviewed execution path. Explicit `safety.enable = false` remains a separate user policy choice. Configured aliases still require approval. | Disabled discovery retains the review agent; disabled discovery rejects theme actions before preparation. |
| Medium: cleanup failure skipped remaining resources | A failed overlay reset during shutdown prevented approval and HTTP cleanup. Startup failures before the old `try/finally` could leave acquired resources open. | Register each resource with `AsyncExitStack` as it is acquired. A cleanup exception does not prevent the other registered callbacks from running. | Failed connect, failed readiness, failed reset, normal text-mode exit, and cancellation while the capture thread waits. The last case verifies that voice closure releases the test capture thread and other resources close. |
| Medium: approval request state could be replaced | Approval dispatch clears `pending` before the request coroutine returns. If notification was still waiting, another request could replace `self.future`; the first request could then wait on or cancel the wrong future. | Track an active request until its coroutine exits, including notification and result delivery. Reject a second request during that interval. | Approve while notification is blocked, attempt a second request, release notification, and verify the original result survives. Cancellation releases the slot for a new request. |
| Medium: approval connections could remain open or stall | Cancellation while reading occurred before the old writer cleanup block. A client that did not consume a response could stall `drain()` without a deadline. | Use outer cleanup for the whole connection. Bound reading and response writing to five seconds and close waiting to one second. | Cancel during read and verify closure; block response draining and verify timeout and closure. These use fake streams because live sockets are unavailable here. |
| Medium: partial media discovery could choose the wrong player | One unreadable player was silently omitted. The remaining player could appear uniquely eligible. Lists were also truncated at 32, and sequential service waits could accumulate for minutes. | Reject incomplete discovery, invalid required player properties, and more than 32 players. Give the complete discovery operation a ten-second deadline. No player is automatically selected from partial results. | A readable player followed by an unreadable player; 33 players; discovery that never returns. |
| Medium: approval window exceeded desktop plan validity | Desktop tokens expire after 120 seconds, but review and the subsequent 120-second approval wait could exceed that lifetime. A user could approve an already expired plan. | Return the token's monotonic expiry with preparation data. Limit approval to the earliest expiry minus a two-second transport margin. Check expiry after review and again after approval, before starting execution. | Expired review does not request approval; approval timeout fits remaining validity; expiry after approval prevents execution. |

## Behavior changes

- JSON configurations with settings discovery disabled still use review and local approval control. They now need the desktop adapter for the supported desktop actions, as the normal Nix service group already provides.
- Update the controller and desktop adapter together. The adapter's `Prepare` JSON response now includes `expires_at`; the pinned overlay D-Bus methods and signatures are unchanged. An older adapter without this field cannot prepare an executable plan for the updated controller.
- An unresponsive media player now prevents automatic player selection. This trades availability for avoiding an action on the wrong player. Discovery reports the failure so the planner can clarify or stop.
- Slow review can leave less than 120 seconds for approval. Expired plans are rejected; the controller does not silently create a fresh plan under an old approval.

## Verification

Sixteen new regression tests were added. The complete suite ran **105 tests: 103 passed and two live D-Bus tests were skipped**. Static overlay/package checks and Python compilation passed.

```sh
python -m unittest discover -s tests
python scripts/test-package.py
python -m compileall -q backend
```

The tests ran with Python 3.11 and the project's installed dependencies. No real speech model, sound device, KDE session, or systemd service was used. Live D-Bus tests remain blocked by the environment's socket restriction. Nix evaluation/build remains unverified. Round one's passing checks do not establish a successful target-host torchaudio build.

## Remaining limits

- Sequential actions are not a transaction. A token can expire while an earlier action is running; the adapter rejects the expired action, but earlier effects remain. The new checks prevent starting an already expired batch, not every later expiry.
- Cleanup callbacks still depend on native libraries returning. The tests cover Python exceptions and cancellation; they do not establish that a hung native recorder can always stop within the systemd stop timeout.
- These fixes do not make an LLM reviewer a security boundary. Generic calls and writes retain human approval. The adapter runs with the desktop account's permissions.
- Media properties can change after discovery. Owner binding, toggle-state checks, and readback remain in place, but there is no cross-service transaction.
