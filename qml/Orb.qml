import QtQuick

Item {
    id: assembly
    property var theme
    property real uiScale: 1.0
    property real seconds: 0
    property real level: 0
    property bool audioActive: false
    property bool processing: false
    property bool isError: false
    property bool active: false

    width: Math.max(180, theme.orb.glowSize + 55) * uiScale
    height: width
    scale: theme.orb.scale

    Rectangle {
        id: halo
        anchors.centerIn: parent
        width: (assembly.theme.orb.glowSize + assembly.level * 15) * assembly.uiScale
        height: width
        radius: width / 2
        color: assembly.theme.orb.glowColor
        opacity: assembly.theme.orb.glowOpacity
        SequentialAnimation on scale {
            running: assembly.active
            loops: Animation.Infinite
            NumberAnimation { from: 0.94; to: 1.13; duration: Math.max(200, assembly.theme.orb.pulseDurationMs) }
            NumberAnimation { from: 1.13; to: 0.94; duration: Math.max(200, assembly.theme.orb.pulseDurationMs) }
        }
    }

    Rectangle {
        id: sphere
        anchors.centerIn: parent
        width: (assembly.theme.orb.size + (assembly.audioActive ? assembly.level * assembly.theme.orb.audioExpand : 0)) * assembly.uiScale
        height: width
        radius: width / 2
        Behavior on width { NumberAnimation { duration: Math.max(0, assembly.theme.animation.levelSmoothMs) } }
        border.width: 1
        border.color: assembly.theme.orb.borderColor
        gradient: Gradient {
            GradientStop { position: 0.0; color: assembly.isError ? assembly.theme.orb.errorColors[0] : assembly.theme.orb.colors[0] }
            GradientStop { position: 0.52; color: assembly.isError ? assembly.theme.orb.errorColors[1] : assembly.theme.orb.colors[1] }
            GradientStop { position: 1.0; color: assembly.isError ? assembly.theme.orb.errorColors[2] : assembly.theme.orb.colors[2] }
        }

        // A translucent ring for processing. Never a solid white disc.
        Rectangle {
            anchors.centerIn: parent
            visible: !assembly.audioActive
            width: (assembly.theme.orb.processingRingSize + 4.0 * Math.sin(assembly.seconds * 2.0)) * assembly.uiScale
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: assembly.theme.orb.processingRingColor
            opacity: assembly.theme.orb.processingRingOpacity
        }

        Item {
            id: waveform
            anchors.centerIn: parent
            width: Math.max(30, sphere.width - 20 * assembly.uiScale)
            height: 36 * assembly.uiScale
            clip: true
            visible: assembly.audioActive
            readonly property int barCount: Math.max(1, Math.min(15, assembly.theme.orb.waveformBarCount))
            Row {
                anchors.centerIn: parent
                spacing: 2
                Repeater {
                    model: waveform.barCount
                    delegate: Item {
                        width: Math.max(2, (waveform.width - 2 * (waveform.barCount - 1)) / waveform.barCount)
                        height: 36 * assembly.uiScale
                        readonly property real modulation: 0.36 + 0.64 * Math.abs(Math.sin(index * 1.3 + assembly.seconds * 2.1))
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width
                            height: Math.min(34 * assembly.uiScale, (5 + assembly.level * assembly.theme.orb.waveformGain * (11 + 18 * modulation)) * assembly.uiScale)
                            radius: 2
                            color: assembly.theme.orb.waveformColor
                            Behavior on height { NumberAnimation { duration: 75 } }
                        }
                    }
                }
            }
        }
    }
}
