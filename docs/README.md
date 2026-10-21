# Aurora documentation

Start with [QUICKSTART.md](QUICKSTART.md). It covers prerequisites, installation,
first use, updates, and common failures. [Examples](../examples/README.md) contain
regular-flake and flake-parts/import-tree file layouts.

- [WEB_SEARCH.md](WEB_SEARCH.md): opt-in local SearXNG API, summaries, sources, and network boundaries.
- [SPEECH_FEEDBACK.md](SPEECH_FEEDBACK.md): Kev escalation notices and word-synchronized reply captions.
- [SETUP.md](SETUP.md): model names, custom wake words, offline operation, and approvals.
- [DBUS.md](DBUS.md): direct calls, adapter boundaries, qdbus examples, and action coverage.
- [ARCHITECTURE.md](ARCHITECTURE.md): Kev routing, planner discovery, review, and services.
- [DEVELOPMENT.md](DEVELOPMENT.md): build generated option docs and run tests.
- [org.example.VoiceOverlay1.xml](org.example.VoiceOverlay1.xml): pinned overlay contract.
- [org.aurora.Desktop1.xml](org.aurora.Desktop1.xml): desktop adapter contract.

Build `nix build .#docs` in the repository to generate OPTIONS.md and options.json
from the NixOS module declarations. The build also includes these guides and the
examples. The generated files are under `result/share/doc/aurora/`.
[CONFIGURATION.md](CONFIGURATION.md) documents the current grouped module options.
[ASSISTANT.md](ASSISTANT.md) retains historical backend notes.

See [MCP_MIGRATION.md](MCP_MIGRATION.md) for staged backend coverage,
[RECALL_EVALUATION.md](RECALL_EVALUATION.md) for optional recall measurements, and
[ACCEPTANCE.md](ACCEPTANCE.md) for target-host acceptance.
