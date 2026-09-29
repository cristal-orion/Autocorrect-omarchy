// Bounded local requests. Failed or incoherent replies preserve the input.
#pragma once
#include "socket_client.h"
#include <json-c/json.h>
#include <fcitx-utils/utf8.h>
#include <memory>
#include <vector>
#include <cstdlib>

using ProbeJson = std::unique_ptr<json_object, decltype(&json_object_put)>;

inline ProbeJson probeRequest(json_object *request) {
    const std::string encoded = json_object_to_json_string_ext(request, JSON_C_TO_STRING_PLAIN);
    const auto raw = sendProbePacket(std::getenv("AUTOCORRECT_PROBE_ENGINE_SOCKET"), encoded);
    auto *parser = json_tokener_new();
    json_tokener_set_flags(parser, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    ProbeJson response(json_tokener_parse_ex(parser, raw.data(), raw.size()), json_object_put);
    if (json_tokener_get_error(parser) != json_tokener_success || !json_object_is_type(response.get(), json_type_object)) response.reset();
    json_tokener_free(parser);
    return response;
}

inline void jsonString(json_object *object, const char *key, const std::string &value) {
    json_object_object_add(object, key, json_object_new_string_len(value.data(), value.size()));
}

// A replacement is one word or a two-word split ("per piacere"): at most one
// inner space, never at an edge, and no other whitespace.
inline bool safeProbeOutput(const std::string &value) {
    const auto space = value.find(' ');
    return !value.empty() && value.size() <= 512 && value.find_first_of("\r\n\t") == std::string::npos
        && (space == std::string::npos || (space > 0 && space + 1 < value.size()
                                           && value.find(' ', space + 1) == std::string::npos))
        && value.find('\0') == std::string::npos && fcitx::utf8::validate(value);
}

struct EngineReply {
    std::string output;
    std::vector<std::string> candidates;
    bool suggestionsEnabled = false;
};

inline EngineReply queryEngine(const std::string &token, const std::string &previous = {}) {
    EngineReply result{token, {}, false};
    if (token.empty() || token.size() > 512 || previous.size() > 1024) return result;
    ProbeJson request(json_object_new_object(), json_object_put);
    jsonString(request.get(), "token", token);
    jsonString(request.get(), "previous", previous);
    jsonString(request.get(), "context", "text");
    auto response = probeRequest(request.get());
    json_object *original = nullptr, *output = nullptr, *action = nullptr, *enabled = nullptr, *candidates = nullptr;
    if (!response || !json_object_object_get_ex(response.get(), "original", &original)
        || !json_object_object_get_ex(response.get(), "output", &output)
        || !json_object_object_get_ex(response.get(), "action", &action)
        || !json_object_is_type(original, json_type_string) || !json_object_is_type(output, json_type_string)
        || !json_object_is_type(action, json_type_string)
        || std::string(json_object_get_string(original), json_object_get_string_len(original)) != token) return result;
    const std::string proposed(json_object_get_string(output), json_object_get_string_len(output));
    if (std::string(json_object_get_string(action)) == "correct" && safeProbeOutput(proposed)) result.output = proposed;
    if (result.output == token && std::string(json_object_get_string(action)) == "keep"
        && json_object_object_get_ex(response.get(), "suggestions_enabled", &enabled)
        && json_object_is_type(enabled, json_type_boolean) && json_object_get_boolean(enabled)
        && json_object_object_get_ex(response.get(), "candidate_outputs", &candidates)
        && json_object_is_type(candidates, json_type_array)) {
        result.suggestionsEnabled = true;
        for (size_t i = 0; i < json_object_array_length(candidates) && i < 3; ++i) {
            auto *candidate = json_object_array_get_idx(candidates, i);
            if (!json_object_is_type(candidate, json_type_string)) break;
            std::string text(json_object_get_string(candidate), json_object_get_string_len(candidate));
            if (safeProbeOutput(text)) result.candidates.push_back(text);
        }
    }
    return result;
}

inline std::string feedbackId() {
    static unsigned long long counter = 0;
    return std::to_string(getpid()) + ":" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count())
        + ":" + std::to_string(++counter);
}

inline void sendFeedback(const std::string &id, const std::string &kind, const std::string &original,
                         const std::string &target, const std::string &previous, const std::string &undoOf = {}) {
    if (!std::getenv("AUTOCORRECT_PROBE_LEARNING")) return;
    ProbeJson request(json_object_new_object(), json_object_put);
    for (const auto &[key, value] : std::vector<std::pair<const char *, std::string>>{
            {"op", "feedback"}, {"id", id}, {"kind", kind}, {"original", original}, {"target", target},
            {"previous", previous}, {"context", "text"}, {"undo_of", undoOf}}) jsonString(request.get(), key, value);
    probeRequest(request.get());
}
