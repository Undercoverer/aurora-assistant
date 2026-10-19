import QtQuick

Item {
    id: block
    property var theme
    property real uiScale: 1.0
    property string message: ""
    property string statusText: ""
    property string state: "idle"
    property bool isError: false
    readonly property bool hasText: message.length > 0
    readonly property bool streaming: hasText && ["thinking", "transcribing", "speaking"].includes(state)
    implicitHeight: content.implicitHeight
    clip: true

    Column {
        id: content
        anchors.top: parent.top
        width: parent.width
        spacing: block.theme.text.spacing * block.uiScale

        Text {
            width: parent.width
            visible: block.theme.text.showStatus
            text: block.statusText
            font.family: block.theme.text.fontFamily
            font.pixelSize: Math.max(8, Math.round(block.theme.text.statusSize * block.theme.text.scale * block.uiScale))
            font.weight: Font.DemiBold
            color: block.isError ? block.theme.text.errorColor : block.theme.text.statusColor
            opacity: block.hasText ? 0.74 : 1.0
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            width: parent.width
            visible: block.hasText
            text: block.message
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            maximumLineCount: block.theme.text.maxLines
            elide: Text.ElideLeft
            lineHeight: block.theme.text.lineHeight
            font.family: block.theme.text.fontFamily
            font.pixelSize: Math.max(8, Math.round(block.theme.text.size * block.theme.text.scale * block.uiScale))
            font.weight: Font.Medium
            color: block.theme.text.color
            horizontalAlignment: Text.AlignHCenter
        }
        Item {
            id: caretHolder
            width: parent.width
            height: 3 * block.uiScale
            visible: block.streaming
            Rectangle {
                id: caret
                anchors.centerIn: parent
                width: 14 * block.uiScale
                height: 3 * block.uiScale
                radius: 1.5
                color: block.theme.text.caretColor
                SequentialAnimation on opacity {
                    running: caretHolder.visible
                    loops: Animation.Infinite
                    NumberAnimation { from: 1; to: 0.12; duration: Math.max(100, block.theme.animation.caretBlinkMs) }
                    NumberAnimation { from: 0.12; to: 1; duration: Math.max(100, block.theme.animation.caretBlinkMs) }
                }
            }
        }
    }
}
