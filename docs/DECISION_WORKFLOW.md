# Decision workflow: Kev, Qwen, and desktop tools

## What the upstream designs mean for Aurora

[TypeSafe's System One documentation](https://docs.typesafe.ai/concepts/system-one)
describes typed decisions over supplied state, with probabilities rather than
generated text. Confidence is not a guarantee of correctness.
[llama.cpp's decision-model guide](https://huggingface.co/blog/ggml-org/decision-models-in-llamacpp)
provides native Kev through `/v1/systemone`, with `choice`, `noul`, and `score`.
Aurora already uses that endpoint and the actual Kev-4B GGUF.

The [Jev Ultrafast reference implementation](https://github.com/browser-use/jev-ultrafast)
builds choices from observed controls, checks the selected target, and uses a
text model only when text generation is necessary. Aurora applies this idea to
typed desktop actions and observed D-Bus interfaces. It does not use the hosted
Jev service, browser automation, or that project's cloud text provider.

## Request flow

1. STT finalizes the request. Kev receives the request and concrete choices.
2. Exact supported clauses can produce a complete multi-action candidate. Kev
   checks that candidate against the entire request.
3. Other requests get a bounded menu of supported operations plus recently
   observed capabilities. Available choices include speaker/microphone mute,
   playback, local clock, audio state, YouTube, and absolute volume values found
   as integer digits in the request. Observed application IDs, themes, colors,
   readable properties, boolean property values, and zero-argument methods can
   also become choices.
4. Low confidence, missing arguments, and unsupported multi-action combinations
   go to Qwen. Qwen can request discovery, synthesize typed arguments, or ask a
   clarification. It cannot supply shell code.
5. The controller validates the complete plan. Invalid JSON or invalid action
   fields get one correction attempt, within the existing round/time limits.
   Nothing from an invalid plan executes. A second invalid plan produces an
   explicit failure, and the report includes the static validation reason.
6. The desktop service checks live targets and prepares the operations. Policy
   and, when needed, model review determine whether approval is required.
7. Execution uses the prepared targets and existing readback checks. Replies
   about completed changes come from executor results, not a generated claim.

Kev does not invent new arguments, retrieve the current time from its weights,
or know every D-Bus interface without discovery. Candidate retrieval is lexical;
Kev performs semantic selection on the shortlist. The catalog is session-local,
bounded, and expires after five minutes. It is not a complete index of Plasma.

## Examples and approval behavior

| Request | Tool path | Approval behavior |
| --- | --- | --- |
| What time is it? | `desktop_read clock`, through `org.aurora.Desktop1.Read` | Read only; returns the current local clock response directly |
| Mute the computer | `mute true`, prepared by the desktop adapter | Exact routine request uses local policy |
| Set volume to 12 | `volume 12` | Exact routine request uses local policy |
| Open YouTube | `open_url https://www.youtube.com/`, desktop portal | Exact routine request uses local policy |
| Mute the microphone and pause playback | Complete two-action candidate | Exact routine policy; microphone mute executes last |
| Make the speakers 12 percent loud | Kev selects a supplied absolute-volume candidate, or Qwen handles uncertainty | Model review if it is not an exact parsed routine request |
| Use Breeze Dark | Discover installed theme/color IDs, then select an actual ID | Model review; no invented theme identifier |
| Change an unfamiliar D-Bus property | Inspect, prepare a typed change, review | Local approval remains required |

The clock response comes from `datetime.now().astimezone()` in the desktop
service. The controller reads it over D-Bus. It uses the host's configured time
zone and does not claim to check internet time accuracy.

Routine policy applies only if every prepared action exactly matches the
complete recognized user request, all actions belong to the supported routine
set, and no adapter requires approval. It does not approve generic D-Bus calls,
unknown settings, or partially understood requests. Model confidence cannot
override those rules. A local approval request is not root privilege escalation.

Controller-to-desktop communication uses D-Bus. Media and URL opening use native
MPRIS/portal calls. Some adapter implementations still use fixed `wpctl` or KDE
commands internally; this release does not claim every operation is a native
KDE D-Bus method. There is no unrestricted shell tool.

## Configuration and troubleshooting

```nix
programs.aurora-assistant = {
  enable = true;
  user = "foxkj";
  models.wakeWord = "alexa"; # Built-in trained phrase; unrelated to Kev.
  kev.model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
  kev.threshold = 0.95;
  safety.backend = "kev";
  planner.model = "hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M";
};
```

After one failed request, collect diagnostics before restarting:

```sh
aurora-report --since '10 minutes ago' --clipboard
aurora-control capabilities
```

`kev.route` and `kev.capability` show whether a candidate was accepted.
`kev.route_failed` includes failure locations and HTTP status where available.
`review.local` shows routine policy; `review.result` shows the resulting decision.
`plan.invalid` gives a static validation reason without storing the request.
A specific earlier ValueError cannot be attributed from the exception name
alone; its event and stack location are needed. These changes improve recovery
and diagnosis, but do not prove the cause of an earlier uncollected failure.

## Validation limits

Offline tests cover clock transport, semantic choice mapping, exact routine
policy, approval preservation, plan correction, bounds, and catalog entries.
They mock inference and desktop effects. They do not establish live model
accuracy, latency on a particular CPU, or successful operation on every Plasma
version. NixOS and live desktop validation remain target-host checks.
