// Eight-state native preview. Run with the shell's Commons/Ui imports available.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import Quickshell
import qs.Commons

ShellRoot {
    FloatingWindow {
        id: window
        title: "Autocorrect · anteprima controlli"
        implicitWidth: Number(Quickshell.env("AUTOCORRECT_PREVIEW_WIDTH")) || 414
        implicitHeight: 900
        color: Color.popups.background
        Item {
        id: canvas
        anchors.fill: parent
        Rectangle { anchors.fill: parent; color: Color.popups.background }
        ScrollView {
            anchors.fill: parent
            contentWidth: availableWidth
            ColumnLayout {
                id: content
                width: parent.width
                spacing: Style.spacing.md
                Repeater {
                    model: ["default", "hover", "focus", "pressed", "disabled", "loading", "error", "success"]
                    ColumnLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        Text {
                            text: modelData
                            color: Color.foreground
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }
                        ControlRow {
                            Layout.fillWidth: true
                            label: "Contesto"
                            helper: "Usa le parole precedenti"
                            previewState: modelData
                            checked: modelData === "success"
                            errorText: modelData === "error" ? "Modifica non riuscita" : ""
                            successText: modelData === "success" ? "Salvato" : ""
                        }
                    }
                }
            }
        }
        }
        Timer {
            interval: 1200
            running: Quickshell.env("AUTOCORRECT_PREVIEW_IMAGE") !== ""
            onTriggered: {
                canvas.grabToImage(function(result) {
                    var saved = result.saveToFile(Quickshell.env("AUTOCORRECT_PREVIEW_IMAGE"))
                    console.log("ControlsPreview", JSON.stringify({saved: saved, windowWidth: window.width, contentWidth: content.width, states: 8,
                        foreground: String(Color.foreground), background: String(Color.popups.background)}))
                    Qt.quit()
                })
            }
        }
    }
}
