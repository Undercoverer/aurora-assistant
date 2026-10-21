# Aurora assistant

A local Linux voice assistant for KDE Plasma on Wayland, with openWakeWord,
Silero VAD, RealtimeSTT/faster-whisper, Kev/Qwen through llama.cpp, and Supertonic
speech. Named models are provisioned explicitly; normal voice operation is offline.
Optional web search is configured separately.

Start with the [installation guide](docs/QUICKSTART.md),
[NixOS configuration](docs/CONFIGURATION.md), and
[regular-flake or flake-parts/import-tree examples](examples/README.md).
Use [troubleshooting](docs/TROUBLESHOOTING.md) for unified service reports.

The strict MCP backend is the default for controller desktop actions, adapter
queries, fixed shortcuts and generic D-Bus execution. Live service listing and request-driven introspection provide
bounded discovery for each request, with exact approval correlation. Embedding recall is also opt-in; it preserves lexical evidence and
does not replace Kev or grant approval. See [migration status](docs/MCP_MIGRATION.md),
[recall evaluation](docs/RECALL_EVALUATION.md), and
[target-host acceptance](docs/ACCEPTANCE.md) for coverage and remaining gates.

Nix package builds and isolated D-Bus tests run in CI. Real microphone/speaker,
KWin rendering, deployed model accuracy and target-CPU latency still need
acceptance on the target machine.

## Overlay and palette editor


A local, configurable assistant overlay for KDE Plasma on Wayland. Qt 6/QML +
LayerShellQt, compiled GPU GLSL, D-Bus state changes, and a **live visual editor** and 10 color-only palettes.

## Fast start

This project uses a Nix flake. From the extracted directory:

```sh
nix run . -- --editor
```

This launches **both** the translucent desktop overlay and an ordinary, clickable
settings window. The editor's sliders, numbers, hex color fields, color palette selector, enum menus,
font field, and toggles update the overlay immediately, using the **same**
ThemeManager instance. Move the editor window away from the text/orb to see the
preview. Choose a color palette from the **Color palette** selector and click **Apply colors**.
The color swatches preview the four aurora colors, while applying it changes the
aurora, edge glow, orb, text, and vignette colors **without changing geometry**.
Choose a preview state from the toolbar; “Animate level” simulates a
microphone waveform when listening or speaking. Use **Save config** to persist
changes. **Reload disk** discards in-memory changes. **Your baseline** previews the bundled default profile (now based on the
user-tuned values supplied for this release) and does not overwrite your
existing runtime configuration until you explicitly save.

Normal headless-control mode (overlay only):

```sh
nix run .
```

Only one instance can own `org.example.VoiceOverlay`, so stop the ordinary
instance or user service before launching `--editor` and vice versa. The editor
is intentionally a normal window, not another layer-shell input surface.

A `flake.lock` is included. Retain it for reproducible code dependencies. No `nix-shell` or `cmake` command is needed.

## Where the settings are stored

The active, editable runtime file is:

```
~/.config/aurora-voice-overlay/config.json
```

The bundled `config/default.json` is an exact copy of the submitted tuned
profile (also saved as `config/user-reference.json`) and provides initial defaults and fills in
missing options from older config files. Editing the bundled default file does
not override an existing runtime config. To apply the bundled profile, click
**Your baseline**, then **Save config** in the editor; or remove/rename the
existing runtime JSON and restart. Existing settings are not silently erased. Color palettes are independent
from full presets: the old **Preset** menu resets layout parameters, whereas
**Color palette** keeps your chosen speed, offsets, positioning, scale, etc.

Settings are reloaded from disk automatically after external edits. Changes
made using the editor take effect immediately, but do not persist until saved.

## Color palettes (new)

There are ten bundled palette files, in `palettes/`. They all keep your existing
shader, orb placement, DPI scale, contrast strength, animation speeds and other
numeric settings. They only change color properties (aurora gradient and edge,
orb/glow/border/waveform, text/caret/contrast, vignette); the error-state reds
remain unchanged.

| Palette | Appearance |
| --- | --- |
| `aqua-violet` | Your original turquoise, blue and violet colors |
| `northern-jade` | Mint green and jade |
| `rose-quartz` | Blush pink and lilac |
| `solar-flare` | Warm gold, orange, pink |
| `deep-ocean` | Teal into saturated deep blue |
| `ultraviolet` | Orchid and electric purple |
| `arctic-mist` | Ice blue and soft white |
| `ember-noir` | Muted amber with rose and plum |
| `lime-electric` | Acid lime, green, teal |
| `monochrome` | Cool white / gray-blue |

Choose **Color palette → Apply colors** in the editor to preview one live,
then **Save config** to persist it. In the background service, the same operation
is available through `LoadPalette`; it also affects memory only until saved.

```sh
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.LoadPalette rose-quartz
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SaveConfig
```

To customize or add built-in palettes in a source checkout, edit the JSON files
in `palettes/`, extend the whitelist in `ThemeManager::paletteNames()` in
`src/theme.cpp`, and register the new file in `CMakeLists.txt`. This requires a
rebuild, while switching between compiled palettes works at runtime.

## Main knobs

- `aurora.sideHeight` defaults to **0.795** in the submitted configuration;
  adjust it separately from `aurora.height` (**0.19**) for shorter or taller side glow.
- `aurora.convexity` controls the upward dome in the middle of the screen.
- `aurora.archWidth` controls how broad the dome is.
- `aurora.density`, `sharpness`, `wave`, `drift` shape Silk's vertical threads.
- `aurora.colors` and `edgeColor` control the palette.
- `text.contrastStrength` controls the feathered dark veil behind the message.
- `text.contrastPadding`, `contrastFeather`, `contrastColor` control its extent,
  softness, and color. It is **not** an opaque text card.
- `layout.uiScale` scales text, orb, geometry offsets, and margins together
  (0.4–3.5). It does not scale the fullscreen shader itself.
- `text.anchor`: `top`, `middle`, `bottom`;
  `text.horizontalAnchor`: `left`, `center`, `right`.
- `orb.placement`: `above`, `below`, `left`, `right`, `independent`.

For illustration, a partial config override:

```json
{
  "aurora": {"sideHeight": 0.795, "height": 0.19, "convexity": 2.0},
  "text": {"contrastStrength": 0.54, "anchor": "bottom"},
  "layout": {"uiScale": 1.15},
  "orb": {"placement": "below"}
}
```

The editor exposes *all scalar and color-array entries* in the theme schema.
Numeric settings have sliders and editable numbers; color settings have hex
inputs and swatches. Some unusually large off-screen offset values are easier
to specify through the number input than by dragging a slider.

## D-Bus

The service is unchanged: `org.example.VoiceOverlay`, object
`/org/example/VoiceOverlay`, interface `org.example.VoiceOverlay1`.

```sh
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SetState listening
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SetMessage 'Testing Silk Studio'
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SetLevel 0.6
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SetOption aurora.sideHeight 0.2
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SetOption aurora.colors.0 '"#78ffd4"'
qdbus org.example.VoiceOverlay /org/example/VoiceOverlay org.example.VoiceOverlay1.SaveConfig
```

Existing `Reset`, `AppendMessage`, `ClearMessage`, `ReloadConfig`, `LoadPreset`, `LoadPalette`,
`GetConfigPath`, and `Ping` are still supported. New `SaveConfig` saves all
currently applied settings; `ResetTheme` previews the bundled defaults in
memory (use `SaveConfig` to persist). Color values can also be sent as bare
hex strings to `SetOption` if shell quoting is inconvenient.

## Editing the shader

The GLSL source is `shaders/aurora.frag`. `nix run .` recompiles the shader
when the file changes. Qt's shader compilation produces a `.qsb` resource at
`:/localvoice/shaders/aurora.frag.qsb`; uniform properties are declared in
`qml/Overlay.qml`. If the uniform block changes, update the QML properties
accordingly. The editor changes uniform values at runtime, but doesn't compile
new GLSL on the fly.

`nix run . -- --check-resources` checks packaged QML and shader resources
without starting a Wayland window. `./scripts/test-package.py` runs static
source checks. The QML module remains `LocalVoice.AuroraOverlayV3`, and the
runtime QML disk cache is disabled, to avoid the stale resource issue in
previous revisions.

### Build environment and limitations

The overlay compiles and its packaged resources are checked in Nix CI. It has
not been rendered in a live Plasma Wayland session in that environment. The
first `--editor` run should be used to verify the imported Qt Quick Controls
QML module, the shader rendering, and its GPU performance on the target host.

The overlay currently follows the primary screen. It is fullscreen but
click-through and reserves no panel space. The editor is a separate, ordinary
window; users running several screens may prefer moving that window to the
secondary screen. Qt Quick shader rendering is only active while the assistant
is visible. The systemd service is optional and should not run at the same time
as `nix run . -- --editor`.
