cmake_minimum_required(VERSION 3.24)
project(aurora-voice-overlay VERSION 2.3.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.7 REQUIRED COMPONENTS Core Gui Quick Qml DBus ShaderTools)
find_package(LayerShellQt REQUIRED)
qt_standard_project_setup(REQUIRES 6.7)

qt_add_executable(aurora-voice-overlay
    src/main.cpp
    src/assistant.h src/assistant.cpp
    src/theme.h src/theme.cpp
)

# There is exactly one QML module; do not add a second resources.qrc.
foreach(qml_file Overlay Orb MessageBlock Editor)
    set_source_files_properties(qml/${qml_file}.qml PROPERTIES QT_RESOURCE_ALIAS ${qml_file}.qml)
endforeach()
qt_add_qml_module(aurora-voice-overlay
    URI LocalVoice.AuroraOverlayV3
    VERSION 2.0
    QML_FILES
        qml/Overlay.qml
        qml/Orb.qml
        qml/MessageBlock.qml
        qml/Editor.qml
    NO_CACHEGEN
)

# qsb emits :/localvoice/shaders/aurora.frag.qsb.
qt_add_shaders(aurora-voice-overlay aurora_line_shader
    PREFIX "/localvoice/shaders"
    BASE "${CMAKE_CURRENT_SOURCE_DIR}/shaders"
    FILES shaders/aurora.frag
)

# Embedded defaults make the executable independent of its current working dir.
qt_add_resources(aurora-voice-overlay "aurora_default_themes"
    PREFIX "/localvoice"
    BASE "${CMAKE_CURRENT_SOURCE_DIR}"
    FILES
        config/default.json
        presets/northern-lights.json
        presets/pink-horizon.json
        presets/cyber-blue.json
        palettes/aqua-violet.json
        palettes/northern-jade.json
        palettes/rose-quartz.json
        palettes/solar-flare.json
        palettes/deep-ocean.json
        palettes/ultraviolet.json
        palettes/arctic-mist.json
        palettes/ember-noir.json
        palettes/lime-electric.json
        palettes/monochrome.json
)

target_link_libraries(aurora-voice-overlay PRIVATE
    Qt6::Core Qt6::Gui Qt6::Quick Qt6::Qml Qt6::DBus
    LayerShellQt::Interface
)
install(TARGETS aurora-voice-overlay RUNTIME DESTINATION bin)
