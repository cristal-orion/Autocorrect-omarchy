// Dedicated Qt fields for exercising the actual Fcitx input-method module.
#include <QApplication>
#include <QFile>
#include <QInputMethodEvent>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
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
    window.setWindowTitle(realEngine ? "Autocorrect - testo reale (SymSpell + Hunspell)" : "Autocorrect Fcitx Probe Qt");
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
    layout->addWidget(paragraph);
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
        QFile file(status);
        if (file.open(QIODevice::WriteOnly)) file.write(QJsonDocument(object).toJson());
    });
    timer.start(50);
    return app.exec();
}
