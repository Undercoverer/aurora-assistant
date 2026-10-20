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
  diagnostics.logContent = true; # Opt in to transcripts, replies and model text.
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
