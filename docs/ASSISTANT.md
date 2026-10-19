> This is the original integration-build design record. Current model provisioning and settings control are documented in [SETUP.md](SETUP.md).

# Aurora local assistant: integration build 0.1

This extends the supplied Palette Studio overlay with a Python voice backend,
validated desktop actions, a local Supertonic API, and a NixOS module at
`programs.aurora-assistant`. The existing C++, QML, shaders, palettes, and D-Bus
methods are unchanged.

This is an integration build, not a hardware-validated release. CPU execution
on x86_64 Linux is the initial package target. Read the verification limits at
the end before enabling it as an always-running service.

## Data path

1. One SoundDevice capture stream reads 16 kHz mono PCM from the configured input.
2. While idle, only openWakeWord receives live samples. Its ONNX wake model,
   embedding model, and mel model are supplied as explicit local paths.
3. Detection opens the audio gate to RealtimeSTT. RealtimeSTT uses Silero ONNX
   with end-of-speech detection and faster-whisper for provisional and final text.
4. Every provisional hypothesis **replaces** the overlay message. It is not
   appended, because the recognizer can revise earlier words. Latest-value slots
   bound callback traffic and drive the overlay at up to 30 updates per second.
5. Configured silence ends speech. Only the authoritative final text enters the
   LLM. Eight seconds without speech cancels activation; a 45-second turn cap
   discards an overlong utterance. These bounds are configurable in JSON. A timed-out
   turn recreates the STT recorder to remove any cancelled audio still queued
   internally; this adds model initialization latency after a timeout.
6. Qwen3 in Ollama returns a JSON-schema-constrained plan. The Python validator
   checks the entire plan before executing any of it. Unsupported fields,
   types, actions, and values fail closed. Maximum: four actions per turn.
7. The executor uses fixed argument vectors, never a shell. Allowed operations:
   absolute volume 0–100%, mute/unmute, five media operations, configured
   application aliases resolved to desktop entry filenames, and explicitly
   registered D-Bus calls. See [CONFIGURATION.md](CONFIGURATION.md).
8. Action responses come from execution results. A failed step stops later
   steps and preserves the report of earlier completed steps. This is not a
   rollback transaction. For a question with no actions, the model supplies text.
9. Supertonic returns WAV audio through `/v1/audio/speech`. Playback sample
   energy drives SetLevel. This is a block-level envelope, not phoneme lip sync.
10. Capture continues draining the microphone, but its samples are discarded
    during inference and playback. Wake/STT input resumes after playback and the
    completion display. Barge-in and acoustic echo cancellation are not implemented.

Modules are in `backend/aurora_assistant/`. `voice.py` owns audio; `inference.py`
owns local HTTP clients; `actions.py` owns validation and system execution;
`controller.py` owns turn states; `overlay.py` is the pinned-contract client.
`tts_server.py` owns the separate TTS service. Speech modules and inference are
lazy-loaded, so basic controller tests do not require model files.

## NixOS configuration

Add this source tree as a flake input and import its module. For example, after
putting the extracted directory at `/etc/nixos/aurora`:

```nix
# In the host flake inputs:
aurora.url = "path:/etc/nixos/aurora";

# In the host's nixosSystem modules list:
inputs.aurora.nixosModules.default

# In a NixOS configuration module:
programs.aurora-assistant = {
  enable = true;
  user = "alice"; # Replace with the desktop account.
  modelDirectory = "/var/lib/aurora-models";
  silenceSeconds = 0.7;
  wakeThreshold = 0.5;
  voice = "F1";
  ollama.model = "qwen3:4b";
  applications = {
    files = "org.kde.dolphin.desktop";
    browser = "firefox.desktop";
  };
};
```

The mapped applications must already be installed. The selected user must be
able to read modelDirectory and access the session's PipeWire audio devices.
Use Plasma's Wayland session. The module does not change the system's display
manager, audio stack, or user accounts.

`aurora-assistant.target` starts with `graphical-session.target`. It starts the
controller, overlay, and Supertonic user services. The overlay uses systemd
`Type=dbus` with its existing bus name. Ollama runs as the NixOS system service;
no user unit attempts to order itself against a system-manager unit. The
controller polls local API readiness and checks the configured model exists
before opening the microphone. Units restart on failure, and stop with the
graphical session. Restarted overlays can reclaim their name without rebuilding
a cached D-Bus proxy. HTTP service failures are reported on the overlay.

```sh
nix flake check
nix build .#assistant .#default
sudo nixos-rebuild switch --flake /etc/nixos
systemctl --user start aurora-assistant.target
systemctl --user status aurora-controller aurora-tts aurora-voice-overlay
journalctl --user -u aurora-controller -u aurora-tts -b
```

To stop listening and close the microphone:

```sh
systemctl --user stop aurora-assistant.target
```

To use the overlay editor, stop the target first, then `nix run . -- --editor`.
The editor and the service cannot own the same bus name simultaneously.

## Provision models before normal offline use

No runtime service intentionally downloads models. Provision these files during
an explicit online setup step, or copy them from another machine:

```text
/var/lib/aurora-models/
  whisper/                 # complete faster-whisper/CTranslate2 model directory
  whisper-realtime/        # smaller complete CTranslate2 model directory
  wake.onnx                # chosen/trained openWakeWord wake phrase model
  embedding_model.onnx     # matching openWakeWord feature extractor
  melspectrogram.onnx       # matching openWakeWord mel frontend
  silero_vad.onnx           # Silero model supported by RealtimeSTT raw_onnx
  supertonic/              # full Supertonic 3 model snapshot and voice styles
```

Use the upstream model layouts, including their tokenizer/config and voice-style
files. Do not rename ONNX files inside the Supertonic snapshot. Missing assets
cause startup failure rather than an automatic download. The two Whisper paths
can refer to the same local directory to reduce storage, although separate
inference instances can still consume separate memory. A small final model and
a tiny realtime model are reasonable starting points; actual latency needs
measurement on the target CPU.

A customizable wake phrase requires an appropriate trained openWakeWord model.
Changing a string does not train a new phrase. Set the desired model as wake.onnx
and tune wakeThreshold after measuring false triggers in the target room.

For Ollama, provision `qwen3:4b` once with `ollama pull qwen3:4b` while the local
Ollama service is running. The module does not pull it at boot. Preserve the
Ollama model digest when recording a deployment; a model tag alone is mutable.
The module sets `OLLAMA_NO_CLOUD=1` when it manages Ollama. If
`ollama.enable = false`, the administrator must provide a local-only Ollama
service with that setting and the configured model already present.

Record all speech-model file hashes after provisioning:

```sh
python scripts/model_manifest.py record /var/lib/aurora-models /path/to/models.sha256.json
python scripts/model_manifest.py verify /var/lib/aurora-models /path/to/models.sha256.json
```

The manifest records an exact installed snapshot; it does not certify its source.
Keep model revisions, license terms, the manifest, `uv.lock`, and `flake.lock`
with the deployment. Model weights are not bundled in the ZIP or fetched by the
flake. Thus the flake locks code dependencies; full deployment reproduction also
requires the preserved model snapshots and Ollama digest.

## Interfaces and privacy

Overlay service: `org.example.VoiceOverlay`; object:
`/org/example/VoiceOverlay`; interface: `org.example.VoiceOverlay1`.
The backend uses SetState(s), SetMessage(s), SetLevel(d), and Reset(). The complete
existing contract is also recorded in `docs/org.example.VoiceOverlay1.xml`.
No new methods, renamed states, or compositor modifications are required.

LLM: `http://127.0.0.1:11434/v1/chat/completions`, OpenAI-compatible JSON-schema
response format. TTS: `http://127.0.0.1:7788/v1/audio/speech`, accepts input, model,
voice, and response_format="wav". `/health` reports TTS readiness. TTS binds only
to IPv4 loopback, limits request size and text length, and serializes synthesis.

STT deliberately uses a local Python adapter for wake gating, VAD, provisional
hypotheses, and final text. It does not expose an OpenAI transcription HTTP
endpoint. A batch upload API would not preserve this live revision contract;
a future server adapter should preserve the same event semantics.

HTTP clients accept literal loopback addresses only, ignore proxy environment
variables, and do not follow redirects. Models and audio are processed locally.
No audio files or transcript history are saved by the controller. Its error logs
omit transcript and model-response content; RealtimeSTT file logging is disabled.
Runtime offline flags block Hugging Face downloads. These settings are not a
network sandbox for every dependency. Verify with networking disabled on the
host; any separately configured service must meet the same local-only policy.
Local HTTP endpoints are accessible to other processes on the same machine.

## Development and validation

The lock uses Python 3.11 and CPU PyTorch 2.8.0. openWakeWord 0.6.0 declares
`tflite-runtime` on Linux, whose available wheels require Python <=3.11, even
though this application explicitly uses ONNX. RealtimeSTT 1.1.2 and Supertonic
1.3.1 are pinned. All resolved distributions and hashes are in uv.lock.

```sh
nix develop
uv sync --frozen --extra voice
uv run --frozen --extra voice python -m unittest discover -s tests -v
dbus-run-session -- uv run --frozen --extra voice python -m unittest discover -s tests -v
python scripts/test-package.py
```

For a real one-shot controller request without a microphone:

```sh
nix run .#assistant -- --config config/assistant.example.json --text 'Set volume to thirty percent'
```

This executes the requested action. It is not a dry run. The overlay and both
local inference services must already be running. Use `nix run .#default` for
the overlay. `nix build .#assistant` supplies both aurora-assistant and aurora-tts.

Validation in the delivery environment: 21 backend, HTTP contract, audio-gate, and D-Bus capability tests
passed; the D-Bus integration test was skipped because creating a session-bus
socket is prohibited. Existing overlay static tests passed. Nix execution was
blocked by the environment, so Nix evaluation/build and all native-library
resolution remain unverified. Flake pins were assembled from the upstream
build-system lock and a content hash of its source archive; Nix must verify them
on the target host. No microphone, model inference, or Plasma compositor was
available for an end-to-end test.

Before treating this as a persistent assistant, validate `nix flake check`, both
packages, repeated wake turns, silence timeout, service restarts, screen lock,
CPU latency, and playback feedback on the target machine with networking off.
Screen-lock detection and automatic microphone suspension while locked are not
implemented. Stop the target if listening while locked is unwanted. Multi-turn
conversation memory, barge-in, arbitrary desktop automation, CUDA support,
ARM packaging, and custom KWin effects are not implemented in this build.

## Upstream API references

- https://github.com/KoljaB/RealtimeSTT/tree/v1.1.2
- https://github.com/dscripka/openWakeWord/tree/v0.6.0
- https://docs.ollama.com/api/openai-compatibility
- https://github.com/supertone-oss-archive/supertonic-py
- https://github.com/pyproject-nix/uv2nix
