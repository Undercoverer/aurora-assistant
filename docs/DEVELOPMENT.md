# Build, documentation, and validation

## Generate option documentation

From the repository root on a Nix-capable x86_64 Linux machine:

```sh
nix build .#docs
ls result/share/doc/aurora
```

`OPTIONS.md` and `options.json` come from `pkgs.nixosOptionsDoc`, using the actual
`programs.aurora-assistant` declarations in `nix/module.nix`. They include option
types, defaults, descriptions, and supplied examples. Missing-description warnings
are errors. Package defaults use human-readable expressions rather than store
paths. The output also contains `docs/` and `examples/` with the source guides.
The `documentation` flake check builds this package, so doc failures are build
failures rather than silently stale generated pages.

Add descriptions whenever an option is added, including nested submodule fields.
Add examples for values whose syntax is not clear from their type. Keep deployment
examples in `examples/` and document migrations in the guides. Generated reference
files are built from the module, not manually maintained in the repository.

## Build and test

```sh
nix build .#assistant .#default .#docs
nix flake check -L
```

The backend check runs Python tests under a private session bus. The audio import
check loads the pinned Torch, TorchAudio, SoundDevice, and SoundFile libraries.
The overlay build verifies embedded resources. Python unit tests use fakes for
model inference and desktop effects; they are not a replacement for a real Plasma
session test. Model download/inference, Wayland rendering, and actual KDE control
must be checked on the target host.

To run only Python tests from a development environment with the project installed:

```sh
PYTHONPATH=backend python -m unittest discover -s tests -v
```

## Add a capability

Prefer an existing native D-Bus interface. Discover its service name, object path,
and input/output signatures. Use typed calls and explicit readback where available.
Do not add a shell-string escape hatch. Common-operation adapters must validate
inputs, select a concrete target, bind preparation to a service owner, and report
uncertain effects honestly. Unknown methods stay on the generic approval path.

The Aurora adapter is only for controls with no suitable native interface. Add
its methods to `docs/org.aurora.Desktop1.xml`, describe the underlying backend in
DBUS.md, and test parameter validation, expiry/restarts, and failed operations.
Do not describe a wrapper around a command as a native KDE or PipeWire interface.

## Manual runtime example

The sample `config/assistant.example.json` uses the same current model directory
layout. For a manual run, install and start Ollama, provision the named assets,
start the overlay and TTS server, and start the desktop adapter with
`aurora-desktop --config config/assistant.example.json`. In another terminal in
the same desktop session, run
`aurora-assistant --config config/assistant.example.json --text "pause playback"`.
This executes a real request. The normal NixOS module starts these services for
you; the JSON file is a developer example and does not override Nix-managed config.
