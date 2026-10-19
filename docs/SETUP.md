# Declarative setup, settings discovery, and local approval

This is the current setup guide. The original overlay editor and D-Bus contract
remain unchanged. The package targets x86_64 Linux with CPU speech inference.
Native Nix/KDE/audio integration still needs validation on the target machine.

## Configure models by name

For full file layouts, see [the integration examples](../examples/README.md).
Keep the GitHub input and the flake-parts wrapper that imports
`inputs.aurora.nixosModules.default`. Put these settings in the host's NixOS module:

```nix
programs.aurora-assistant = {
  enable = true;
  user = "YOUR_USERNAME";

  models = {
    enable = true;
    stt = "base.en";
    realtimeStt = "tiny.en";
    wakeWord = "hey_jarvis";
    silero = "silero-vad";
    tts = "supertonic-3";
  };
  kev.model = "qwen3:0.6b";
  ollama.model = "qwen3:4b";
  safety = {
    enable = true;
    model = "qwen3:4b";
  };

  silenceSeconds = 0.7;
  wakeTimeout = 8;
  maxUtteranceSeconds = 45;
  wakeThreshold = 0.5;
  voice = "F1";
  # Applications are discovered automatically; aliases are optional.
};
```

Speech names such as `base.en` resolve to `Systran/faster-whisper-base.en`.
A full Hugging Face repository ID can also be supplied, but it must contain a
complete CTranslate2 Whisper model. Unknown or incompatible repositories fail
provisioning; they do not silently select another model. Silero currently accepts
`silero-vad` and uses the model bundled in the locked Python package. TTS accepts
`supertonic`, `supertonic-2`, or `supertonic-3`; the SDK provides their tested
repository revisions. No Supertonic inference is sent to an online service.

Built-in wake model names are `alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`,
`timer`, and `weather`, as provided by the pinned openWakeWord 0.6.0 package.
The actual spoken phrase is part of the trained model. An arbitrary name such as
`hey_aurora` fails unless a trained model source is configured. For a custom model:

```nix
programs.aurora-assistant.models = {
  wakeWord = "hey_aurora";
  wakeSource = {
    repo = "YOUR_ACCOUNT/YOUR_WAKE_MODEL";
    revision = "EXACT_HUGGING_FACE_COMMIT";
    file = "hey_aurora.onnx";
  };
};
```

That example requires a real repository and compatible trained ONNX file. It does
not train a new phrase. Provisioning currently expects publicly downloadable
models; it does not put access tokens in Nix configuration. The built-in wake
model licenses differ from the openWakeWord code license; review the upstream
model terms for your intended use.

## Download lifecycle and errors

`aurora-models.service` is a **system service** running as the configured desktop
user. It downloads models during explicit deployment/startup provisioning. It
pulls the Kev, planner, and reviewer models through the local Ollama service, downloads
speech assets, checks required files and ONNX/TTS loading, and writes a manifest
of resolved revisions, Ollama digests, and file hashes. It stages all speech files
before atomically switching `modelDirectory/current` to the new generation.
Failed staging does not replace an older complete generation. The new runtime
configuration still refuses to start against an old, mismatched generation.

Unchanged, verified models are reused. Normal voice processing and TTS run with
offline flags and never invoke the provisioner themselves. A normal offline boot
uses the existing speech snapshot and locally installed Ollama models. If a model
is missing, provisioning must have network access to restore it. A misspelled
model, missing repository, incompatible layout, or network failure makes the
provisioning service fail with an error in its journal.

```sh
cd /etc/nixos
nix flake update aurora
sudo nixos-rebuild switch --flake .#framework
systemctl status aurora-models.service
journalctl -u aurora-models.service -b
```

After correcting a name or restoring connectivity:

```sh
sudo systemctl restart aurora-models.service
systemctl --user restart aurora-assistant.target
```

The controller and TTS user services run an offline manifest check before loading
models. They retry startup while provisioning is incomplete. Use this command to
check the active requested snapshot without downloading anything:

```sh
aurora-models --config /etc/aurora-assistant/models.json \
  --root /var/lib/aurora-models --check
```

`modelDirectory` defaults to `/var/lib/aurora-models`. Keep a custom managed
location outside the user's home because the provisioning service has
ProtectHome enabled. Old complete generations are retained to avoid deleting
model assets still in use. They are not garbage-collected automatically.

Optional `models.revisions.stt`, `.realtimeStt`, and `.tts` pin Hugging Face
commits. Without an explicit STT revision, the first download resolves the
repository's current commit and records it. Subsequent unchanged starts reuse
that snapshot. To request an update, change the revision or explicitly run the
provisioner with `--refresh` as the configured user. Ollama tags can move; the
manifest records the installed digest. Flake locks pin code, not all model tags.

For manually managed assets, set `models.enable = false`; use modelDirectory and
the `wakeModel`, `sttModel`, and `realtimeSttModel` path options. Install Ollama
models yourself in that mode. Do not retain old path overrides when switching
to named provisioning unless those overrides are intentional.

## Natural multi-action requests

The planner can inspect state over several bounded rounds before preparing one
batch of up to four mutations. For example:

- "Switch to Breeze Dark, mute the microphone, and pause playback."
- "Which color schemes are installed?"
- "Is the microphone muted?"
- "What is the current value of this exposed KDE setting?"

Installed global themes and color schemes are discovered using Plasma's tools.
The planner must choose an installed identifier. Global themes use
`plasma-apply-lookandfeel`; color schemes use `plasma-apply-colorscheme`. Their
stored setting is read back after application. Microphone mute uses the default
PipeWire source; speaker mute uses the default sink. These are distinct actions.
Microphone mute is moved to the end of a batch. Playback uses direct MPRIS calls. The common action selects the sole playing
player or sole available player; ambiguous selection requires further discovery.
See [DBUS.md](DBUS.md) for native versus adapter paths.

Visible installed XDG applications are discovered automatically over the adapter.
No aliases are required. Optional application aliases retain their existing meaning: `files` maps to a configured
installed desktop-entry filename and is launched through gtk-launch. A successful
launch request does not prove that an application finished opening.

A failed or unverifiable operation stops later operations. Earlier changes are
not automatically rolled back. A method can have changed state before returning
an error; the response states this instead of claiming nothing happened.
Muting the default microphone can prevent a spoken unmute request. Unmute through
Plasma audio controls or another physical/local input method. No barge-in or
voice-confirmation mechanism is added in this version.

## Generic D-Bus discovery and changes

The planner can list active services, inspect objects and child paths, read
properties, set readable/writable properties, and propose typed method calls.
Signatures come from live introspection, not from model guesses. Property writes
record the old value, verify that it has not changed while awaiting approval,
check the service owner has not restarted, and read back the new value.
Write-only properties are not changed by the generic property path. Method
side effects cannot generally be verified; a successful return is reported as
such, not as proof of the intended effect.

Discovery is scoped in Nix:

```nix
programs.aurora-assistant.settings = {
  sessionPrefixes = [ "org.kde." "org.mpris." "org.example.VoiceOverlay" "org.aurora.Desktop" ];
  systemPrefixes = [ "org.freedesktop.UPower" ];
  maxRounds = 5;
};
```

Prefixes control which services can be inspected. Add specific prefixes for
other services you intend to use. Credentials/wallet services, terminal/launcher
services, and known generic code-execution methods are excluded. Generic method
calls and property changes **always need human approval**, even when the reviewer
says allow. Existing fixed `dbusActions` also require approval in this settings
agent. D-Bus/Polkit permissions continue to apply; nothing runs as root to bypass
them. Reads are scoped but still depend on the service honoring standard read
semantics. A model does not receive private credentials merely because a service
is present on the bus.

There is no universal interface for every KDE or Linux setting. This release
covers live D-Bus interfaces and the implemented Plasma/audio backends. It does
not edit arbitrary files, run arbitrary shell commands, change Nix configuration,
install software, or perform recursive root-level system administration. Runtime
changes to declaratively managed settings may be overwritten by a Nix rebuild.

## Local reviewer and approval

The reviewer uses a separate, tool-free conversation with the original request
and exact prepared operations. It returns allow, ask, or block. It can use the
same local weights as the planner or a different `safety.model`. Reusing weights
does not imply independent failure modes. No claimed confidence score grants
permissions. The deterministic executor policy remains in force.

Known low-risk desktop actions can run after review. Unknown D-Bus mutations,
reviewer uncertainty, and reviewer failure require local approval. Blocked plans
do not execute. Disabling the reviewer does not disable approval for generic
D-Bus mutations.

The overlay displays that approval is needed. In a terminal belonging to the
same desktop user, inspect the complete proposed plan:

```sh
aurora-control pending
```

Then approve or deny its exact returned id:

```sh
aurora-control approve EXACT_ID_FROM_PENDING
# or
aurora-control deny EXACT_ID_FROM_PENDING
```

Approval uses a mode-0600 Unix socket inside a mode-0700 runtime directory and
checks the peer UID. It applies to one frozen plan, expires after two minutes,
and cannot be reused. No approval is inferred from unrelated speech. Pending
requests and plans live in memory and disappear on shutdown. The socket provides
no arbitrary execution endpoint. A graphical approval dialog is not implemented;
the local CLI is the confirmation interface for this release.

## Validation status

The Python suite exercises model staging/caching/failure, typed D-Bus arguments,
state-change and service-restart checks, the bounded planning loop, reviewer
failure, one-use approval, action validation, and microphone gating. Live socket
integration, model downloads/inference, Nix builds, and Plasma execution still
need target-host testing. `nix flake check` includes the backend suite and native
Torch/TorchAudio/SoundDevice/SoundFile imports; do not treat an untested deployment
as verified merely because the Python mock-based tests pass.
