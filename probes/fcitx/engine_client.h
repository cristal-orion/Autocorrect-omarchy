// Bounded local request. Any failure means preserving the original input.
#pragma once
#include <json-c/json.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <string>
#include <fcitx-utils/utf8.h>

inline std::string queryEngine(const char *path, const std::string &token) {
    if (token.empty() || token.size() > 512 || std::strlen(path) >= sizeof(sockaddr_un::sun_path)) {
        return token;
    }
    int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return token;
    struct Cleanup {
        int fd;
        ~Cleanup() { close(fd); }
    } cleanup{fd};
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(50);
    auto wait = [&](short events) {
        int remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
                            deadline - std::chrono::steady_clock::now()).count();
        if (remaining <= 0) return false;
        pollfd descriptor{fd, events, 0};
        return poll(&descriptor, 1, remaining) > 0 && (descriptor.revents & events);
    };
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    std::strcpy(address.sun_path, path);
    if (connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0 && errno != EINPROGRESS) {
        return token;
    }
    if (!wait(POLLOUT)) return token;
    json_object *request = json_object_new_object();
    json_object_object_add(request, "token", json_object_new_string_len(token.data(), token.size()));
    const std::string encoded = json_object_to_json_string_ext(request, JSON_C_TO_STRING_PLAIN);
    json_object_put(request);
    if (send(fd, encoded.data(), encoded.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(encoded.size())) return token;
    if (!wait(POLLIN)) return token;
    char buffer[4096];
    const auto size = recv(fd, buffer, sizeof(buffer), MSG_TRUNC);
    if (size <= 0 || size >= static_cast<ssize_t>(sizeof(buffer))) return token;
    json_tokener *parser = json_tokener_new();
    json_object *response = json_tokener_parse_ex(parser, buffer, size);
    bool valid = json_tokener_get_error(parser) == json_tokener_success &&
                 json_object_is_type(response, json_type_object);
    json_tokener_free(parser);
    json_object *original = nullptr, *output = nullptr, *action = nullptr;
    valid = valid && json_object_object_get_ex(response, "original", &original) &&
            json_object_object_get_ex(response, "output", &output) &&
            json_object_object_get_ex(response, "action", &action) &&
            json_object_is_type(original, json_type_string) &&
            json_object_is_type(output, json_type_string) &&
            json_object_is_type(action, json_type_string);
    std::string result = token;
    if (valid && std::string(json_object_get_string(action)) == "correct" &&
        std::string(json_object_get_string(original), json_object_get_string_len(original)) == token) {
        std::string proposed(json_object_get_string(output), json_object_get_string_len(output));
        if (!proposed.empty() && proposed.size() <= 512 && proposed.find_first_of("\r\n\t ") == std::string::npos &&
            proposed.find('\0') == std::string::npos && fcitx::utf8::validate(proposed)) {
            result = proposed;
        }
    }
    if (response) json_object_put(response);
    return result;
}
