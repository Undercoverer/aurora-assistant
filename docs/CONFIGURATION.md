# Configuration and GitHub updates

## Use the repository as your flake input

```nix
inputs.aurora.url = "github:Undercoverer/aurora-assistant";
```

Keep the existing wrapper that imports `inputs.aurora.nixosModules.default`.
No flake-parts or import-tree layout change is needed. This repository is private;
Nix needs GitHub credentials with read access, configured outside committed files.
Alternatively, use Git over SSH if the machine already has a working GitHub key:

```nix
inputs.aurora.url = "git+ssh://git@github.com/Undercoverer/aurora-assistant.git";
```

The host's flake.lock pins a commit. Pushing a change does not silently change a
running system. Fetch a new revision, build, and apply it:

```sh
cd /etc/nixos
nix flake update aurora
sudo nixos-rebuild switch --flake .#framework
```

Keep your local `programs.aurora-assistant` settings in the host repository.
They do not belong in this project. Do not add a `nixpkgs.follows` override until
the build is working with Aurora's own locked dependencies.

## Wake phrase and speech settings

```nix
programs.aurora-assistant = {
  enable = true;
  user = "YOUR_USERNAME";
  modelDirectory = "/var/lib/aurora-models";

  wakeModel = "/var/lib/aurora-models/hey_aurora.onnx";
  wakeThreshold = 0.5;
  wakeTimeout = 8;
  silenceSeconds = 0.7;
  maxUtteranceSeconds = 45;

  sttModel = "/var/lib/aurora-models/whisper";
  realtimeSttModel = "/var/lib/aurora-models/whisper-realtime";
  language = "en";
  inputDevice = null;
  voice = "F1";
  ollama.model = "qwen3:4b";

  applications = {
    files = "org.kde.dolphin.desktop";
    browser = "firefox.desktop";
  };
};
```

`hey_aurora.onnx` is an illustrative filename, not a bundled model. The actual
phrase is encoded in the trained openWakeWord model. Renaming a model or typing
a different phrase into a config does not change what it detects. Supply a
pretrained model for the desired phrase or train a compatible custom model.
The feature-extractor files `embedding_model.onnx` and `melspectrogram.onnx`
still come from modelDirectory. The initial default wakeModel is
`${modelDirectory}/wake.onnx`.

Higher wakeThreshold requires more confidence and tends to reduce false wakes,
but can miss real calls. Lower it only after checking the intended model and
microphone. wakeTimeout is the time to start speech after activation.
silenceSeconds is the end-of-speech silence. maxUtteranceSeconds bounds the turn,
including final transcription; timeout discards the request and reloads STT.

inputDevice accepts a SoundDevice input index or device-name substring. `null`
uses its default. Use an actual input, not a speaker-monitor source. voice accepts
M1–M5 or F1–F5 and selects a local Supertonic style. language controls recognition;
TTS currently synthesizes with `lang="en"`.

Change Nix settings and rebuild to update the generated service configuration.
Do not edit generated files in `/nix/store`. The JSON example is for running
`aurora-assistant --config ...` manually; editing it does not affect the NixOS
service. The overlay's visual settings are separate: use its editor or the
existing D-Bus theme methods, then SaveConfig to persist them.

## Applications

The left side is a semantic alias supplied to the LLM. The right side is an
installed `.desktop` filename. With `files = "org.kde.dolphin.desktop"`, a request
such as "open files" can become:

```json
{"actions":[{"name":"open_app","argument":"files"}],"reply":""}
```

The executor maps `files` to the configured filename and calls
`gtk-launch org.kde.dolphin.desktop`. The model cannot supply command-line
arguments, executable paths, or desktop filenames that are absent from this map.
The alias need not exactly match the spoken sentence, but clear aliases improve
selection. Applications must be installed separately. Filenames vary by package.
List candidates on the target host:

```sh
find /run/current-system/sw/share/applications \
  ~/.nix-profile/share/applications ~/.local/share/applications \
  -maxdepth 1 -name '*.desktop' -printf '%f\n' 2>/dev/null
```

A successful launch request means the launcher accepted it, not that the
application finished opening or reached a particular screen.

## Model capacity and permissions are separate

`ollama.model = "qwen3:8b"` selects a larger model; provision that model in Ollama
before restarting the controller. Qwen3 14B is another option when memory and
latency permit. The appropriate size depends on host RAM, GPU memory, model
quantization, and the latency you can accept. The model must support the supplied
structured-output schema. A larger model does not receive extra system access.
Changing this option does not enable GPU acceleration. The current speech package
is CPU-only; Ollama acceleration is configured separately through NixOS.

The current controller supports one planning pass with at most four actions.
It has no recursive agent loop, persistent conversation memory, automatic D-Bus
service discovery, or model-generated Python/shell execution.

## D-Bus capabilities

D-Bus support is configured with `dbusActions`. Every entry fixes the bus,
destination, object path, interface, method, argument signature, and arguments.
The model sees the alias and description and can select that capability. It
cannot replace its endpoint or arguments. For example, this uses the already
pinned overlay interface:

```nix
programs.aurora-assistant.dbusActions.jade_theme = {
  description = "Change the assistant overlay color palette to northern jade";
  bus = "session";
  destination = "org.example.VoiceOverlay";
  path = "/org/example/VoiceOverlay";
  interface = "org.example.VoiceOverlay1";
  member = "LoadPalette";
  signature = "s";
  arguments = [ "northern-jade" ];
  expectedReply = [ true ];
  successMessage = "Overlay palette changed.";
};
```

The model selects `{ "name": "dbus", "argument": "jade_theme" }`. Endpoint
names and argument types are validated before starting the assistant. Errors,
access denials, timeouts, and unexpected replies do not report success. If
expectedReply is omitted, a normal D-Bus method return is sufficient. This sample
changes the current palette in memory; it does not invoke SaveConfig.

For another desktop service, inspect its actual interface on the target host:

```sh
busctl --user list
busctl --user introspect SERVICE OBJECT_PATH
# For system services:
busctl --system introspect SERVICE OBJECT_PATH
```

Copy the exact endpoint, method, and signature into a capability. The service must
actually expose the operation, and its normal D-Bus/Polkit rules still apply.
The controller runs as the desktop user and does not bypass those rules. Merely
exposing a D-Bus interface does not make every method suitable for voice control.

This version supports fixed-argument capabilities. Several presets can expose
useful choices such as different brightness levels. Variable model-supplied
arguments need explicit schemas and range validation in a future extension.
A general "call anything on D-Bus" capability is not enabled.

## torchaudio packaging fix

The previous wheel package did not expose PyTorch's nested shared-library
directory to autoPatchelf. It also contained optional FFmpeg 4/5/6 plug-ins and
SoX bindings without their native dependencies. The new override:

- Adds the matching locked `torch` package and `pkgs.sox` to buildInputs.
- Adds `${torch}/${python.sitePackages}/torch/lib` to the autoPatchelf search path.
- Removes optional `torio/lib/*ffmpeg*.so` plug-ins. Aurora uses SoundDevice and
  SoundFile for audio I/O; it does not use torio FFmpeg streaming.
- Disables torio FFmpeg probing with TORIO_USE_FFMPEG=0 in the application runtime.
- Keeps autoPatchelf strict; missing core libraries are not ignored.

`nix flake check` now includes an import check for torch, torchaudio, sounddevice,
and soundfile. This must run on a Nix-capable host. The edit addresses the reported
dependencies, but a successful Nix build has not been verified in the delivery
environment. The Python suite passes 21 tests; one live session-bus integration
test is skipped there because socket creation is unavailable.
