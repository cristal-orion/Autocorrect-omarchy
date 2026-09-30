// Isolated Fcitx probe: fixed replacements or a bounded request to the real core.
#include "engine_client.h"
#include "edit_tracker.h"
#include <fcitx/addonfactory.h>
#include <fcitx/addonmanager.h>
#include <fcitx/candidatelist.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/inputcontextproperty.h>
#include <fcitx/inputmethodengine.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <fcitx-utils/utf8.h>
#include <cstdlib>
#include <iostream>
#include <map>
#include <string>
#include <functional>

namespace {
const std::map<std::string, std::string> replacements{
    {"quesot", "questo"}, {"qaundo", "quando"}, {"domnai", "domani"}};

std::string correction(const std::string &token, const std::string &previous = {}) {
    if (std::getenv("AUTOCORRECT_PROBE_ENGINE_SOCKET")) {
        return queryEngine(token, previous).output;
    }
    const auto found = replacements.find(token);
    return found == replacements.end() ? token : found->second;
}

bool separator(char character) {
    return character == ' ' || character == '\n' || character == '\r' || character == '\t';
}

bool closingPunctuation(const fcitx::Key &key) {
    const auto text = fcitx::Key::keySymToUTF8(key.sym());
    return text.size() == 1 && std::string(",.;:!?").find(text[0]) != std::string::npos
        && !key.states().testAny(fcitx::KeyStates(fcitx::KeyState::Ctrl) | fcitx::KeyState::Alt | fcitx::KeyState::Super);
}

struct State : fcitx::InputContextProperty {
    std::string composing;
    std::string original;
    std::string replacement;
    std::string expectedText;
    unsigned expectedCursor = 0;
    bool waitingForSurrounding = false;
    bool bypassWord = false;
    bool suppressNextSpace = false;
    EditTracker edit;
    std::string undoPrevious, undoFeedbackId;
    // After an undo, the rejection is only learned if the user keeps the
    // original with Space; editing, typing or punctuation discard it.
    bool rejectPending = false;
    std::string rejectOriginal, rejectTarget, rejectPrevious, rejectUndoOf;
    std::string pendingFeedbackId, pendingOriginal, pendingTarget, pendingPrevious;
    std::string choiceText, choiceBeforeText, choiceOriginal, choicePrevious;
    unsigned choiceCursor = 0;
    bool choiceReady = false;
    std::vector<std::string> choices;

    void clearUndo() {
        original.clear();
        replacement.clear();
        expectedText.clear();
        expectedCursor = 0;
        waitingForSurrounding = false;
        undoPrevious.clear();
        undoFeedbackId.clear();
    }
};

class FeedbackCandidate : public fcitx::CandidateWord {
public:
    FeedbackCandidate(const std::string &text, std::function<void(fcitx::InputContext *)> callback)
        : CandidateWord(fcitx::Text(text)), callback_(std::move(callback)) {}
    void select(fcitx::InputContext *ic) const override {
        auto callback = callback_; // The callback may destroy the candidate list.
        callback(ic);
    }
private:
    std::function<void(fcitx::InputContext *)> callback_;
};

bool blocked(fcitx::InputContext *ic) {
    // Desktop trials opt in one application at a time. Unknown application
    // identities stay excluded; isolated toolkit probes leave this unset.
    if (const char *program = std::getenv("AUTOCORRECT_PROBE_ALLOWED_PROGRAM")) {
        if (!*program || ic->program() != program) return true;
        // Wayland exposes spellcheck as a positive hint, not NoSpellCheck.
        // Require it in the desktop trial so code/editors opting out stay intact.
        if (ic->frontendName() == "wayland_v2" &&
            !ic->capabilityFlags().test(fcitx::CapabilityFlag::SpellCheck)) return true;
    }
    auto flags = ic->capabilityFlags();
    return flags.testAny(fcitx::CapabilityFlags(fcitx::CapabilityFlag::PasswordOrSensitive) |
                         fcitx::CapabilityFlag::Terminal |
                         fcitx::CapabilityFlag::Disable |
                         fcitx::CapabilityFlag::NoSpellCheck |
                         fcitx::CapabilityFlag::Url |
                         fcitx::CapabilityFlag::Email);
}

bool surroundingUsable(fcitx::InputContext *ic) {
    const auto &text = ic->surroundingText();
    return ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText) &&
           text.isValid() && text.cursor() == text.anchor();
}

std::vector<fcitx::Key> selectionKeys(fcitx::InputContext *ic) {
    const auto *program = std::getenv("AUTOCORRECT_PROBE_ALLOWED_PROGRAM");
    if (program && *program && ic->program() == program) {
        return {fcitx::Key(FcitxKey_1, fcitx::KeyState::Alt),
                fcitx::Key(FcitxKey_2, fcitx::KeyState::Alt),
                fcitx::Key(FcitxKey_3, fcitx::KeyState::Alt)};
    }
    return {fcitx::Key(FcitxKey_F1), fcitx::Key(FcitxKey_F2), fcitx::Key(FcitxKey_F3)};
}

std::size_t cursorByte(fcitx::InputContext *ic) {
    return fcitx::utf8::ncharByteLength(ic->surroundingText().text().begin(),
                                      ic->surroundingText().cursor());
}

// The restored original still sits whole right before the caret.
bool originalBeforeCursor(fcitx::InputContext *ic, const std::string &original) {
    if (original.empty() || !surroundingUsable(ic)) return false;
    const auto &text = ic->surroundingText().text();
    const auto byte = cursorByte(ic);
    return byte >= original.size() && text.compare(byte - original.size(), original.size(), original) == 0
        && (byte == original.size() || separator(text[byte - original.size() - 1]));
}

void diagnostic(fcitx::InputContext *ic, const char *event) {
    // No text or key contents: logs identify only protocol/capability outcomes.
    std::cerr << "autocorrect-probe event=" << event << " program=" << ic->program()
              << " frontend=" << ic->frontend()
              << " preedit=" << ic->capabilityFlags().test(fcitx::CapabilityFlag::Preedit)
              << " surrounding=" << surroundingUsable(ic)
              << " valid=" << ic->surroundingText().isValid()
              << " cursor=" << ic->surroundingText().cursor()
              << " anchor=" << ic->surroundingText().anchor()
              << " blocked=" << blocked(ic) << '\n';
}
} // namespace

class ProbeEngine : public fcitx::InputMethodEngine {
public:
    explicit ProbeEngine(fcitx::Instance *instance) : instance_(instance) {
        instance_->inputContextManager().registerProperty("autocorrect-probe-state", &factory_);
        surroundingWatcher_ = instance_->watchEvent(
            fcitx::EventType::InputContextSurroundingTextUpdated,
            fcitx::EventWatcherPhase::PostInputMethod, [this](fcitx::Event &event) {
                auto *ic = static_cast<fcitx::InputContextEvent &>(event).inputContext();
                acknowledgeWayland(ic);
                auto *state = ic->propertyFor(&factory_);
                if (blocked(ic) || !ic->hasFocus()) { *state = State{}; return; }
                if (surroundingUsable(ic)) {
                    observeEdit(ic, state);
                    confirmSelection(ic, state, false);
                    if (!state->choices.empty()) {
                        const bool matches = ic->surroundingText().text() == state->choiceText
                            && ic->surroundingText().cursor() == state->choiceCursor;
                        if (matches) state->choiceReady = true;
                        else if (state->choiceReady || ic->surroundingText().text() != state->choiceBeforeText) clearChoices(ic, state);
                    }
                }
                // Some clients do not report initially empty surrounding text.
                // Capture the post-commit snapshot only before any next edit key.
                if (!state->waitingForSurrounding || blocked(ic) || !surroundingUsable(ic)) {
                    return;
                }
                const auto byte = cursorByte(ic);
                const auto &text = ic->surroundingText().text();
                if (byte >= state->replacement.size() &&
                    text.substr(byte - state->replacement.size(), state->replacement.size()) == state->replacement) {
                    state->expectedText = text;
                    state->expectedCursor = ic->surroundingText().cursor();
                    state->waitingForSurrounding = false;
                    diagnostic(ic, "undo-snapshot-received");
                }
            });
        cursorWatcher_ = instance_->watchEvent(fcitx::EventType::InputContextCursorRectChanged,
            fcitx::EventWatcherPhase::PostInputMethod, [this](fcitx::Event &event) {
                acknowledgeWayland(static_cast<fcitx::InputContextEvent &>(event).inputContext());
            });
        focusWatcher_ = instance_->watchEvent(fcitx::EventType::InputContextFocusIn,
            fcitx::EventWatcherPhase::PostInputMethod, [this](fcitx::Event &event) {
                auto *ic = static_cast<fcitx::InputContextEvent &>(event).inputContext();
                const auto *program = std::getenv("AUTOCORRECT_PROBE_ALLOWED_PROGRAM");
                if (std::getenv("AUTOCORRECT_PROBE_AUTO_ACTIVATE") && program && *program
                    && ic->program() == program && ic->frontendName() == "wayland_v2"
                    && ic->hasFocus() && instance_->inputMethod(ic) != "autocorrect-probe-surrounding") {
                    // Change only this application context, not the group or
                    // the user's keyboard state in terminals and other apps.
                    instance_->setCurrentInputMethod(ic, "autocorrect-probe-surrounding", true);
                }
            });
    }

    void activate(const fcitx::InputMethodEntry &, fcitx::InputContextEvent &event) override {
        diagnostic(event.inputContext(), "activate");
        acknowledgeWayland(event.inputContext());
    }

    void reset(const fcitx::InputMethodEntry &, fcitx::InputContextEvent &event) override {
        auto *ic = event.inputContext();
        auto *state = ic->propertyFor(&factory_);
        // GTK resets its IM around Backspace and caret navigation. Preserve
        // only a compatible, user-key-driven edit, never an undo/choice.
        // Focus/field changes and external text changes still invalidate it.
        const bool preserveEdit = event.type() == fcitx::EventType::InputContextReset
            && ic->hasFocus() && !blocked(ic) && state->edit.active && surroundingUsable(ic)
            && state->edit.target(ic->surroundingText().text()).has_value();
        EditTracker edit;
        if (preserveEdit) edit = std::move(state->edit);
        *state = State{};
        if (preserveEdit) state->edit = std::move(edit);
        ic->inputPanel().reset();
        ic->updatePreedit();
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
    }

    void deactivate(const fcitx::InputMethodEntry &entry, fcitx::InputContextEvent &event) override {
        auto *ic = event.inputContext();
        auto *state = ic->propertyFor(&factory_);
        // Fcitx already commits client preedit on focus-out by default.
        if (event.type() != fcitx::EventType::InputContextFocusOut && !blocked(ic)) {
            const auto text = state->composing;
            state->composing.clear();
            if (!text.empty()) {
                ic->commitString(text);
            }
        }
        reset(entry, event);
    }

    void keyEvent(const fcitx::InputMethodEntry &entry, fcitx::KeyEvent &event) override {
        if (event.isRelease()) {
            return;
        }
        auto *ic = event.inputContext();
        auto *state = ic->propertyFor(&factory_);
        const bool preedit = entry.uniqueName() == "autocorrect-probe-preedit";
        if (blocked(ic)) {
            reset(entry, event);
            return;
        }
        if (preedit && !ic->capabilityFlags().test(fcitx::CapabilityFlag::Preedit)) {
            diagnostic(ic, "no-client-preedit");
            return;
        }
        const auto key = event.key();
        if (key.isModifier()) {
            return;
        }
        if (!preedit) {
            confirmSelection(ic, state, true);
            if (surroundingUsable(ic)) observeEdit(ic, state);
            const auto choices = selectionKeys(ic);
            for (int i = 0; i < 3; ++i) {
                if (key.check(choices[i]) && selectChoice(ic, state, i)) {
                    event.filterAndAccept();
                    return;
                }
            }
            clearChoices(ic, state);
        }
        if (!preedit && state->rejectPending && !key.check(FcitxKey_space)) {
            state->rejectPending = false;
            // Backspace removed the space to add punctuation: put the
            // correction back and let the punctuation key through.
            if (closingPunctuation(key) && originalBeforeCursor(ic, state->rejectOriginal)) {
                const auto count = fcitx::utf8::length(state->rejectOriginal);
                ic->deleteSurroundingText(-static_cast<int>(count), count);
                ic->commitString(state->rejectTarget);
                state->suppressNextSpace = false;
                state->edit.clear();
                diagnostic(ic, "undo-reverted-for-punctuation");
                return; // The punctuation key itself reaches the application.
            }
        }
        if (key.check(FcitxKey_BackSpace) && !state->original.empty()) {
            if (!state->waitingForSurrounding && surroundingUsable(ic) && ic->surroundingText().text() == state->expectedText &&
                ic->surroundingText().cursor() == state->expectedCursor) {
                const auto original = state->original;
                auto target = state->replacement;
                if (!target.empty() && target.back() == ' ') target.pop_back();
                if (preedit) {
                    sendFeedback(feedbackId(), "reject", original, target, state->undoPrevious, state->undoFeedbackId);
                } else {
                    state->rejectPending = true;
                    state->rejectOriginal = original;
                    state->rejectTarget = target;
                    state->rejectPrevious = state->undoPrevious;
                    state->rejectUndoOf = state->undoFeedbackId;
                }
                const auto count = fcitx::utf8::length(state->replacement);
                state->edit.clear();
                state->clearUndo();
                ic->deleteSurroundingText(-static_cast<int>(count), count);
                if (preedit) {
                    state->composing = original;
                } else {
                    ic->commitString(original);
                }
                state->suppressNextSpace = true;
                render(ic, state);
                diagnostic(ic, "undo");
                event.filterAndAccept();
                return;
            }
            diagnostic(ic, "undo-declined-stale-or-unavailable");
        }
        state->clearUndo();
        if (!preedit) {
            if (std::getenv("AUTOCORRECT_PROBE_LEARNING")) {
                if (key.check(FcitxKey_space) || key.check(FcitxKey_Return)) {
                    auto observation = state->edit.finish(ic->surroundingText().text(), surroundingUsable(ic) ? cursorByte(ic) : 0);
                    if (observation && surroundingUsable(ic)) {
                        sendFeedback(feedbackId(), "manual", observation->original, observation->target, observation->previous);
                        state->suppressNextSpace = false;
                        return; // The user's completed edit is not autocorrected again.
                    }
                } else {
                    const bool backspace = key.sym() == FcitxKey_BackSpace;
                    const bool deletion = backspace || key.check(FcitxKey_Delete);
                    const auto codePoint = fcitx::Key::keySymToUnicode(key.sym());
                    const bool typing = codePoint >= 0x21 && !key.hasModifier();
                    const bool controlBackspace = backspace && key.check(FcitxKey_BackSpace, fcitx::KeyState::Ctrl);
                    if ((deletion && (!key.hasModifier() || controlBackspace)) || typing) {
                        if (ic->surroundingText().isValid() && ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText)) {
                            const auto &surrounding = ic->surroundingText();
                            const auto anchor = fcitx::utf8::ncharByteLength(surrounding.text().begin(), surrounding.anchor());
                            if (!state->edit.active) state->edit.begin(surrounding.text(), cursorByte(ic), anchor, backspace, deletion);
                            if (state->edit.active) state->edit.authorize(surrounding.text(), cursorByte(ic), anchor,
                                backspace, deletion, controlBackspace, typing ? fcitx::Key::keySymToUTF8(key.sym()) : "");
                        }
                    } else if (!key.isCursorMove()) state->edit.clear();
                }
            }
            if (key.check(FcitxKey_space)) {
                if (state->suppressNextSpace) {
                    state->suppressNextSpace = false;
                    if (state->rejectPending && originalBeforeCursor(ic, state->rejectOriginal)) {
                        sendFeedback(feedbackId(), "reject", state->rejectOriginal, state->rejectTarget,
                                     state->rejectPrevious, state->rejectUndoOf);
                        diagnostic(ic, "undo-kept");
                    }
                    state->rejectPending = false;
                    return;
                }
                replaceSurrounding(ic, state, event);
            } else {
                state->suppressNextSpace = false;
            }
            return;
        }
        if (key.check(FcitxKey_BackSpace) && !state->composing.empty()) {
            state->composing.pop_back();
            state->suppressNextSpace = false;
            render(ic, state);
            event.filterAndAccept();
            return;
        }
        if (key.isLAZ() && !key.hasModifier() && !state->bypassWord) {
            state->suppressNextSpace = false;
            state->composing += static_cast<char>(key.sym());
            if (state->composing.size() >= 64) {
                ic->commitString(state->composing);
                state->composing.clear();
                state->bypassWord = true;
            }
            render(ic, state);
            event.filterAndAccept();
            return;
        }
        if (key.check(FcitxKey_space)) {
            state->bypassWord = false;
            if (state->composing.empty()) {
                state->suppressNextSpace = false;
                return;
            }
            const auto original = state->composing;
            const auto output = state->suppressNextSpace ? original : correction(original);
            state->suppressNextSpace = false;
            state->composing.clear();
            render(ic, state);
            rememberUndo(ic, state, original, output + " ", 0);
            ic->commitString(output + " ");
            diagnostic(ic, output == original ? "commit-original" : "correct-preedit");
            event.filterAndAccept();
            return;
        }
        // Shortcuts/navigation/punctuation commit exactly the original composition.
        if (!state->composing.empty()) {
            const auto original = state->composing;
            state->composing.clear();
            render(ic, state);
            ic->commitString(original);
        }
        state->suppressNextSpace = false;
        state->bypassWord = !(key.isCursorMove() || key.hasModifier() || key.check(FcitxKey_BackSpace) ||
                              key.check(FcitxKey_Return) || key.check(FcitxKey_Tab));
    }

private:
    void acknowledgeWayland(fcitx::InputContext *ic) {
        // Fcitx 5.1.22 suppresses repeated empty preedits. Chromium's v3 IME
        // waits for a done before sending more surrounding state. An empty
        // commit acknowledges the serial without inserting any text. Keep this
        // compatibility path confined to the opt-in desktop surrounding trial.
        const auto *program = std::getenv("AUTOCORRECT_PROBE_ALLOWED_PROGRAM");
        if (std::getenv("AUTOCORRECT_PROBE_WAYLAND_ACK") && program && *program
            && ic->program() == program && ic->frontendName() == "wayland_v2" && ic->hasFocus()
            && instance_->inputMethod(ic) == "autocorrect-probe-surrounding") {
            ic->commitString("");
        }
    }

    void observeEdit(fcitx::InputContext *ic, State *state) {
        const bool active = state->edit.active;
        auto observation = state->edit.observe(ic->surroundingText().text(), cursorByte(ic), cursorByte(ic));
        if (observation) sendFeedback(feedbackId(), "manual", observation->original, observation->target, observation->previous);
        else if (active && !state->edit.active && std::getenv("AUTOCORRECT_PROBE_TEST")) diagnostic(ic, "edit-discard");
    }

    void clearChoices(fcitx::InputContext *ic, State *state) {
        if (state->choices.empty()) return;
        state->choices.clear();
        state->choiceReady = false;
        ic->inputPanel().setCandidateList(nullptr);
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
    }

    void confirmSelection(fcitx::InputContext *ic, State *state, bool cancelIfStale) {
        if (state->pendingFeedbackId.empty()) return;
        if (ic->hasFocus() && surroundingUsable(ic) && ic->surroundingText().text() == state->expectedText
            && ic->surroundingText().cursor() == state->expectedCursor) {
            const auto id = state->pendingFeedbackId;
            state->pendingFeedbackId.clear();
            sendFeedback(id, "selection", state->pendingOriginal, state->pendingTarget, state->pendingPrevious);
        } else if (cancelIfStale) state->pendingFeedbackId.clear();
    }

    bool selectChoice(fcitx::InputContext *ic, State *state, int index) {
        if (blocked(ic) || !ic->hasFocus() || !surroundingUsable(ic) || index < 0 || index >= static_cast<int>(state->choices.size())
            || ic->surroundingText().text() != state->choiceText || ic->surroundingText().cursor() != state->choiceCursor) return false;
        const auto output = state->choices[index];
        const auto original = state->choiceOriginal;
        const auto previous = state->choicePrevious;
        clearChoices(ic, state);
        state->edit.clear();
        const auto removeBytes = original.size() + 1; // Includes the just-typed space.
        rememberUndo(ic, state, original, output + " ", removeBytes);
        state->undoPrevious = previous;
        state->undoFeedbackId = feedbackId();
        state->pendingFeedbackId = state->undoFeedbackId;
        state->pendingOriginal = original;
        state->pendingTarget = output;
        state->pendingPrevious = previous;
        const auto chars = fcitx::utf8::length(original) + 1;
        ic->deleteSurroundingText(-static_cast<int>(chars), chars);
        ic->commitString(output + " ");
        diagnostic(ic, "manual-candidate");
        return true;
    }

    void rememberUndo(fcitx::InputContext *ic, State *state, const std::string &original,
                      const std::string &output, unsigned removeCount) {
        if (output == original + " ") {
            return;
        }
        state->original = original;
        state->replacement = output;
        if (!surroundingUsable(ic)) {
            state->waitingForSurrounding = true;
            diagnostic(ic, "undo-awaiting-surrounding");
            return;
        }
        const auto &surrounding = ic->surroundingText();
        auto byte = cursorByte(ic);
        if (byte < removeCount) {
            return;
        }
        const auto removeChars = removeCount ? fcitx::utf8::length(surrounding.text().substr(byte - removeCount, removeCount)) : 0;
        state->expectedCursor = surrounding.cursor() - removeChars + fcitx::utf8::length(output);
        state->expectedText = surrounding.text();
        state->expectedText.replace(byte - removeCount, removeCount, output);
    }

    void replaceSurrounding(fcitx::InputContext *ic, State *state, fcitx::KeyEvent &event) {
        if (!surroundingUsable(ic)) {
            diagnostic(ic, "no-surrounding-text");
            return;
        }
        const auto &text = ic->surroundingText().text();
        const auto cursor = cursorByte(ic);
        auto start = cursor;
        while (start && !separator(text[start - 1])) {
            --start;
        }
        if (cursor - start > 512) {
            return;
        }
        if (cursor < text.size() && !separator(text[cursor])) {
            return;
        }
        const auto original = text.substr(start, cursor - start);
        // Bound the prefix in bytes, then advance to a whitespace boundary:
        // no partial UTF-8 code point or truncated word enters the tokenizer.
        auto contextStart = start > 1024 ? start - 1024 : 0;
        while (contextStart && contextStart < start && !separator(text[contextStart - 1])) {
            ++contextStart;
        }
        const auto previous = text.substr(contextStart, start - contextStart);
        const auto reply = std::getenv("AUTOCORRECT_PROBE_ENGINE_SOCKET") ? queryEngine(original, previous)
            : EngineReply{correction(original), {}, false};
        const auto &output = reply.output;
        if (output == original) {
            if (reply.suggestionsEnabled && !reply.candidates.empty()) {
                state->choices = reply.candidates;
                state->choiceOriginal = original;
                state->choicePrevious = previous;
                state->choiceBeforeText = text;
                state->choiceText = text;
                state->choiceText.insert(cursor, " ");
                state->choiceCursor = ic->surroundingText().cursor() + 1;
                state->choiceReady = false;
                auto list = std::make_unique<fcitx::CommonCandidateList>();
                list->setSelectionKey(selectionKeys(ic));
                for (size_t i = 0; i < state->choices.size(); ++i) {
                    list->append<FeedbackCandidate>(state->choices[i], [this, i](fcitx::InputContext *context) {
                        selectChoice(context, context->propertyFor(&factory_), i);
                    });
                }
                list->setLayoutHint(fcitx::CandidateLayoutHint::Horizontal);
                ic->inputPanel().setCandidateList(std::move(list));
                ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
            }
            return;
        }
        state->edit.clear();
        const auto count = fcitx::utf8::length(original);
        rememberUndo(ic, state, original, output + " ", original.size());
        state->undoPrevious = previous;
        ic->deleteSurroundingText(-static_cast<int>(count), count);
        ic->commitString(output + " ");
        diagnostic(ic, "correct-surrounding");
        event.filterAndAccept();
    }

    void render(fcitx::InputContext *ic, State *state) {
        ic->inputPanel().reset();
        fcitx::Text preedit(state->composing);
        preedit.setCursor(state->composing.size());
        ic->inputPanel().setClientPreedit(preedit);
        if (std::getenv("AUTOCORRECT_PROBE_POPUP") && !state->composing.empty()) {
            auto list = std::make_unique<fcitx::CommonCandidateList>();
            const auto found = replacements.find(state->composing);
            list->append<fcitx::DisplayOnlyCandidateWord>(fcitx::Text(
                found == replacements.end() ? state->composing : found->second));
            list->setLayoutHint(fcitx::CandidateLayoutHint::Vertical);
            ic->inputPanel().setCandidateList(std::move(list));
        }
        ic->updatePreedit();
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
    }

    fcitx::Instance *instance_;
    fcitx::SimpleInputContextPropertyFactory<State> factory_;
    std::unique_ptr<fcitx::HandlerTableEntry<fcitx::EventHandler>> surroundingWatcher_;
    std::unique_ptr<fcitx::HandlerTableEntry<fcitx::EventHandler>> cursorWatcher_;
    std::unique_ptr<fcitx::HandlerTableEntry<fcitx::EventHandler>> focusWatcher_;
};

class ProbeFactory : public fcitx::AddonFactory {
public:
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override {
        return new ProbeEngine(manager->instance());
    }
};
FCITX_ADDON_FACTORY(ProbeFactory)
