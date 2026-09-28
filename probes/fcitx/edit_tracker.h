// Tracks a local, user-key-driven replacement of one whitespace-delimited word.
// Byte offsets must be valid UTF-8 boundaries supplied by the input context.
#pragma once
#include <algorithm>
#include <optional>
#include <string>

inline bool wordSeparator(char c) { return c == ' ' || c == '\n' || c == '\r' || c == '\t'; }

inline std::string boundedPrevious(const std::string &prefix) {
    size_t start = prefix.size() > 1024 ? prefix.size() - 1024 : 0;
    while (start && start < prefix.size() && !wordSeparator(prefix[start - 1])) ++start;
    return prefix.substr(start);
}

struct ManualObservation { std::string original, target, previous; };

class EditTracker {
public:
    bool active = false, awaitingChange = false;
    std::string original, prefix, suffix, lastText;
    std::string plannedText, intermediateText;
    bool hasPlan = false, hasIntermediate = false;

    void clear() { *this = EditTracker{}; }

    bool begin(const std::string &text, size_t cursor, size_t anchor, bool backspace, bool deletion) {
        if (text.size() > 16384 || cursor > text.size() || anchor > text.size()) return false;
        auto left = std::min(cursor, anchor), right = std::max(cursor, anchor);
        size_t suffixStart;
        if (left != right) {
            // Whole-field clearing and multiword selections aren't typo edits.
            if ((left == 0 && right == text.size())
                || std::any_of(text.begin() + left, text.begin() + right, wordSeparator)) return false;
            while (left && !wordSeparator(text[left - 1])) --left;
            while (right < text.size() && !wordSeparator(text[right])) ++right;
            suffixStart = right;
        } else {
            if (backspace) {
                while (left && text[left - 1] == ' ') --left;
                if (!left || wordSeparator(text[left - 1])) return false;
            } else if (left >= text.size() || wordSeparator(text[left])) {
                return false; // Appending to a fresh word is ordinary typing.
            }
            right = left;
            while (left && !wordSeparator(text[left - 1])) --left;
            while (right < text.size() && !wordSeparator(text[right])) ++right;
            suffixStart = std::max(right, cursor);
            if (!deletion && cursor == right) return false;
        }
        if (right <= left || right - left > 256) return false;
        original = text.substr(left, right - left);
        prefix = text.substr(0, left);
        suffix = text.substr(suffixStart);
        lastText = text;
        active = awaitingChange = true;
        return true;
    }

    std::optional<std::string> target(const std::string &text) const {
        if (text.size() < prefix.size() + suffix.size() || !text.starts_with(prefix) || !text.ends_with(suffix)) return {};
        auto word = text.substr(prefix.size(), text.size() - prefix.size() - suffix.size());
        while (!word.empty() && word.back() == ' ') word.pop_back();
        if (word.size() > 256 || std::any_of(word.begin(), word.end(), wordSeparator)) return {};
        return word;
    }

    void authorize(const std::string &text, size_t cursor, size_t anchor, bool backspace,
                   bool deletion, bool wordBackspace, const std::string &inserted) {
        if (!active || cursor > text.size() || anchor > text.size()) return;
        auto begin = std::min(cursor, anchor), end = std::max(cursor, anchor);
        if (begin == end && deletion) {
            if (backspace && begin) {
                if (wordBackspace) {
                    while (begin && text[begin - 1] == ' ') --begin;
                    while (begin && !wordSeparator(text[begin - 1])) --begin;
                } else {
                    --begin;
                    while (begin && (static_cast<unsigned char>(text[begin]) & 0xc0) == 0x80) --begin;
                }
            } else if (!backspace && end < text.size()) {
                ++end;
                while (end < text.size() && (static_cast<unsigned char>(text[end]) & 0xc0) == 0x80) ++end;
            }
        }
        auto changed = text;
        changed.erase(begin, end - begin);
        hasIntermediate = !inserted.empty() && begin != end;
        intermediateText = hasIntermediate ? changed : "";
        changed.insert(begin, inserted);
        plannedText = std::move(changed);
        hasPlan = true;
        awaitingChange = true;
    }

    std::optional<ManualObservation> observe(const std::string &text, size_t cursor, size_t anchor) {
        if (!active) return {};
        if (text != lastText) {
            if (!awaitingChange || !target(text) || !hasPlan) { clear(); return {}; }
            if (text != plannedText) {
                if (hasIntermediate && text == intermediateText) {
                    lastText = text;
                    return {}; // Selection deletion may precede its replacement.
                }
                clear();
                return {};
            }
            lastText = text;
            awaitingChange = false;
            hasPlan = hasIntermediate = false;
            plannedText.clear();
            intermediateText.clear();
        }
        if (cursor != anchor) { clear(); return {}; }
        if (cursor < prefix.size() || cursor > text.size() - suffix.size()) {
            auto word = target(text);
            std::optional<ManualObservation> result;
            // Leaving a word already changed by observed user keys completes
            // that edit. Toolkits may move the caret without forwarding End.
            if (!awaitingChange && word && !word->empty() && *word != original)
                result = ManualObservation{original, *word, boundedPrevious(prefix)};
            clear();
            return result;
        }
        return {};
    }

    std::optional<ManualObservation> finish(const std::string &text, size_t cursor) {
        auto word = target(text);
        std::optional<ManualObservation> result;
        if (active && !awaitingChange && text == lastText && word && !word->empty() && *word != original
            && cursor == prefix.size() + word->size())
            result = ManualObservation{original, *word, boundedPrevious(prefix)};
        clear();
        return result;
    }
};
