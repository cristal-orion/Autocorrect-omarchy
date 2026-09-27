// Dedicated Qt fields for exercising the actual Fcitx input-method module.
#include <QApplication>
#include <QFile>
#include <QInputMethodEvent>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMap>
#include <QPlainTextEdit>
#include <QTextEdit>
#include <QTimer>
#include <QVBoxLayout>

class Field : public QLineEdit {
public:
    QString preedit;
    int imeEvents = 0;
    void inputMethodEvent(QInputMethodEvent *event) override {
        preedit = event->preeditString();
        ++imeEvents;
        QLineEdit::inputMethodEvent(event);
    }
};

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setApplicationName("autocorrect-probe-qt");
    QWidget window;
    const bool realEngine = !qEnvironmentVariable("AUTOCORRECT_PROBE_ENGINE_SOCKET").isEmpty();
    window.setWindowTitle(realEngine ? "Autocorrect - testo reale e diagnostica" : "Autocorrect Fcitx Probe Qt");
    auto *layout = new QVBoxLayout(&window);
    auto *instructions = new QLabel(realEngine
        ? "Motore reale conservativo: scrivi nel paragrafo. Spazio corregge; Backspace annulla.\n"
          "Mantiene parole valide e casi ambigui. L'incolla non corregge tutto il testo retroattivamente."
        : "Fcitx probe: quesot + spazio; Backspace annulla. Tab cambia campo.");
    instructions->setWordWrap(true);
    layout->addWidget(instructions);
    auto *normal = new Field;
    normal->setPlaceholderText("Testo normale");
    layout->addWidget(normal);
    auto *password = new Field;
    password->setPlaceholderText("Password di prova (solo testo sintetico)");
    password->setEchoMode(QLineEdit::Password);
    layout->addWidget(password);
    auto *code = new Field;
    code->setPlaceholderText("NoPredictiveText / NoSpellCheck");
    code->setInputMethodHints(Qt::ImhNoPredictiveText);
    layout->addWidget(code);
    auto *second = new Field;
    second->setPlaceholderText("Secondo campo normale");
    layout->addWidget(second);
    auto *paragraph = new QPlainTextEdit;
    paragraph->setPlaceholderText("Scrivi qui un testo di più righe. Esempio: oggi provo quesot sistema qaundo scrivo un progeto interesasnte.");
    paragraph->setTabChangesFocus(true);
    const auto initialText = qEnvironmentVariable("AUTOCORRECT_PROBE_INITIAL_TEXT");
    if (!initialText.isEmpty()) {
        paragraph->setPlainText(initialText);
        paragraph->moveCursor(QTextCursor::End);
    }
    layout->addWidget(paragraph);
    auto *decisionLabel = new QLabel("Ultima analisi del motore: in attesa di una parola seguita da spazio.");
    decisionLabel->setTextFormat(Qt::PlainText);
    decisionLabel->setWordWrap(true);
    decisionLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    if (realEngine) layout->addWidget(decisionLabel);
    else decisionLabel->setParent(&window);
    decisionLabel->setVisible(realEngine);
    const auto diagnosticsPath = qEnvironmentVariable("AUTOCORRECT_PROBE_DIAGNOSTICS");
    const QMap<QString, QString> explanations{
        {"ambiguous", "Margine insufficiente fra i candidati: conserva l'originale"},
        {"known_word", "Voce presente nella lista di frequenze"},
        {"valid_word", "Forma riconosciuta da Hunspell"},
        {"high_margin", "Propone una correzione: soglie superate"},
        {"edit_distance", "Il primo candidato richiede troppe modifiche"},
        {"low_frequency", "Il primo candidato ha frequenza troppo bassa"},
        {"short_word", "Parola troppo corta per la sostituzione automatica"},
        {"no_candidate", "Nessun candidato entro la distanza di ricerca"},
        {"protected_word", "Voce del glossario protetto"},
        {"protected_candidate", "Il primo candidato è una voce protetta"},
        {"capitalized_or_mixed_case", "Maiuscole conservate"},
        {"apostrophe_requires_context", "Apostrofo: richiede contesto"},
        {"possible_elision", "Possibile elisione: richiede contesto"},
        {"non_word", "Token strutturato o non alfabetico"}};
    window.resize(850, 620);
    window.show();
    if (realEngine && qEnvironmentVariable("AUTOCORRECT_PROBE_TEST").isEmpty()) {
        paragraph->setFocus();
    } else {
        normal->setFocus();
    }
    const auto status = qEnvironmentVariable("AUTOCORRECT_PROBE_STATUS");
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, [&] {
        if (!diagnosticsPath.isEmpty()) {
            QFile diagnosticFile(diagnosticsPath);
            if (diagnosticFile.open(QIODevice::ReadOnly)) {
                const auto data = QJsonDocument::fromJson(diagnosticFile.readAll()).object();
                if (data.contains("original")) {
                    const auto reason = data["reason"].toString();
                    QStringList candidates;
                    for (const auto &value : data["candidates"].toArray()) {
                        const auto candidate = value.toObject();
                        candidates << QString("%1 (distanza %2)").arg(candidate["term"].toString()).arg(candidate["distance"].toInt());
                    }
                    QString text = QString("Ultima analisi del motore: %1 → %2\n%3 [%4]")
                        .arg(data["original"].toString(), data["output"].toString(), explanations.value(reason, reason), reason);
                    if (!candidates.isEmpty()) text += "\nCandidati: " + candidates.join(" · ");
                    if (data["score_margin"].isDouble()) {
                        text += QString("\nMargine: %1 — richiesto: %2 (score euristico)")
                            .arg(data["score_margin"].toDouble(), 0, 'f', 3)
                            .arg(data["required_margin"].toDouble(), 0, 'f', 3);
                    }
                    decisionLabel->setText(text);
                }
            }
        }
        if (status.isEmpty()) return;
        QJsonObject object;
        auto field = [](Field *widget) {
            return QJsonObject{{"text", widget->text()}, {"preedit", widget->preedit},
                               {"cursor", widget->cursorPosition()}, {"focus", widget->hasFocus()},
                               {"ime_events", widget->imeEvents}};
        };
        object["normal"] = field(normal);
        object["password"] = field(password);
        object["code"] = field(code);
        object["second"] = field(second);
        object["paragraph"] = QJsonObject{{"text", paragraph->toPlainText()},
            {"cursor", paragraph->textCursor().position()}, {"focus", paragraph->hasFocus()}};
        object["decision"] = QJsonObject{{"text", decisionLabel->text()}};
        QFile file(status);
        if (file.open(QIODevice::WriteOnly)) file.write(QJsonDocument(object).toJson());
    });
    timer.start(50);
    return app.exec();
}
