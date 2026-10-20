> For grouped NixOS options and migration names, see [Configuration](CONFIGURATION.md). Older option names below remain compatible.

# One llama.cpp router for Kev and Qwen

Aurora uses llama.cpp 0.7.0 or newer for both decision and language inference.
`pkgs.llama-cpp` is preferred when the flake's nixpkgs provides that version;
otherwise a source-hashed 0.7.0 compatibility derivation builds with nixpkgs tools
and libraries. This may still require a local C++ build. The version update is
not a measured speed improvement.

One `aurora-inference.service` runs the router on loopback port 8008. Requests use
the `model` field to select Kev at `/v1/systemone` or Qwen at
`/v1/chat/completions`. The router starts separate worker processes internally;
it does not combine model weights or their memory use. Both workers load at
startup, idle sleeping is disabled, and the simultaneous-model limit equals the
number of managed roles. The controller waits until both report loaded before
accepting speech. This avoids normal cold loads during the first request, provided
the host has enough memory. A crash or manual unload can still require a reload.

Supertonic remains a separate speech service. It is an ONNX-based synthesis engine,
not a llama.cpp model. Whisper.cpp is a separate project and server. Although
llama.cpp has an audio-transcription endpoint for supported audio models, it is
not a drop-in server for this project's faster-whisper/RealtimeSTT streaming
pipeline. Wake word, Silero VAD and live transcription therefore remain in the
controller. No extra STT or wake-word service is added. See the upstream
[llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/v0.7.0/tools/server/README.md)
and [whisper.cpp server documentation](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server).

## Migrate an existing host

Remove `programs.aurora-assistant.ollama.enable` and `.ollama.model`. They now
produce explicit Nix migration errors. Replace an old `safety.backend = "ollama"`
with `"kev"` or `"planner"`. Remove an explicit old `safety.model = "qwen3:4b"`;
the default follows the new planner alias. Ollama tags do not identify GGUF files.

A complete host-level inference configuration is:

```nix
programs.aurora-assistant = {
  enable = true;
  user = "alice"; # Use the existing Plasma account.
  kev.model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
  planner = {
    model = "hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M";
    contextSize = 32768;
    gpuLayers = 0;
  };
  safety.backend = "kev";
  inference.port = 8008;
  inference.startupTimeoutSeconds = 180;
};
```

The existing flake-parts/import-tree layout does not change. These options belong
in the imported NixOS host module. After editing that module:

```sh
cd /etc/nixos
nix flake update aurora
sudo nixos-rebuild switch --flake .#framework
systemctl status aurora-models.service
journalctl -u aurora-models.service -b --no-pager
```

Replace the input and host names if yours differ. Wait for successful provisioning,
then restart the user services from the configured Plasma session:

```sh
systemctl --user restart aurora-inference.service aurora-tts.service aurora-desktop.service aurora-controller.service
aurora-report --since '30 minutes ago' --clipboard
```

Aurora no longer enables or contacts Ollama. If your own Nix configuration separately
enables `services.ollama`, that service remains enabled until you remove that setting.
Existing Ollama model data and old Aurora generations are not deleted automatically.

## Model downloads and offline starts

`aurora-models.service` downloads one GGUF per managed inference role from the given
`hf.co/owner/repository:QUANT` name. The default planner uses the official Qwen
repository. Matching is case-insensitive and uses quantization-name boundaries. Managed API
aliases normalize the quantization tag to uppercase, matching llama.cpp presets.
Missing, ambiguous or split-file matches fail provisioning. The downloader checks
the GGUF header; architecture compatibility and full model loading are checked by
the server at startup, not guaranteed by the filename or header.

Downloads resolve the repository revision before fetching the file. The manifest
records that commit, filename and SHA-256 content hash. Set `models.revisions.kev`
and `models.revisions.planner` to exact Hugging Face commit IDs to pin weights.
An unchanged verified generation is reused without downloads or inference-server
requests. Changing the model specification stages a complete new generation before
activation, so allow disk space for both old and new generations.

Normal services pass local `--model` paths, never a download flag. For manually
managed files, set `models.enable = false`, provide all speech assets, and set
`kev.modelFile` and `planner.modelFile` to existing GGUF files.

## Package overrides and external local servers

Both managed roles use `inferencePackage`. The old `kev.package` and `kev.port`
options are renamed to `inferencePackage` and `inference.port`, respectively. For example, if the host's nixpkgs has
a compatible llama.cpp package, select it explicitly in a module accepting `pkgs`:

```nix
{ pkgs, ... }: {
  programs.aurora-assistant.inferencePackage = pkgs.llama-cpp;
}
```

An override must provide `bin/llama-server`, System One support for Kev, and the
chat flags used by the planner. GPU offload requires a package built for the actual
GPU backend, working drivers and appropriate `kev.gpuLayers`/`planner.gpuLayers`.
The compatibility build is CPU-only. Context size also affects memory use.

To use an already running local chat server:

```nix
programs.aurora-assistant.planner = {
  manageService = false;
  url = "http://127.0.0.1:8080/v1";
  model = "my-local-model-alias";
};
```

The external server must advertise that exact alias at `/v1/models` and accept the
OpenAI structured-response schema. Its model is not downloaded by Aurora. Only
literal loopback HTTP endpoints are accepted. `kev.manageService = false` provides
the corresponding option for an external System One server.

Review defaults to Kev. `safety.backend = "planner"` sends a separate tool-free
chat request to the planner; with the managed single-model server, `safety.model`
must equal `planner.model`. The managed Qwen server uses Jinja and
`{"enable_thinking":false}` to avoid generating an extra reasoning section.

## Manual developer launch

After provisioning, a local preset equivalent to the default managed setup is:

```ini
version = 1
[*]
parallel = 1
sleep-idle-seconds = -1
[hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M]
model = /var/lib/aurora-models/current/kev.gguf
ctx-size = 32768
cache-ram = 512
batch-size = 32768
n-gpu-layers = 0
load-on-startup = true
[hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M]
model = /var/lib/aurora-models/current/planner.gguf
ctx-size = 32768
n-gpu-layers = 0
load-on-startup = true
jinja = true
chat-template-kwargs = {"enable_thinking":false}
```

Save it as `aurora-models.ini`, then launch one compatible server:

```sh
llama-server --models-preset ./aurora-models.ini --models-max 2 \
  --host 127.0.0.1 --port 8008
```

Do not start another copy while the unit uses that port. The managed service has a
private runtime cache and uses only local model paths in its preset. Stop/restart
`aurora-inference.service` to stop/restart the router and all child workers together.

## Latency limits

The router simplifies configuration; it does not make model inference intrinsically
faster. Preloading both models and disabling Qwen thinking remove two sources of
request delay. Supertonic synthesis, local word alignment, model size, CPU contention
and available RAM still affect latency. Timed captions currently require synthesis
and alignment before playback begins. Use phase durations from `aurora-report`
to identify the remaining delay; `wordSync = false` can isolate alignment cost.
The shared router and real audio/model latency still require target-host testing.

See [decision workflow](DECISION_WORKFLOW.md#context-and-cache) for Kev context, cache and validation limits.
