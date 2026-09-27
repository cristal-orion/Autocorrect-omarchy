// Minimal Fcitx feasibility probe: fixed ASCII replacements, no language model.
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

namespace {
const std::map<std::string, std::string> replacements{
    {"quesot", "questo"}, {"qaundo", "quando"}, {"domnai", "domani"}};

struct State : fcitx::InputContextProperty {
    std::string composing;
    std::string original;
    std::string replacement;
    std::string expectedText;
    unsigned expectedCursor = 0;
    bool waitingForSurrounding = false;
    bool bypassWord = false;
    bool suppressNextSpace = false;

    void clearUndo() {
        original.clear();
        replacement.clear();
        expectedText.clear();
        expectedCursor = 0;
        waitingForSurrounding = false;
    }
};

bool blocked(fcitx::InputContext *ic) {
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

std::size_t cursorByte(fcitx::InputContext *ic) {
    return fcitx::utf8::ncharByteLength(ic->surroundingText().text().begin(),
                                      ic->surroundingText().cursor());
}

void diagnostic(fcitx::InputContext *ic, const char *event) {
    // No text or key contents: logs identify only protocol/capability outcomes.
    std::cerr << "autocorrect-probe event=" << event << " program=" << ic->program()
              << " frontend=" << ic->frontend()
              << " preedit=" << ic->capabilityFlags().test(fcitx::CapabilityFlag::Preedit)
              << " surrounding=" << surroundingUsable(ic)
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
                auto *state = ic->propertyFor(&factory_);
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
    }

    void activate(const fcitx::InputMethodEntry &, fcitx::InputContextEvent &event) override {
        diagnostic(event.inputContext(), "activate");
    }

    void reset(const fcitx::InputMethodEntry &, fcitx::InputContextEvent &event) override {
        auto *ic = event.inputContext();
        *ic->propertyFor(&factory_) = State{};
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
        if (key.check(FcitxKey_BackSpace) && !state->original.empty()) {
            if (!state->waitingForSurrounding && surroundingUsable(ic) && ic->surroundingText().text() == state->expectedText &&
                ic->surroundingText().cursor() == state->expectedCursor) {
                const auto original = state->original;
                const auto count = state->replacement.size(); // Probe replacements are ASCII.
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
            if (key.check(FcitxKey_space)) {
                if (state->suppressNextSpace) {
                    state->suppressNextSpace = false;
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
            const auto found = replacements.find(original);
            const auto output = (found != replacements.end() && !state->suppressNextSpace)
                                    ? found->second : original;
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
        state->expectedCursor = surrounding.cursor() - removeCount + output.size();
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
        while (start && text[start - 1] >= 'a' && text[start - 1] <= 'z') {
            --start;
        }
        if (start && text[start - 1] != ' ' && text[start - 1] != '\n' && text[start - 1] != '\t') {
            return;
        }
        if (cursor < text.size() && ((text[cursor] >= 'a' && text[cursor] <= 'z') ||
                                     (text[cursor] >= 'A' && text[cursor] <= 'Z'))) {
            return;
        }
        const auto original = text.substr(start, cursor - start);
        const auto found = replacements.find(original);
        if (found == replacements.end()) {
            return;
        }
        rememberUndo(ic, state, original, found->second + " ", original.size());
        ic->deleteSurroundingText(-static_cast<int>(original.size()), original.size());
        ic->commitString(found->second + " ");
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
};

class ProbeFactory : public fcitx::AddonFactory {
public:
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override {
        return new ProbeEngine(manager->instance());
    }
};
FCITX_ADDON_FACTORY(ProbeFactory)
