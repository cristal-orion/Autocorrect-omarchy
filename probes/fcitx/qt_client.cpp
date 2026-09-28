// Dedicated Qt fields for exercising the actual Fcitx input-method module.
#include "socket_client.h"
#include <QApplication>
#include <QCheckBox>
#include <QDoubleSpinBox>
#include <QFile>
#include <QHBoxLayout>
#include <QInputMethodEvent>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QLocale>
#include <QMap>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSaveFile>
#include <QSpinBox>
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
    auto *paragraphLabel = new QLabel("&Testo multilinea (Alt+T):");
    paragraphLabel->setBuddy(paragraph);
    layout->addWidget(paragraphLabel);
    layout->addWidget(paragraph);
    auto *decisionLabel = new QLabel("Ultima analisi del motore: in attesa di una parola seguita da spazio.");
    decisionLabel->setTextFormat(Qt::PlainText);
    decisionLabel->setWordWrap(true);
    decisionLabel->setTextInteractionFlags(Qt::TextSelectableByMouse);
    if (realEngine) layout->addWidget(decisionLabel);
    else decisionLabel->setParent(&window);
    decisionLabel->setVisible(realEngine);
    const auto diagnosticsPath = qEnvironmentVariable("AUTOCORRECT_PROBE_DIAGNOSTICS");
    const auto settingsPath = qEnvironmentVariable("AUTOCORRECT_PROBE_SETTINGS");
    auto *margin = new QDoubleSpinBox(&window);
    margin->setRange(0.01, 5.0);
    margin->setDecimals(2);
    margin->setSingleStep(0.1);
    margin->setValue(1.3);
    margin->setKeyboardTracking(false);
    margin->setInputMethodHints(Qt::ImhNoPredictiveText);
    auto *marginLabel = new QLabel("&Margine minimo (Alt+M):", &window);
    marginLabel->setBuddy(margin);
    auto *resetMargin = new QPushButton("Ripristina 1,30", &window);
    auto *frequency = new QSpinBox(&window);
    const QLocale italian(QLocale::Italian, QLocale::Italy);
    frequency->setLocale(italian);
    frequency->setGroupSeparatorShown(true);
    frequency->setRange(1000, 100000);
    frequency->setSingleStep(1000);
    bool validInitialFrequency = false;
    const auto initialFrequency = qEnvironmentVariable("AUTOCORRECT_PROBE_INITIAL_FREQUENCY").toInt(&validInitialFrequency);
    frequency->setValue(validInitialFrequency ? initialFrequency : 100000);
    frequency->setKeyboardTracking(false);
    frequency->setInputMethodHints(Qt::ImhNoPredictiveText);
    auto *frequencyLabel = new QLabel("&Frequenza minima (Alt+F):", &window);
    frequencyLabel->setBuddy(frequency);
    auto *baselineFrequency = new QPushButton("&100.000 (baseline)", &window);
    auto *trialFrequency = new QPushButton("Prova &5.000", &window);
    const bool hasContext = !qEnvironmentVariable("AUTOCORRECT_PROBE_CONTEXT_CORPUS").isEmpty();
    if (hasContext) {
        window.setWindowTitle("Autocorrect - contesto Leipzig, da 3 lettere");
        instructions->setText("Contesto Leipzig sperimentale: scrivi una frase. Spazio corregge; Backspace annulla.\n"
            "I typo di 3 e 4 lettere richiedono evidenza nel corpus. Alt+C attiva o disattiva il contesto.");
    }
    auto *contextToggle = new QCheckBox("&Contesto Leipzig sperimentale (Alt+C): include typo da 3 lettere", &window);
    contextToggle->setEnabled(hasContext);
    contextToggle->setChecked(hasContext);
    const bool hasLearning = !qEnvironmentVariable("AUTOCORRECT_PROBE_LEARNING").isEmpty();
    const auto feedbackPath = qEnvironmentVariable("AUTOCORRECT_PROBE_FEEDBACK");
    auto *learningToggle = new QCheckBox("Memoria personale attiva (Alt+&L)", &window);
    learningToggle->setEnabled(hasLearning);
    learningToggle->setChecked(hasLearning);
    auto *suggestionsToggle = new QCheckBox("&Suggerimenti opzionali (Alt+S): clic o F1–F3 solo quando il motore si astiene", &window);
    suggestionsToggle->setEnabled(hasLearning);
    suggestionsToggle->setChecked(hasLearning && !qEnvironmentVariable("AUTOCORRECT_PROBE_CANDIDATES").isEmpty());
    auto *forgetWord = new QLineEdit(&window);
    forgetWord->setInputMethodHints(Qt::ImhNoPredictiveText);
    forgetWord->setPlaceholderText("es. pne; Invio per dimenticare");
    auto *forgetLabel = new QLabel("Typo da &dimenticare (Alt+D):", &window);
    forgetLabel->setBuddy(forgetWord);
    auto *forgetButton = new QPushButton("Dimentica", &window);
    auto *learningStatus = new QLabel("Memoria pronta. Le correzioni manuali si apprendono quando termini la parola con spazio.", &window);
    learningStatus->setTextFormat(Qt::PlainText);
    learningStatus->setWordWrap(true);
    learningStatus->setTextInteractionFlags(Qt::TextSelectableByMouse);
    if (hasLearning) {
        window.setWindowTitle("Autocorrect - apprendimento personale");
        instructions->setText("Spazio corregge; Backspace annulla una sostituzione.\n"
            "Correggi una parola con Backspace o modificandola al suo interno, poi premi spazio per imparare. "
            "La memoria resta dopo il riavvio. I suggerimenti sono opzionali.");
    }
    auto *policyStatus = new QLabel("Soglie valide dalla prossima parola, solo in questa sessione. "
        "Per confrontare le frequenze lascia il margine a 1,30. Hunspell attivo nel launcher core.", &window);
    policyStatus->setWordWrap(true);
    if (realEngine && !settingsPath.isEmpty()) {
        auto *controls = new QHBoxLayout;
        controls->addWidget(marginLabel);
        controls->addWidget(margin);
        controls->addWidget(resetMargin);
        layout->addLayout(controls);
        auto *frequencyControls = new QHBoxLayout;
        frequencyControls->addWidget(frequencyLabel);
        frequencyControls->addWidget(frequency);
        frequencyControls->addWidget(baselineFrequency);
        frequencyControls->addWidget(trialFrequency);
        layout->addLayout(frequencyControls);
        layout->addWidget(contextToggle);
        if (hasLearning) {
            layout->addWidget(learningToggle);
            layout->addWidget(suggestionsToggle);
            auto *forgetControls = new QHBoxLayout;
            forgetControls->addWidget(forgetLabel);
            forgetControls->addWidget(forgetWord);
            forgetControls->addWidget(forgetButton);
            layout->addLayout(forgetControls);
            layout->addWidget(learningStatus);
        }
        layout->addWidget(policyStatus);
        auto saveSettings = [=] {
            QSaveFile file(settingsPath);
            const auto bytes = QJsonDocument(QJsonObject{{"min_score_margin", margin->value()},
                {"min_frequency", frequency->value()}, {"use_context", contextToggle->isChecked()},
                {"learn_enabled", learningToggle->isChecked()}, {"suggestions_enabled", suggestionsToggle->isChecked()}}).toJson();
            const bool saved = file.open(QIODevice::WriteOnly)
                && file.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner)
                && file.write(bytes) == bytes.size() && file.commit();
            policyStatus->setText(saved
                ? QString("Salvato per i prossimi token: frequenza %1, margine %2. "
                          "L'ultima analisi mostra le soglie effettivamente usate dal motore.")
                    .arg(italian.toString(frequency->value())).arg(italian.toString(margin->value(), 'f', 2))
                : "Errore di salvataggio: il motore conserva le soglie precedenti.");
        };
        QObject::connect(margin, &QDoubleSpinBox::valueChanged, [=](double) { saveSettings(); });
        QObject::connect(frequency, &QSpinBox::valueChanged, [=](int) { saveSettings(); });
        QObject::connect(contextToggle, &QCheckBox::toggled, [=](bool) { saveSettings(); });
        QObject::connect(learningToggle, &QCheckBox::toggled, [=](bool) { saveSettings(); });
        QObject::connect(suggestionsToggle, &QCheckBox::toggled, [=](bool) { saveSettings(); });
        QObject::connect(resetMargin, &QPushButton::clicked, [=] { margin->setValue(1.3); });
        QObject::connect(baselineFrequency, &QPushButton::clicked, [=] { frequency->setValue(100000); });
        QObject::connect(trialFrequency, &QPushButton::clicked, [=] { frequency->setValue(5000); });
    } else {
        margin->hide();
        marginLabel->hide();
        resetMargin->hide();
        frequency->hide();
        frequencyLabel->hide();
        baselineFrequency->hide();
        trialFrequency->hide();
        contextToggle->hide();
        policyStatus->hide();
    }
    if (!hasLearning) {
        learningToggle->hide(); suggestionsToggle->hide(); forgetWord->hide();
        forgetLabel->hide(); forgetButton->hide(); learningStatus->hide();
    }
    auto forget = [=] {
        const auto word = forgetWord->text().trimmed();
        if (word.isEmpty()) return;
        const auto request = QJsonDocument(QJsonObject{{"op", "forget"}, {"token", word}, {"context", "text"}}).toJson(QJsonDocument::Compact);
        const auto socket = qEnvironmentVariable("AUTOCORRECT_PROBE_ENGINE_SOCKET").toUtf8();
        const auto raw = sendProbePacket(socket.constData(), std::string(request.constData(), request.size()));
        const auto response = QJsonDocument::fromJson(QByteArray::fromStdString(raw)).object()["feedback"].toObject();
        learningStatus->setText(response["status"].toString() == "forgotten"
            ? QString("Dimenticato %1: rimossi %2 eventi. Torna al testo con Alt+T.").arg(word).arg(response["forgotten_events"].toInt())
            : "Dimenticanza non confermata dal motore; riprova.");
    };
    QObject::connect(forgetButton, &QPushButton::clicked, forget);
    QObject::connect(forgetWord, &QLineEdit::returnPressed, forget);
    const QMap<QString, QString> explanations{
        {"ambiguous", "Margine insufficiente fra i candidati: conserva l'originale"},
        {"known_word", "Voce presente nella lista di frequenze"},
        {"valid_word", "Forma riconosciuta da Hunspell"},
        {"high_margin", "Propone una correzione: soglie superate"},
        {"context_high_margin", "Propone una correzione con evidenza dal contesto"},
        {"context_ambiguous", "Il contesto non separa abbastanza i candidati"},
        {"context_low_evidence", "Troppo poche occorrenze del candidato nel contesto"},
        {"context_weak_rerank", "Cambio di candidato: servono più occorrenze con entrambe le parole precedenti"},
        {"context_short_target", "Il candidato è troppo corto per correggere un typo di tre lettere"},
        {"context_unsupported_short_edit", "Il ripiego sugli articoli richiede una vocale interna mancante"},
        {"personal_correction", "Correzione appresa da un tuo gesto esplicito"},
        {"personal_suggestion", "Preferenza personale: suggerimento senza sostituzione automatica"},
        {"personal_ambiguous", "Conferme personali in conflitto: conserva l'originale"},
        {"personal_rejected", "Correzione rifiutata: conserva l'originale"},
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
    window.resize(900, 700);
    window.show();
    if (realEngine && qEnvironmentVariable("AUTOCORRECT_PROBE_TEST").isEmpty()) {
        paragraph->setFocus();
    } else {
        normal->setFocus();
    }
    const auto status = qEnvironmentVariable("AUTOCORRECT_PROBE_STATUS");
    qint64 lastFeedbackTime = 0;
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, [&] {
        if (!diagnosticsPath.isEmpty()) {
            QFile diagnosticFile(diagnosticsPath);
            if (diagnosticFile.open(QIODevice::ReadOnly)) {
                const auto data = QJsonDocument::fromJson(diagnosticFile.readAll()).object();
                if (data.contains("original")) {
                    const auto reason = data["reason"].toString();
                    const auto personal = data["personal"].toObject();
                    QStringList candidates;
                    for (const auto &value : data["candidates"].toArray()) {
                        const auto candidate = value.toObject();
                        candidates << QString("%1 (distanza %2, frequenza %3)")
                            .arg(candidate["term"].toString()).arg(candidate["distance"].toInt())
                            .arg(italian.toString(candidate["frequency"].toInteger()));
                    }
                    QString text = QString("Ultima analisi del motore: %1 → %2\n%3 [%4]")
                        .arg(data["original"].toString(), data["output"].toString(), explanations.value(reason, reason), reason);
                    if (!candidates.isEmpty()) text += "\nCandidati: " + candidates.join(" · ");
                    if (data["score_margin"].isDouble()) {
                        text += QString("\nMargine: %1 — richiesto: %2 (score euristico)")
                            .arg(data["score_margin"].toDouble(), 0, 'f', 3)
                            .arg(data["required_margin"].toDouble(), 0, 'f', 3);
                    } else if (data["required_margin"].isDouble()) {
                        text += QString("\nMargine richiesto: %1 (score euristico)")
                            .arg(data["required_margin"].toDouble(), 0, 'f', 3);
                    }
                    if (data["required_frequency"].isDouble()) {
                        text += QString("\nFrequenza minima %1: ").arg(personal["used"].toBool() ? "baseline" : "usata")
                            + italian.toString(data["required_frequency"].toInteger());
                    }
                    const auto context = data["context"].toObject();
                    if (personal["used"].toBool()) {
                        text += QString("\nMemoria personale: %1 | conferme: %2 | rifiuti: %3 | usi nel contesto: %4")
                            .arg(personal["target"].toString()).arg(personal["confirmations"].toInt())
                            .arg(personal["rejections"].toInt()).arg(personal["context_uses"].toInt());
                    } else if (context["enabled"].toBool()) {
                        if (context["used"].toBool()) {
                            QStringList words;
                            for (const auto &word : context["previous_words"].toArray()) words << word.toString();
                            const bool articleEvidence = context["evidence_source"].toString() == "article_family";
                            text += QString("\nContesto %1: %2 | %3: %4 / minime: %5")
                                .arg(articleEvidence ? "letto" : "usato", words.join(" "),
                                     articleEvidence ? "occorrenze aggregate" : "occorrenze")
                                .arg(context["evidence"].toInt()).arg(context["required_evidence"].toInt());
                            if (articleEvidence) {
                                QStringList articles;
                                for (const auto &article : context["article_family"].toArray()) articles << article.toString();
                                text += "\nEvidenza aggregata dagli articoli: " + articles.join(", ");
                            } else if (context["evidence_source"].toString() == "exact_trigram") {
                                text += "\nEvidenza: trigramma esatto";
                            }
                            text += QString("\nRanking contestuale; candidato prima al posto %1. Margine baseline: %2")
                                .arg(context["baseline_rank"].toInt()).arg(data["baseline_required_margin"].toDouble(), 0, 'f', 3);
                        } else {
                            text += "\nContesto attivo; per questa parola vale la decisione di base.";
                        }
                    } else if (hasContext) {
                        text += "\nContesto disattivato per questa decisione.";
                    }
                    decisionLabel->setText(text);
                }
            }
        }
        if (hasLearning) {
            QFile feedbackFile(feedbackPath);
            if (feedbackFile.open(QIODevice::ReadOnly)) {
                const auto data = QJsonDocument::fromJson(feedbackFile.readAll()).object();
                if (data["time_ns"].toInteger() > lastFeedbackTime) {
                    lastFeedbackTime = data["time_ns"].toInteger();
                    const auto feedback = data["feedback"].toObject();
                    const auto kind = feedback["status"].toString();
                    if (kind == "learned_pair" || kind == "learned_use" || kind == "rejected") {
                        learningStatus->setText(QString("%1: %2 → %3. Conferme attive: %4; rifiuti: %5.")
                            .arg(kind == "learned_pair" ? "Coppia appresa" : (kind == "learned_use" ? "Solo uso contestuale appreso" : "Rifiuto registrato"),
                                 feedback["original"].toString(), feedback["target"].toString())
                            .arg(feedback["confirmations"].toInt()).arg(feedback["rejections"].toInt()));
                    } else if (kind == "forgotten") {
                        learningStatus->setText(QString("Dimenticato %1: rimossi %2 eventi.")
                            .arg(feedback["original"].toString()).arg(feedback["forgotten_events"].toInt()));
                    } else {
                        learningStatus->setText("Esito feedback: " + kind);
                    }
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
        object["margin"] = QJsonObject{{"value", margin->value()}, {"focus", margin->hasFocus()},
            {"text", policyStatus->text()}};
        object["frequency"] = QJsonObject{{"value", frequency->value()}, {"focus", frequency->hasFocus()},
            {"text", policyStatus->text()}};
        object["context"] = QJsonObject{{"available", hasContext}, {"enabled", contextToggle->isChecked()}};
        object["learning"] = QJsonObject{{"available", hasLearning}, {"enabled", learningToggle->isChecked()},
            {"suggestions", suggestionsToggle->isChecked()}, {"text", learningStatus->text()}, {"forget_focus", forgetWord->hasFocus()}};
        QFile file(status);
        if (file.open(QIODevice::WriteOnly)) file.write(QJsonDocument(object).toJson());
    });
    timer.start(50);
    return app.exec();
}
