# Runtime troubleshooting

## Update an existing installation

Remove an old explicit `kev.model = "qwen3:0.6b"` override. The correct default is
`hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M`; it runs through llama.cpp's System One endpoint,
not Ollama chat completions. Planner configuration now uses `planner.model`; remove old `ollama.*` options
as described in [the migration guide](LLAMA_CPP.md).

Assuming the flake input is named `aurora` and the NixOS host is `framework`:

```sh
cd /etc/nixos
nix flake update aurora
sudo nixos-rebuild switch --flake .#framework
systemctl status aurora-models.service
```

Wait for successful model provisioning, then run from the configured Plasma user:

```sh
systemctl --user restart aurora-inference.service aurora-tts.service aurora-desktop.service aurora-controller.service
aurora-assistant --check-audio
```

The audio check loads packaged PortAudio and libsndfile without opening the mic.
SoundDevice is patched to use the absolute Nix store library path, avoiding its
runtime search via external compiler/linker tools. The wrapper retains native
library paths too. The flake has an empty-environment audio import check; build
and runtime validation on the actual NixOS machine are still necessary.

## All user services are inactive; control socket is missing

A completed `aurora-models.service` only means the model files were provisioned.
It does not prove that the graphical-session target or controller is running.
`aurora-control` needs the controller's private socket; it cannot query capabilities
while that controller is stopped. Installed unit files are not evidence of active
services. A rebuild can also leave new graphical-session dependencies needing an
explicit start in an already running login session.

From the configured Plasma user's terminal, without sudo:

```sh
systemctl --user daemon-reload
systemctl --user restart aurora-assistant.target
systemctl --user status aurora-assistant.target aurora-inference.service aurora-controller.service --no-pager
```

Allow the inference workers to load. The default startup deadline is 180 seconds.
If the target is skipped, inspect `ConditionResult` and confirm the current user
matches `programs.aurora-assistant.user`. If services stop or fail, export a report:

```sh
aurora-report --since '10 minutes ago' --clipboard
```

Once the controller runs, `aurora-control capabilities` can connect. Its catalog
starts empty and is populated by successful D-Bus discovery requests; an empty
catalog is different from a missing control socket. Reports now include both
Aurora and graphical-session targets, model-provisioner status, stop/start times,
exit type, condition results and the units named in manager journal messages.

## One unified diagnostic report

Reproduce the problem, then copy this report directly to the Wayland clipboard:

```sh
aurora-report --since '30 minutes ago' --clipboard
```

Or save it / use wl-copy explicitly:

```sh
aurora-report --since '30 minutes ago' > aurora-report.txt
aurora-report --since '30 minutes ago' | wl-copy
```

The report contains package revision, actual user-unit executable/config paths,
restart counts and status, plus a merged UTC journal timeline from controller,
the shared inference router and its workers, TTS, desktop adapter, overlay,
PipeWire/WirePlumber, model provisioner and managed search services. It is scoped to the current boot. Missing
permission to read system journals is reported; it does not silently claim the
report is complete. It does not dump environment variables or record audio.
Review it before sharing because upstream service messages can contain personal
data. Text mode/manual runs write structured events to their terminal; those
messages are not automatically in the service journal.

## Configuration for debugging and responsiveness

All these options belong in the host's NixOS module, including when that module is
imported through flake-parts/import-tree:

```nix
programs.aurora-assistant = {
  kev = {
    model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
    timeoutSeconds = 10;
    threshold = 0.95;
  };
  safety.backend = "kev";
  diagnostics.logContent = true; # Opt in to transcripts, replies, model text and exception messages.
  presentation = {
    resultSeconds = 6;
    errorSeconds = 10;
    agentTimeoutSeconds = 60;
  };
  conversation = {
    followUpSeconds = 12;
    maxFollowUps = 2;
  };
};
```

Rebuild after changing options. Set `diagnostics.logContent = false` after debugging
if you do not want future conversation text stored in the local journal. Turning
it off does not erase old entries. Timing events remain available without content.
Each turn has an ID; phases include recognition, Kev, planning, D-Bus reads/calls,
review, TTS synthesis/alignment and playback. Exceptions report their type and code
location without indiscriminately logging exception payloads.

The overlay remains active during work, then holds results/errors for the configured
duration. The request deadline covers planning, discovery, review and approval;
raising it also increases how long a slow request may wait. Speech has its own
bounded deadline. A timeout after an action may mean a partial change: inspect the
actual setting before repeating a request. The log distinguishes phases but cannot
prove that a remote service rolled back an interrupted operation.

A clarification question opens a short listening window without another wake word.
If that window expires, use the wake word again. Muting the microphone prevents
voice follow-ups until it is unmuted through desktop controls.

## Dependencies and latency

Native libraries, Qt components, CLI utilities and inference service dependencies
come from nixpkgs. Kev uses `pkgs.llama-cpp` when its version is at least 0.7.0.
The currently pinned older nixpkgs needs a pinned 0.7.0 compatibility derivation
built with nixpkgs tools/libraries; older servers lack the required endpoint.
`inferencePackage` permits an explicit compatible package override. Python retains the
existing uv2nix lock because the speech packages require a coordinated version set.
No dependency or model is installed ad hoc during normal voice operation.

CPU Kev, Whisper, Supertonic and Qwen can contend for compute and memory. No
one-second latency guarantee has been verified. Check phase durations before
changing model sizes. TTS alignment adds work; `wordSync = false` disables word
alignment when troubleshooting synthesis latency. The small common-command route
avoids the larger planner, while unfamiliar commands may still need multiple rounds.

## Overlay errors with no corresponding journal events

The overlay includes the exception type and request ID when a request fails.
`aurora-report` also queries the running controller directly for its most recent
128 metadata events. This buffer works independently of Python logging and
journal capture, excludes transcript/reply text, and disappears when the
controller exits. Collect the report after reproducing the problem, before
restarting the service:

```sh
aurora-report --since '10 minutes ago' --clipboard
# Inspect only the live controller's metadata:
aurora-control diagnostics
```

The report includes the controller PID and the service's MainPID. A mismatch
means the socket belongs to a different process, such as a manually launched
controller. An empty capability catalog means no interfaces have been recorded;
it does not establish that the desktop has no D-Bus capabilities. HTTP failures
include a status code and code locations, without copying model response bodies.
An older controller may return `Invalid approval command` for the new diagnostic
query; update the flake input, rebuild, and restart `aurora-assistant.target`.

## Wake word produces no response

The default built-in wake phrase is **Hey Jarvis** (`models.wakeWord =
"hey_jarvis"`). The assistant's product name does not change the phrase learned
by the wake model. A custom phrase requires a trained model.

Capture diagnostics appear automatically in the terminal, journal, and
`aurora-control diagnostics`. No audio or spoken words are stored by these
checks. After startup, speak the configured phrase and collect a report without
restarting. Look for:

- `capture.opening` then `capture.opened`: the selected audio device opened.
- `capture.first_audio`: at least one audio block arrived.
- `capture.prepare.done` then `wake.armed`: the wake detector is listening.
- `capture.health`: every five seconds while audio arrives, reports block and
  overflow counts, peak RMS level, peak wake score, threshold, and gate state.
- `capture.failed`: an exception interrupted audio capture or wake detection.

A zero RMS value means the received samples were silent during that interval.
A nonzero RMS value with a low wake score means audio arrived but did not meet
the model threshold. An opened stream with no first-audio event means the first
read has not completed. These distinctions must be checked before changing
thresholds or selecting another microphone. Overflow counts indicate lost
older samples; the returned block is still processed.


## ValueError review (2026-10-20)

The original user-reported ValueError has not been attributed without its trace.
A source review against the pinned llama.cpp v0.7.0 found these concrete issues:

* Completion JSON envelopes were indexed before validation. Invalid outer JSON,
  an empty choices list or a missing message could bypass the bounded plan-repair
  path. They now become a static `PlanValidationError` before any action executes.
* Kev responses must now contain exactly the requested question IDs. Broken
  envelopes fail at the inference boundary rather than later dictionary access.
* Desktop exceptions were wrapped for D-Bus without logging their original stack.
  `desktop.service.failed` now records it before wrapping. Static plan-validation
  reasons are included by default. Arbitrary exception messages remain opt-in with
  `diagnostics.logContent`, and are excluded from the recent-event socket buffer.
* Context capacity and logical batch capacity are separate in the pinned server.
  Its decision output positions must fit within one logical batch; the default
  batch size is 2048. The managed Kev preset now sets `batch-size` equal to its
  context size. Physical microbatch size is unchanged. This addresses a catalog
  size failure path, not a confirmed cause of the earlier ValueError.

The reviewed source is [server-context.cpp at v0.7.0](https://github.com/ggml-org/llama.cpp/blob/v0.7.0/tools/server/server-context.cpp),
particularly `can_split()` and the decision output batch-size guard. External
servers need equivalent configuration. This does not assert that non-causal
replacement models can split their prompts in the same way as Kev.

The [upstream decision API documentation](https://huggingface.co/blog/ggml-org/decision-models-in-llamacpp)
confirms the `choice`/`probabilities` and `noul` response shapes. Aurora thresholds
use the selected option probability, not the separate `confidence` field. A 0.95
threshold is a policy default, not a calibrated accuracy guarantee. Published
millisecond timings use an NVIDIA RTX PRO 6000 and do not establish CPU latency.
Nested decisions add work; caching alone does not prove a speedup.

Regression tests use mocked inference and desktop effects. The original runtime
cause, real model semantics, actual cache reuse, host performance, and NixOS build
remain unverified. No new recording or cloud service is required by these fixes.
