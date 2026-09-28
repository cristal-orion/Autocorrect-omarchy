// Small bounded local transport, shared by the addon and its Qt laboratory UI.
#pragma once
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <chrono>
#include <cerrno>
#include <cstring>
#include <string>

inline std::string sendProbePacket(const char *path, const std::string &encoded) {
    if (!path || encoded.size() >= 4096 || std::strlen(path) >= sizeof(sockaddr_un::sun_path)) return {};
    const int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return {};
    struct Cleanup { int fd; ~Cleanup() { close(fd); } } cleanup{fd};
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(50);
    auto wait = [&](short events) {
        const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now()).count();
        if (remaining <= 0) return false;
        pollfd descriptor{fd, events, 0};
        return poll(&descriptor, 1, static_cast<int>(remaining)) > 0 && (descriptor.revents & events);
    };
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    std::strcpy(address.sun_path, path);
    if (connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address)) < 0 && errno != EINPROGRESS) return {};
    if (!wait(POLLOUT) || send(fd, encoded.data(), encoded.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(encoded.size())) return {};
    if (!wait(POLLIN)) return {};
    char buffer[8192];
    const auto size = recv(fd, buffer, sizeof(buffer), MSG_TRUNC);
    if (size <= 0 || size >= static_cast<ssize_t>(sizeof(buffer))) return {};
    return std::string(buffer, size);
}
