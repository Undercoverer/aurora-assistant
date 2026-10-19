import QtQuick

// AURORA_CONFIGURABLE_V3_RESOURCE_MARKER — loaded by loadFromModule.
Item {
    id: root
    width: 1280
    height: 800
    clip: true

    readonly property var theme: themeManager.settings
    readonly property real uiScale: Math.max(0.4, Math.min(3.5, root.theme.layout.uiScale || 1.0))
    readonly property bool active: assistant.state !== "idle"
    readonly property bool hasText: assistant.message.length > 0
    readonly property bool audioActive: assistant.state === "listening" || assistant.state === "speaking"
    readonly property bool processing: ["transcribing", "thinking", "executing"].includes(assistant.state)
    readonly property bool errorState: assistant.state === "error"
    property real seconds: 0
    property real smoothLevel: assistant.level

    Behavior on smoothLevel { NumberAnimation { duration: Math.max(0, root.theme.animation.levelSmoothMs) } }
    opacity: active ? theme.layout.opacity : 0
    Behavior on opacity { NumberAnimation { duration: Math.max(0, root.theme.animation.fadeMs) } }

    function statusLabel() {
        switch (assistant.state) {
        case "wake": return "Ready"
        case "listening": return "Listening…"
        case "transcribing": return "Transcribing…"
        case "thinking": return "Thinking…"
        case "executing": return "Running command…"
        case "speaking": return "Speaking…"
        case "success": return "Done"
        case "error": return "Something went wrong"
        default: return ""
        }
    }

    // Coordinates use logical Wayland pixels, relative to the overlay's screen.
    function anchoredX(mode, itemWidth, margin) {
        switch (mode) {
        case "left": return margin
        case "right": return width - itemWidth - margin
        default: return (width - itemWidth) / 2
        }
    }
    function anchoredY(mode, itemHeight, margin) {
        switch (mode) {
        case "top": return margin
        case "middle": return (height - itemHeight) / 2
        default: return height - itemHeight - margin
        }
    }

    NumberAnimation on seconds {
        running: root.active
        from: 0
        to: 10000
        duration: 10000000
        loops: Animation.Infinite
    }

    // Uniforms live directly on this ShaderEffect. This avoids the previous
    // missing-property warnings caused by the separate theme-bearing wrapper.
    // Each declared name matches a float/vec4 in shaders/aurora.frag.
    ShaderEffect {
        id: aurora
        objectName: "auroraShader"
        anchors.fill: parent
        visible: root.active
        blending: true
        property real time: root.seconds
        property real energy: root.audioActive ? root.smoothLevel : (root.processing ? 0.20 : 0.10)
        property real danger: root.errorState ? 1.0 : 0.0
        property real speed: root.theme.aurora.speed
        property real heightFactor: root.theme.aurora.height
        property real sideHeight: root.theme.aurora.sideHeight
        property real sideWidth: root.theme.aurora.sideWidth
        property real brightness: root.theme.aurora.brightness
        property real density: root.theme.aurora.density
        property real sharpness: root.theme.aurora.sharpness
        property real wave: root.theme.aurora.wave
        property real drift: root.theme.aurora.drift
        property real baseGlow: root.theme.aurora.baseGlow
        property real edgeBoost: root.theme.aurora.edgeBoost
        property real edgeColorMix: root.theme.aurora.edgeColorMix
        property real offsetX: root.theme.aurora.offsetX
        property real offsetY: root.theme.aurora.offsetY
        property real vignetteStrength: root.theme.vignette.strength
        property real vignetteRadius: root.theme.vignette.innerRadius
        property real vignetteSoftness: root.theme.vignette.softness
        property real convexity: root.theme.aurora.convexity
        property real archWidth: root.theme.aurora.archWidth
        property real textContrast: root.theme.text.contrastStrength * (root.hasText ? 1.0 : 0.48)
        property real textPadding: root.theme.text.contrastPadding
        property real textFeather: root.theme.text.contrastFeather
        property point textCenter: Qt.point((messageBlock.x + messageBlock.width / 2) / Math.max(1,root.width),
                                                  (messageBlock.y + messageBlock.height / 2) / Math.max(1,root.height))
        property point textExtent: Qt.point(messageBlock.width / Math.max(1,root.width),
                                                  Math.max(messageBlock.height,45*root.uiScale) / Math.max(1,root.height))
        property color textContrastColor: root.theme.text.contrastColor
        property color colorA: root.theme.aurora.colors[0]
        property color colorB: root.theme.aurora.colors[1]
        property color colorC: root.theme.aurora.colors[2]
        property color colorD: root.theme.aurora.colors[3]
        property color edgeColor: root.theme.aurora.edgeColor
        property color errorColor: root.theme.aurora.errorColor
        property color vignetteColor: root.theme.vignette.color
        fragmentShader: "qrc:/localvoice/shaders/aurora.frag.qsb"
        onStatusChanged: {
            if (status === ShaderEffect.Error)
                console.error("AURORA SHADER ERROR:", log)
            else if (status === ShaderEffect.Compiled)
                console.info("AURORA SHADER COMPILED; speed =", speed, "height =", heightFactor)
        }
    }

    // Text can anchor independently to screen top/middle/bottom and
    // left/center/right. The item's height follows its actual text content.
    MessageBlock {
        id: messageBlock
        theme: root.theme
        uiScale: root.uiScale
        state: assistant.state
        statusText: root.statusLabel()
        message: assistant.message
        isError: root.errorState
        width: Math.min(Math.max(150, root.width - 2 * root.theme.text.screenMargin * root.uiScale), root.theme.text.maxWidth * root.uiScale)
        height: Math.min(root.theme.text.maxHeight * root.uiScale, implicitHeight)
        x: root.anchoredX(root.theme.text.horizontalAnchor, width, root.theme.text.screenMargin * root.uiScale) + root.theme.text.offsetX * root.uiScale
        y: root.anchoredY(root.theme.text.anchor, height, root.theme.text.anchorMargin * root.uiScale) + root.theme.text.offsetY * root.uiScale
        Behavior on x { NumberAnimation { duration: Math.max(0, root.theme.animation.moveMs); easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: Math.max(0, root.theme.animation.moveMs); easing.type: Easing.OutCubic } }
    }

    // Orb placement relative to the text, or independently screen-anchored.
    Orb {
        id: orb
        theme: root.theme
        uiScale: root.uiScale
        seconds: root.seconds
        level: root.smoothLevel
        audioActive: root.audioActive
        processing: root.processing
        isError: root.errorState
        active: root.active

        readonly property string placement: root.theme.orb.placement
        readonly property real gap: root.theme.orb.gap * root.uiScale
        readonly property real ownX: root.anchoredX(root.theme.orb.horizontalAnchor, width, root.theme.orb.screenMargin * root.uiScale)
        readonly property real ownY: root.anchoredY(root.theme.orb.anchor, height, root.theme.orb.anchorMargin * root.uiScale)
        x: ((placement === "above" || placement === "below")
               ? messageBlock.x + (messageBlock.width - width) / 2
               : placement === "left" ? messageBlock.x - width - gap
               : placement === "right" ? messageBlock.x + messageBlock.width + gap
               : ownX) + root.theme.orb.offsetX * root.uiScale
        y: ((placement === "above") ? messageBlock.y - height - gap
               : placement === "below" ? messageBlock.y + messageBlock.height + gap
               : (placement === "left" || placement === "right")
                   ? messageBlock.y + (messageBlock.height - height) / 2
               : ownY) + root.theme.orb.offsetY * root.uiScale - (root.hasText ? 0 : root.theme.orb.noTextLift * root.uiScale)

        Behavior on x { NumberAnimation { duration: Math.max(0, root.theme.animation.moveMs); easing.type: Easing.OutCubic } }
        Behavior on y { NumberAnimation { duration: Math.max(0, root.theme.animation.moveMs); easing.type: Easing.OutCubic } }
    }
}
