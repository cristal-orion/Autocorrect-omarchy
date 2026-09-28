// Hallmark · component: toggle-row · genre: modern-minimal · theme: Omarchy
// States: default, hover, focus, pressed, disabled, loading, error, success.
// Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V3
import QtQuick
import qs.Ui as UI
import qs.Commons

UI.BorderSurface {
    id: root
    property string label: ""
    property bool checked: false
    property bool available: true
    property bool busy: false
    property string helper: ""
    property string errorText: ""
    property string successText: ""
    property string previewState: ""
    property color foreground: Color.foreground
    property color accent: Color.accent
    readonly property bool hot: mouse.containsMouse || previewState === "hover"
    readonly property bool focused: activeFocus || previewState === "focus"
    readonly property bool pressed: mouse.pressed || previewState === "pressed"
    readonly property string detail: errorText ? "Errore: " + errorText :
        (busy || previewState === "loading" ? "Applicazione…" : successText || helper)
    signal requested(bool value)

    enabled: available && !busy && previewState !== "disabled" && previewState !== "loading"
    opacity: available && previewState !== "disabled" ? 1 : 0.5
    activeFocusOnTab: true
    implicitWidth: Style.space(280)
    implicitHeight: Math.max(Style.space(54), content.implicitHeight + Style.spacing.lg * 2)
    radius: Style.cornerRadius
    color: pressed ? Style.pressedFillFor(foreground, accent) : Style.controlFill(focused, hot, foreground, accent)
    borderSpec: Border.controlSpec(focused || errorText ? "focus" : (hot ? "hover-cursor" : "normal"), foreground, accent)
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.description: detail
    Accessible.checked: checked
    Accessible.onToggleAction: if (enabled) requested(!checked)
    Keys.onReturnPressed: if (enabled) requested(!checked)
    Keys.onEnterPressed: if (enabled) requested(!checked)
    Keys.onSpacePressed: if (enabled) requested(!checked)

    Row {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Style.spacing.rowPaddingX
        anchors.rightMargin: Style.spacing.rowPaddingX
        spacing: Style.spacing.rowPaddingX
        Column {
            width: parent.width - track.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.spacing.xs
            Text {
                width: parent.width
                text: root.label
                textFormat: Text.PlainText
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: root.detail
                textFormat: Text.PlainText
                color: root.foreground
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                wrapMode: Text.WordWrap
            }
        }
        UI.ToggleSwitch {
            id: track
            checked: root.checked
            interactive: false
            foreground: root.foreground
            accent: root.accent
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.requested(!root.checked)
    }
}
