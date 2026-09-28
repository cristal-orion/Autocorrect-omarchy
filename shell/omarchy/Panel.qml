// Hallmark · component: control-panel · genre: modern-minimal · theme: Omarchy
// Native shell tokens; compact single-column controls; no page macrostructure.
// Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V3
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import qs.Ui as UI
import qs.Commons

UI.Panel {
    id: root
    moduleName: "michele.autocorrect"
    manageIpc: false
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    property var snapshot: ({connected: false, settings: {}, memory: null, service: {}})
    property bool loaded: false
    property bool pollFailed: false
    property string errorText: ""
    property string notice: ""
    property int generation: 0
    property int pollGeneration: 0
    property bool actionReply: false
    readonly property bool busy: actionProc.running
    readonly property bool online: snapshot.connected && !pollFailed
    readonly property string backend: decodeURIComponent(String(Qt.resolvedUrl("autocorrectctl")).replace(/^file:\/\//, ""))

    function refresh() {
        if (stateProc.running || actionProc.running) return
        pollGeneration = generation
        stateProc.running = true
    }
    function receive(raw, fromAction) {
        if (!fromAction && (pollGeneration !== generation || actionProc.running)) return
        var value
        try { value = JSON.parse(raw) }
        catch (error) { errorText = "Risposta del controller non valida. Premi Aggiorna."; if (!fromAction) pollFailed = true; return }
        if (!value.ok) { errorText = value.error || "Controller non disponibile. Premi Aggiorna."; if (!fromAction) pollFailed = true; return }
        if (pollFailed) errorText = ""
        pollFailed = false
        snapshot = value
        loaded = true
        if (fromAction) {
            errorText = ""
            notice = value.message || ""
            noticeTimer.restart()
            if (actionProc.command.indexOf("open-probe") >= 0) close()
        }
        if (!marginInput.activeFocus) marginInput.text = Number(value.settings.min_score_margin || 1.3).toFixed(2)
    }
    function act(args) {
        if (busy) return
        generation++
        actionReply = false
        errorText = ""
        notice = ""
        actionProc.command = ["timeout", "30", "python3", backend].concat(args)
        actionProc.running = true
    }
    function setOption(key, value) { act(["set", key, JSON.stringify(value)]) }
    function saveMargin() {
        if (busy) return
        var value = Number(marginInput.text.replace(",", "."))
        if (!isFinite(value) || value < 0.01 || value > 5) {
            errorText = "Il margine deve essere tra 0,01 e 5,00. Correggi il valore."
            return
        }
        if (value !== snapshot.settings.min_score_margin) setOption("min_score_margin", value)
    }
    onOpenedChanged: if (opened) refresh()
    Component.onCompleted: refresh()

    Timer { interval: root.opened ? 1500 : 10000; running: true; repeat: true; onTriggered: root.refresh() }
    Timer { id: noticeTimer; interval: 5000; onTriggered: root.notice = "" }
    Process {
        id: stateProc
        command: ["timeout", "8", "python3", root.backend, "status"]
        stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.receive(String(text), false) }
    }

    IpcHandler {
        target: "autocorrect-panel"
        enabled: button.QsWindow.window !== null && Quickshell.screens.length > 0
            && button.QsWindow.window.screen === Quickshell.screens[0]
        function inspect(): string {
            return JSON.stringify({opened: root.opened, connected: root.online, busy: root.busy,
                settings: root.snapshot.settings, error: root.errorText,
                geometry: {x: panel.cardOrigin.x, y: panel.cardOrigin.y, width: panel.contentWidth,
                    height: panel.contentHeight, screen: panel.screen ? panel.screen.name : ""}})
        }
    }
    Process {
        id: actionProc
        stdout: StdioCollector {
            waitForEnd: true
            onStreamFinished: { root.actionReply = true; root.receive(String(text), true) }
        }
        onExited: function(code, status) {
            Qt.callLater(function() {
                if (!root.actionReply) root.errorText = "Il controller non ha risposto. Premi Aggiorna."
                root.refresh()
            })
        }
    }

    UI.BarIconButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        text: "󰓆"
        active: root.loaded && root.online && root.snapshot.settings.correction_enabled
        tooltipText: "Autocorrect · " + (root.online ? "motore di prova pronto" : "motore non collegato")
        onPressed: function(mouseButton) { root.toggle() }
    }

    UI.KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: focusArea
        contentWidth: fittedContentWidth(Style.space(410))
        contentHeight: fittedContentHeight(content.implicitHeight, Style.space(780))
        FocusScope {
            id: focusArea
            anchors.fill: parent
            focus: true
            Keys.onEscapePressed: root.close()
            QQC.ScrollView {
                id: scroll
                anchors.fill: parent
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    id: content
                    width: scroll.availableWidth
                    spacing: Style.spacing.md
                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "Autocorrect"
                            color: Color.foreground
                            font.family: Style.font.family
                            font.pixelSize: Style.font.title
                            font.bold: true
                            Layout.fillWidth: true
                        }
                        UI.Button {
                            text: "Chiudi"
                            focusable: true
                            onClicked: root.close()
                            Accessible.name: text
                            Accessible.role: Accessible.Button
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.busy ? "Operazione in corso…" : (root.pollFailed ? "Stato non aggiornato" : (!root.loaded ? "Lettura dello stato…" :
                            root.online ? "Motore pronto · ambito: prova Fcitx" : (root.snapshot.service.active === "active" ? "Motore non raggiungibile" : "Motore spento")))
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        wrapMode: Text.WordWrap
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        UI.Button {
                            text: root.online ? "Ferma" : (root.snapshot.service.active === "active" ? "Riavvia" : "Avvia")
                            Layout.fillWidth: true
                            bordered: true; focusable: true
                            enabled: !root.busy
                            opacity: enabled ? 1 : 0.5
                            onClicked: root.act([root.online ? "stop" : (root.snapshot.service.active === "active" ? "restart" : "start")])
                            Accessible.name: text + " motore"
                            Accessible.role: Accessible.Button
                        }
                        UI.Button {
                            text: "Apri prova"
                            Layout.fillWidth: true
                            bordered: true; focusable: true
                            enabled: !root.busy
                            opacity: enabled ? 1 : 0.5
                            onClicked: root.act(["open-probe"])
                            Accessible.name: text
                            Accessible.role: Accessible.Button
                        }
                    }
                    ControlRow {
                        Layout.fillWidth: true
                        label: "Correzione automatica"; helper: "Sostituzioni allo spazio"
                        checked: !!root.snapshot.settings.correction_enabled
                        available: root.online; busy: root.busy
                        onRequested: value => root.setOption("correction_enabled", value)
                    }
                    ControlRow {
                        Layout.fillWidth: true
                        label: "Contesto"; helper: "Usa le parole precedenti"
                        checked: !!root.snapshot.settings.use_context
                        available: root.online && !!root.snapshot.capabilities.context; busy: root.busy
                        onRequested: value => root.setOption("use_context", value)
                    }
                    ControlRow {
                        Layout.fillWidth: true
                        label: "Memoria personale"; helper: "Impara dalle correzioni"
                        checked: !!root.snapshot.settings.learn_enabled
                        available: root.online && !!root.snapshot.capabilities.learning; busy: root.busy
                        onRequested: value => root.setOption("learn_enabled", value)
                    }
                    ControlRow {
                        Layout.fillWidth: true
                        label: "Suggerimenti"; helper: "Solo sulle astensioni"
                        checked: !!root.snapshot.settings.suggestions_enabled
                        available: root.online && !!root.snapshot.capabilities.learning; busy: root.busy
                        onRequested: value => root.setOption("suggestions_enabled", value)
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: width < Style.space(330) ? 1 : 2
                        columnSpacing: Style.spacing.md
                        rowSpacing: Style.spacing.md
                        UI.NumberField {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 1
                            label: "Frequenza minima"
                            value: root.snapshot.settings.min_frequency || 5000
                            from: 1000; to: 100000; stepSize: 1000
                            fieldWidth: width
                            enabled: root.online && !root.busy
                            opacity: enabled ? 1 : 0.5
                            onModified: value => root.setOption("min_frequency", value)
                            Component.onCompleted: field.contentItem.inputMethodHints = Qt.ImhFormattedNumbersOnly | Qt.ImhNoPredictiveText
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            Layout.preferredWidth: 1
                            spacing: Style.spacing.md
                            Text {
                                text: "Margine minimo"
                                color: Color.foreground
                                font.family: Style.font.family
                                font.pixelSize: Style.font.bodySmall
                            }
                            UI.TextField {
                                id: marginInput
                                Layout.fillWidth: true
                                text: "1.30"
                                enabled: root.online && !root.busy
                                opacity: enabled ? 1 : 0.5
                                inputMethodHints: Qt.ImhFormattedNumbersOnly | Qt.ImhNoPredictiveText
                                Accessible.name: "Margine minimo"
                                onAccepted: root.saveMargin()
                                onEditingFinished: root.saveMargin()
                            }
                        }
                    }
                    UI.PanelSeparator { Layout.fillWidth: true }
                    Text {
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.snapshot.memory ? (root.snapshot.memory.pair_count + " coppie · " +
                            root.snapshot.memory.confirmations + " conferme · " + root.snapshot.memory.rejections + " rifiuti") : "Memoria: —"
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        text: "Typo da dimenticare"
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        UI.TextField {
                            id: forgetInput
                            Layout.fillWidth: true
                            placeholderText: "pne"
                            inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                            Accessible.name: "Typo da dimenticare"
                            onAccepted: if (text.trim() && !root.busy) root.act(["forget", "--", text.trim()])
                        }
                        UI.Button {
                            text: "Dimentica"
                            focusable: true; bordered: true
                            enabled: !!forgetInput.text.trim() && !root.busy
                            opacity: enabled ? 1 : 0.5
                            onClicked: root.act(["forget", "--", forgetInput.text.trim()])
                            Accessible.name: "Dimentica il typo indicato"
                            Accessible.role: Accessible.Button
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        textFormat: Text.PlainText
                        text: root.errorText ? ("Errore: " + root.errorText) : root.snapshot.memory_error || root.notice
                        visible: text !== ""
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        wrapMode: Text.Wrap
                    }
                    UI.PanelSeparator { Layout.fillWidth: true }
                    Text {
                        Layout.fillWidth: true
                        text: "App da collaudare: BrowserOS, ZapFast, Slack.\nTerminale: solo chat, attivazione manuale da verificare.\nIl motore non è ancora collegato al Fcitx di sistema."
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.WordWrap
                    }
                    ControlRow {
                        Layout.fillWidth: true
                        label: "Avvio al login"; helper: "Avvia il motore in background"
                        checked: !!root.snapshot.service.autostart
                        available: root.loaded; busy: root.busy
                        onRequested: value => root.act(["autostart", value ? "true" : "false"])
                    }
                    UI.Button {
                        text: "Aggiorna"
                        focusable: true
                        enabled: !root.busy && !stateProc.running
                        opacity: enabled ? 1 : 0.5
                        onClicked: { root.errorText = ""; root.refresh() }
                        Accessible.name: "Aggiorna lo stato"
                        Accessible.role: Accessible.Button
                    }
                }
            }
        }
    }
}
