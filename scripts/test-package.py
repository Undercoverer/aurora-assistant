#!/usr/bin/env python3
"""Source-level checks. Run before building; graphical Qt rendering is separate."""
from pathlib import Path
import json
import re

base = Path(__file__).resolve().parents[1]
for path in list((base / "config").glob("*.json")) + list((base / "presets").glob("*.json")):
    loaded = json.loads(path.read_text())
    assert isinstance(loaded, dict), path
    print("JSON OK:", path.relative_to(base))

shader = (base / "shaders/aurora.frag").read_text()
qml = (base / "qml/Overlay.qml").read_text()
block = re.search(r"layout\(std140, binding = 0\) uniform buf\s*\{(.*?)\}", shader, re.S)
assert block, "Missing std140 uniform block"
uniforms = re.findall(r"(?:float|vec2|vec4|mat4)\s+(\w+)\s*;", block.group(1))
for name in uniforms:
    if not name.startswith("qt_"):
        assert re.search(r"property\s+(?:real|color|point)\s+" + name + r"\s*:", qml), f"No ShaderEffect property for {name}"
print("Uniform names declared on same QML ShaderEffect:", len(uniforms) - 2)
assert 'objectName: "auroraShader"' in qml
assert 'AURORA_CONFIGURABLE_V3_RESOURCE_MARKER' in qml
assert 'running: caretHolder.visible' in (base / "qml/MessageBlock.qml").read_text()
cmake = (base / "CMakeLists.txt").read_text()
assert 'qt_add_qml_module' in cmake and 'qt_add_shaders' in cmake
assert 'qml/resources.qrc' not in cmake
config = json.loads((base / "config/default.json").read_text())
assert config["text"]["anchor"] in ("top", "middle", "bottom")
assert config["text"]["horizontalAnchor"] in ("left", "center", "right")
assert config["orb"]["placement"] in ("above", "below", "left", "right", "independent")
main_cpp = (base / "src/main.cpp").read_text()
assert "findVisualItem(view.rootObject()" in main_cpp
assert "parent->childItems()" in main_cpp
assert 'FATAL: ShaderEffect object not found in loaded QML' not in main_cpp
print("Visual-tree shader diagnostic: OK")
print("Layout configuration + resource scheme: OK")

# Guard against old QML modules causing silently stale graphics.
assert 'URI LocalVoice.AuroraOverlayV3' in cmake
assert 'loadFromModule("LocalVoice.AuroraOverlayV3", "Overlay")' in main_cpp
assert 'qputenv("QML_DISABLE_DISK_CACHE", "1")' in main_cpp
assert 'return 11;' in main_cpp
print("Unique QML module + cache isolation: OK")

assert 'qml/Editor.qml' in cmake
assert 'property real uiScale:' in qml
assert 'property point textCenter:' in qml
assert 'contrastStrength' in (base / 'config/default.json').read_text()
assert 'resetToDefaults()' in (base / 'src/theme.cpp').read_text()
print("Silk Studio shader, editor and scale configuration: OK")

# Color-only palettes must never overwrite tuned geometry, animation or DPI settings.
allowed = {
    "aurora": {"colors", "edgeColor"},
    "orb": {"colors", "borderColor", "glowColor", "processingRingColor", "waveformColor"},
    "text": {"color", "statusColor", "caretColor", "contrastColor"},
    "vignette": {"color"},
}
all_palettes = list((base / "palettes").glob("*.json"))
assert len(all_palettes) == 10, "Expected all ten compiled color palettes"
import copy
for file in all_palettes:
    theme = json.loads((base / "config/default.json").read_text())
    trial = copy.deepcopy(theme)
    data = json.loads(file.read_text())
    assert set(data).issubset(allowed)
    for section, overrides in data.items():
        assert set(overrides).issubset(allowed[section]), file
        for key, value in overrides.items():
            if isinstance(value, list):
                assert len(value) == len(theme[section][key])
                assert all(re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", v) for v in value)
            else:
                assert re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value)
            trial[section][key] = value
    for section in trial:
        for key in trial[section]:
            if key not in allowed.get(section, set()):
                assert trial[section][key] == theme[section][key], (file, section, key)
    assert f"palettes/{file.stem}.json" in cmake
assert "Q_INVOKABLE bool applyPalette" in (base / "src/theme.h").read_text()
assert "PALETTE APPLIED:" in (base / "src/theme.cpp").read_text()
assert "LoadPalette" in (base / "src/assistant.cpp").read_text()
assert "themeManager.applyPalette" in (base / "qml/Editor.qml").read_text()
assert "Color palette:" in (base / "qml/Editor.qml").read_text()
print("10 embedded color palettes and non-color preservation: OK")
