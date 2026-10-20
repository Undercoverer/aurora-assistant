# NixOS configuration

## Start here

Import `inputs.aurora-assistant.nixosModules.default` into the host's NixOS
modules, then set:

```nix
programs.aurora-assistant = {
  enable = true;
  user = "foxkj"; # Existing Plasma account.
  wakeWord.name = "alexa";
};
```

The default trained phrase is Hey Jarvis if `wakeWord.name` is omitted. Kev, Qwen,
Supertonic, provisioning, the shared llama.cpp router and desktop user services
are configured automatically. Default inference uses the CPU. No application
list, fixed D-Bus action list, ports or model paths are needed for this setup.
Download failures stop model provisioning rather than substituting another model.
Initial provisioning requires internet access; normal voice operation is local.

## Configure by task

| Group | Purpose | Common options |
| --- | --- | --- |
| `wakeWord` | Activation | `name`, `threshold`, `timeoutSeconds` |
| `recognition` | Speech input | `model`, `realtimeModel`, `inputDevice`, `language`, `silenceSeconds` |
| `speech` | Spoken output | `model`, `voice`, `wordSync` |
| `overlay` | Result/error display | `resultSeconds`, `errorSeconds` |
| `conversation` | Request and follow-up limits | `timeoutSeconds`, `followUpSeconds`, `maxFollowUps` |
| `kev` | Fast decisions | `model`, `threshold`, `contextSize`, `cacheRamMiB` |
| `planner` | Generation and complex requests | `model`, `contextSize`, `gpuLayers` |
| `models` | Asset provisioning | `enable`, `directory`, `revisions` |
| `inference` | Shared llama.cpp service | `package`, `port`, `startupTimeoutSeconds` |
| `catalog` | Idle-time D-Bus explanations | `enrich`, `persist`, `idleSeconds` |
| `diagnostics` | Content logging | `logContent` |
| `webSearch` | Optional online search through a local API | `enable`, `engines` |

See [the complete example](../examples/customized.nix). Each option has a
type, default where appropriate, and description in the generated option reference
(`nix build .#docs` in the assistant checkout). Existing safety and D-Bus scope
options remain under `safety` and `settings`.

## Common changes

```nix
programs.aurora-assistant = {
  recognition = {
    inputDevice = null; # Default microphone, or a SoundDevice name substring/index.
    silenceSeconds = 1.0; # Allow longer pauses before finalizing.
  };
  speech = { voice = "M1"; wordSync = true; };
  overlay = { resultSeconds = 8; errorSeconds = 15; };
  conversation.followUpSeconds = 15;
};
```

Wake names select trained models; changing the label does not train a new phrase.
For a custom trained ONNX model, set `wakeWord.source = { repo = "owner/repo";
revision = "exact-commit"; file = "wake.onnx"; };` and use `wakeWord.name` as its label.
Use actual repository values. See [model provisioning](SETUP.md) for available
sources and revision behavior.

For an external local chat server, set `planner.manageService = false`,
`planner.url = "http://127.0.0.1:9000/v1"` and `planner.model` to its served alias.
Kev stays managed unless `kev.manageService` is also disabled. For GPU inference,
select a compatible `inference.package` and then configure per-model `gpuLayers`;
changing layers alone does not add GPU support.

Model *names* select downloaded assets. `wakeWord.modelFile`,
`recognition.modelDirectory`, `recognition.realtimeModelDirectory`, and per-LLM
`modelFile` options are advanced local-path overrides. Normally leave them alone.
For fully manual assets, disable `models.enable` and follow the asset layout in
the provisioning guide; disabling it does not remove required model files.

## Existing configurations

Old option names still forward to the new options through NixOS rename modules,
with migration warnings. Defaults and runtime JSON field names are unchanged.
Use one spelling for a setting; different values under old and new names conflict
rather than silently overriding each other. The complete mapping is in
[option-renames.nix](../nix/option-renames.nix).

| Old option | New option |
| --- | --- |
| `models.wakeWord` | `wakeWord.name` |
| `models.stt`, `models.realtimeStt` | `recognition.model`, `recognition.realtimeModel` |
| `silenceSeconds`, `inputDevice` | `recognition.silenceSeconds`, `recognition.inputDevice` |
| `models.tts`, `voice`, `wordSync` | `speech.model`, `speech.voice`, `speech.wordSync` |
| `presentation.resultSeconds`, `presentation.errorSeconds` | `overlay.resultSeconds`, `overlay.errorSeconds` |
| `presentation.agentTimeoutSeconds` | `conversation.timeoutSeconds` |
| `modelDirectory`, `inferencePackage` | `models.directory`, `inference.package` |

The [flake-parts/import-tree example](../examples/flake-parts) uses the same options:
import the exported module into the host's NixOS module list, not directly into the
flake-parts module scope. Existing Kev/planner settings need no migration.

See [the semantic catalog](CAPABILITIES.md#idle-time-semantic-catalog) for cache behavior, limits and background resource controls.
