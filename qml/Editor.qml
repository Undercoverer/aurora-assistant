import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A normal input-capable window. The overlay remains a separate transparent
// layer-shell surface in the same process and shares themeManager in real time.
ApplicationWindow {
    id: studio
    width: 1030
    height: 810
    minimumWidth: 700
    minimumHeight: 560
    visible: true
    title: "Aurora Palette Studio — live theme editor"
    color: "#101624"

    property var data: themeManager.settings
    property var schema: ({})
    property string notice: "Move a slider to update the overlay immediately. Save to keep changes."
    property bool demoLevels: false
    property real demoClock: 0
    readonly property var sections: [
        {key:"aurora", title:"Aurora curtains, convex arc and edge wrap"},
        {key:"vignette", title:"Vignette"},
        {key:"text", title:"Text, contrast and placement"},
        {key:"orb", title:"Orb appearance and placement"},
        {key:"animation", title:"Animation timings"},
        {key:"layout", title:"Global UI scale and opacity"}
    ]
    readonly property var enums: ({
        "text.anchor":["top","middle","bottom"],
        "text.horizontalAnchor":["left","center","right"],
        "orb.placement":["above","below","left","right","independent"],
        "orb.anchor":["top","middle","bottom"],
        "orb.horizontalAnchor":["left","center","right"]
    })
    // Slider bounds can be edited here without changing runtime JSON or C++.
    readonly property var ranges: ({
        "aurora.speed":[0,3,0.01], "aurora.height":[0.01,0.8,0.005],
        "aurora.sideHeight":[0.01,0.8,0.005], "aurora.sideWidth":[0.01,0.5,0.005],
        "aurora.brightness":[0,3,0.01], "aurora.density":[2,180,1],
        "aurora.sharpness":[1,20,0.1], "aurora.wave":[0,0.2,0.002],
        "aurora.drift":[-0.5,0.5,0.005], "aurora.baseGlow":[0,1.5,0.01],
        "aurora.edgeBoost":[0,3,0.01], "aurora.edgeColorMix":[0,1,0.01],
        "aurora.offsetX":[-1,1,0.005], "aurora.offsetY":[-0.5,0.5,0.005],
        "aurora.convexity":[0,2,0.01], "aurora.archWidth":[0.06,0.8,0.01],
        "vignette.strength":[0,0.95,0.01], "vignette.innerRadius":[0,1,0.01],
        "vignette.softness":[0.01,1,0.01],
        "text.size":[10,80,1], "text.statusSize":[8,50,1],
        "text.scale":[0.4,3,0.01], "text.maxWidth":[180,1800,10],
        "text.maxHeight":[50,700,5], "text.maxLines":[1,15,1],
        "text.lineHeight":[0.8,2,0.01], "text.spacing":[0,50,1],
        "text.offsetX":[-1200,1200,5], "text.offsetY":[-800,800,5],
        "text.anchorMargin":[0,850,5], "text.screenMargin":[0,200,1],
        "text.contrastStrength":[0,0.95,0.01],
        "text.contrastPadding":[0,2,0.01], "text.contrastFeather":[0.05,2,0.01],
        "orb.size":[20,250,1], "orb.scale":[0.4,3,0.01],
        "orb.audioExpand":[0,120,1], "orb.glowSize":[30,400,1],
        "orb.glowOpacity":[0,1,0.01], "orb.pulseDurationMs":[150,10000,50],
        "orb.offsetX":[-1200,1200,5], "orb.offsetY":[-800,800,5],
        "orb.processingRingSize":[0,100,1],
        "orb.processingRingOpacity":[0,1,0.01],
        "orb.waveformBarCount":[1,15,1], "orb.waveformGain":[0,4,0.01],
        "orb.gap":[-100,350,1], "orb.anchorMargin":[0,850,5],
        "orb.screenMargin":[0,200,1], "orb.noTextLift":[0,300,1],
        "animation.fadeMs":[0,3000,25], "animation.moveMs":[0,3000,25],
        "animation.levelSmoothMs":[0,1000,10],
        "animation.caretBlinkMs":[100,3000,25],
        "layout.uiScale":[0.4,3.5,0.01], "layout.opacity":[0,1,0.01]
    })

    Component.onCompleted: {
        schema = JSON.parse(JSON.stringify(themeManager.settings))
    }
    function entries(section) {
        const result = []
        const obj = schema[section] || {}
        const keys = Object.keys(obj)
        for (let i=0;i<keys.length;i++) {
            const path = section + "." + keys[i]
            const val = obj[keys[i]]
            if (Array.isArray(val)) {
                for (let n=0;n<val.length;n++) {
                    result.push({path:path+"."+n, name:keys[i]+" ["+n+"]"})
                }
            } else if (typeof val !== "object") {
                result.push({path:path,name:keys[i]})
            }
        }
        return result
    }
    function lookup(path) {
        const parts=path.split(".")
        let value=data
        for (let i=0;i<parts.length;i++) {
            if (value===undefined || value===null) return undefined
            value=value[parts[i]]
        }
        return value
    }
    function bounds(path) {
        if (ranges[path] !== undefined) return ranges[path]
        return [0,100,1]
    }
    function assign(path,value) {
        if (!themeManager.setOption(path,JSON.stringify(value)))
            notice="Could not set "+path+" (value/type rejected)"
        else
            notice="Preview updated: "+path+" — unsaved"
    }
    function pretty(name) {
        return name.replace(/([a-z])([A-Z])/g,"$1 $2").replace(/^./,c=>c.toUpperCase())
    }

    Timer {
        interval: 100
        running: studio.demoLevels && (assistant.state === "listening" || assistant.state === "speaking")
        repeat: true
        onTriggered: {
            studio.demoClock += 0.35
            assistant.setLevel(Math.min(1,Math.max(0,0.44+0.3*Math.sin(studio.demoClock)+0.18*Math.sin(studio.demoClock*2.7))))
        }
    }

    header: ToolBar {
        implicitHeight: 181
        background: Rectangle { color: "#192237" }
        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            spacing: 5
            RowLayout {
                spacing: 8
                Label { text: "AURORA STUDIO"; color: "#ccefff"; font.pixelSize: 19; font.bold: true }
                Item { Layout.fillWidth: true }
                Button { text: "Your baseline"; onClicked: { themeManager.resetToDefaults(); studio.notice="Your submitted settings previewed — click Save to persist" } }
                Button { text: "Reload disk"; onClicked: { themeManager.reloadConfig(); studio.notice="Reloaded runtime config" } }
                Button { text: "Save config"; highlighted: true; onClicked: studio.notice=themeManager.saveConfig() ? "Saved to " + themeManager.configPath : "Save failed" }
            }
            RowLayout {
                spacing: 7
                Label { text: "Preview:"; color: "#dce5f8" }
                Repeater {
                    model: ["wake","listening","transcribing","thinking","speaking","success","idle"]
                    Button {
                        required property string modelData
                        text: modelData
                        onClicked: {
                            assistant.setState(modelData)
                            if (modelData === "idle") assistant.setMessage("")
                            else if (modelData === "wake" || modelData === "listening") assistant.setMessage("")
                            else assistant.setMessage("The aurora is responding to your voice. Here's how a streamed answer would appear.")
                        }
                    }
                }
                CheckBox { text: "Animate level"; checked: studio.demoLevels; onToggled: studio.demoLevels=checked }
                Item { Layout.fillWidth: true }
            }
            RowLayout {
                Label { text: "Full preset:"; color: "#dce5f8" }
                ComboBox { id: presets; model: ["northern-lights","pink-horizon","cyber-blue"] }
                Button { text: "Load preview"; onClicked: studio.notice=themeManager.loadPreset(presets.currentText) ? "Preset applied in memory — unsaved" : "Unknown preset" }
                Label { Layout.fillWidth: true; text: studio.notice; color: "#a7bcd6"; elide: Text.ElideRight }
            }
            RowLayout {
                spacing: 8
                Label { text: "Color palette:"; color: "#dce5f8" }
                ComboBox {
                    id: paletteSelector
                    Layout.preferredWidth: 200
                    model: themeManager.paletteNames()
                }
                Button {
                    text: "Apply colors"
                    onClicked: studio.notice = themeManager.applyPalette(paletteSelector.currentText)
                        ? "Applied colors: " + paletteSelector.currentText + " — layout unchanged, unsaved"
                        : "Could not apply palette"
                }
                Repeater {
                    model: 4
                    Rectangle {
                        required property int index
                        readonly property var palette: themeManager.palettePreview(paletteSelector.currentText)
                        width: 25; height: 25; radius: 5
                        color: palette.aurora ? palette.aurora.colors[index] : "transparent"
                        border.color: "#61728f"; border.width: 1
                    }
                }
                Label { text: "Colors only — no layout changes"; color: "#9cb5d2" }
                Item { Layout.fillWidth: true }
            }
        }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        anchors.margins: 12
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded
        Column {
            width: scroll.availableWidth
            spacing: 12
            Repeater {
                model: studio.sections
                Frame {
                    id: sectionFrame
                    required property var modelData
                    width: parent.width
                    padding: 15
                    background: Rectangle {
                        color: "#192438"
                        radius: 12
                        border.color: "#2c3d58"
                    }
                    Column {
                        width: parent.width
                        spacing: 5
                        Label {
                            text: sectionFrame.modelData.title
                            font.bold: true
                            font.pixelSize: 17
                            color: "#daf0ff"
                            bottomPadding: 8
                        }
                        Repeater {
                            model: studio.entries(sectionFrame.modelData.key)
                            Item {
                                id: optionRow
                                required property var modelData
                                width: parent.width
                                height: 40
                                readonly property string optionPath: modelData.path
                                readonly property var current: studio.lookup(optionPath)
                                RowLayout {
                                    anchors.fill: parent
                                    spacing: 10
                                    Label {
                                        text: studio.pretty(optionRow.modelData.name)
                                        color: "#d6e0f2"
                                        Layout.preferredWidth: 200
                                        elide: Text.ElideRight
                                    }
                                    Loader {
                                        Layout.fillWidth: true
                                        sourceComponent: studio.enums[optionRow.optionPath] !== undefined ? choiceEdit
                                            : typeof(optionRow.current) === "number" ? numberEdit
                                            : typeof(optionRow.current) === "boolean" ? boolEdit
                                            : (typeof(optionRow.current) === "string" && optionRow.current.startsWith("#")) ? colorEdit : stringEdit
                                        onLoaded: item.optionPath=optionRow.optionPath
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: numberEdit
        RowLayout {
            id: num
            property string optionPath: ""
            property var range: studio.bounds(optionPath)
            spacing: 8
            Slider {
                Layout.fillWidth: true
                from: num.range[0]; to: num.range[1]; stepSize: num.range[2]
                value: Number(studio.lookup(num.optionPath)) || 0
                onMoved: studio.assign(num.optionPath, value)
            }
            TextField {
                Layout.preferredWidth: 104
                text: String(studio.lookup(num.optionPath) ?? "")
                selectByMouse: true
                onEditingFinished: {
                    const v = Number(text)
                    if (text.trim() !== "" && Number.isFinite(v)) studio.assign(num.optionPath,v)
                }
            }
        }
    }
    Component {
        id: colorEdit
        RowLayout {
            id: col
            property string optionPath: ""
            Rectangle {
                width: 35; height: 26; radius: 5
                color: studio.lookup(col.optionPath) || "transparent"
                border.width: 1; border.color: "#8290a8"
            }
            TextField {
                Layout.fillWidth: true
                text: String(studio.lookup(col.optionPath) ?? "")
                placeholderText: "#RRGGBB"
                onEditingFinished: {
                    if (/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(text)) studio.assign(col.optionPath,text)
                    else studio.notice="Expected #RRGGBB or #RRGGBBAA for " + col.optionPath
                }
            }
        }
    }
    Component {
        id: boolEdit
        Item {
            id: yesno
            property string optionPath: ""
            Switch {
                anchors.verticalCenter: parent.verticalCenter
                checked: Boolean(studio.lookup(yesno.optionPath))
                onToggled: studio.assign(yesno.optionPath,checked)
            }
        }
    }
    Component {
        id: choiceEdit
        RowLayout {
            id: choice
            property string optionPath: ""
            ComboBox {
                Layout.fillWidth: true
                model: studio.enums[choice.optionPath] || []
                currentIndex: Math.max(0,model.indexOf(studio.lookup(choice.optionPath)))
                onActivated: studio.assign(choice.optionPath,currentText)
            }
        }
    }
    Component {
        id: stringEdit
        RowLayout {
            id: str
            property string optionPath: ""
            TextField {
                Layout.fillWidth: true
                text: String(studio.lookup(str.optionPath) ?? "")
                onEditingFinished: studio.assign(str.optionPath,text)
            }
        }
    }
}
