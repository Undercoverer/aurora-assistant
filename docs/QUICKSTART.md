> For grouped NixOS options and migration names, see [Configuration](CONFIGURATION.md). Older option names below remain compatible.

# Install and use Aurora

## Requirements

Use an existing x86_64 NixOS machine with KDE Plasma on Wayland, a working desktop
user session, PipeWire/WirePlumber audio, and a microphone. This module does not
configure your display manager, disks, hardware, user account, or audio stack.
Test the microphone and speaker in Plasma before installing the assistant.
Speech inference is currently CPU-only. Kev and the planner also default to CPU;
GPU offload requires a compatible inferencePackage and configured gpuLayers.
Choose models that fit your available memory and disk space; no latency target
has yet been measured on a real deployment.

## Add the module

Add `aurora.url = "github:Undercoverer/aurora-assistant";` to flake inputs and
`aurora.nixosModules.default` to your host's NixOS module list. Use the complete
[examples](../examples/README.md) for either regular flakes or flake-parts/import-tree.
If this repository is private, the host must have read access.

The smallest host configuration is:

```nix
programs.aurora-assistant = {
  enable = true;
  user = "alice"; # An existing Plasma account, not a new account declaration.
};
```

This uses the trained `hey_jarvis` wake model, base.en final recognition, tiny.en
provisional recognition, Supertonic 3 with voice F1, Kev-4B for decisions, and
Qwen3-4B Q4_K_M for planning. These defaults can be written explicitly:

```nix
programs.aurora-assistant = {
  enable = true;
  user = "alice";
  kev.model = "hf.co/ggml-org/Kev-4B-GGUF:Q4_K_M";
  planner.model = "hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M";
  safety.backend = "kev";
};
```

No per-application aliases or D-Bus command definitions are needed. The model
names above are examples, not a hardware sizing guarantee. See SETUP.md to change
speech models or provide a trained custom wake model.

## Build and first start

From your host configuration directory:

```sh
nix flake update aurora
sudo nixos-rebuild switch --flake .#workstation
systemctl status aurora-models.service
journalctl -u aurora-models.service -b
```

Replace workstation with your existing host output name. The first setup downloads
and validates the named models. A wrong model name causes provisioning to fail;
it does not silently substitute another model. Wait for successful provisioning.
The user services retry their offline asset checks while it runs. Then, from a
terminal in the configured desktop user's Plasma session:

```sh
systemctl --user restart aurora-assistant.target
systemctl --user status aurora-desktop.service aurora-controller.service aurora-tts.service aurora-inference.service
journalctl --user -u aurora-controller.service -b
```

Say the trained wake phrase, then "pause playback" with one supported media player
running. The overlay shows provisional words, then the completed request. The
spoken result follows execution. Test "which applications are installed?", then
"open Dolphin". Test "which color schemes are installed?", then "use Breeze Dark
colors". Installed theme identifiers differ from spoken names and are discovered.
A global theme may change more than colors. A multi-action example is "pause
playback and mute the microphone". Microphone mute runs last; use Plasma controls
to unmute it afterward because voice input may no longer work.

## Approval

When the overlay requests local approval, inspect the exact plan in a terminal:

```sh
aurora-control pending
aurora-control approve TOKEN_SHOWN_BY_PENDING
# Or decline:
aurora-control deny TOKEN_SHOWN_BY_PENDING
```

Approval ends when its token expires or the request deadline is reached. Generic D-Bus mutations require approval;
common built-in controls still pass through the configured model reviewer.
There is no graphical approval dialog yet. A model's confidence never grants
extra authority.

## Updates and recovery

Update the input, then rebuild using the commands above. Keep local preferences
in your host configuration, not the upstream repository or /nix/store. If model
provisioning fails, correct the model name or network issue, rebuild if needed,
then run `sudo systemctl restart aurora-models.service`. Existing complete model
files remain intact after a failed staged download.

| Symptom | Check |
| --- | --- |
| Missing shared library during build | Capture the complete `nix log` output; native packaging needs target-host validation. |
| Model service fails | Read its system journal; check model ID, disk space, repository access, and available disk space. |
| Controller keeps restarting | Run the offline model check in SETUP.md; check the TTS service and user D-Bus session. |
| No overlay | Check `aurora-voice-overlay.service` and that this is the configured user's Plasma Wayland session. |
| No microphone signal | Check Plasma input selection and mute state; `inputDevice = null` uses the default input. |
| Wrong player or several players | Ask for a particular discovered MPRIS player; the common shortcut refuses an ambiguous selection. |
| Application absent | It needs a visible installed XDG desktop entry in the desktop service's environment. Restart the service after changing session paths. |
| Discovery limit reached | Narrow the request. No changes run when discovery exhausts its limit. |
| D-Bus denied | Check service scope and ordinary D-Bus/Polkit access. Aurora does not run as root. |

To stop the assistant for this login session, use
`systemctl --user stop aurora-assistant.target`. To disable it persistently, set
`programs.aurora-assistant.enable = false` and rebuild. Model files are retained.

For service failures, delays, and a single copyable diagnostic report, see
[Troubleshooting](TROUBLESHOOTING.md). For discovered capabilities, see
[the D-Bus catalog](CAPABILITIES.md).

Existing Ollama-based installations must follow [the llama.cpp migration](LLAMA_CPP.md).
