#pragma once

#include <cstddef>
#include <cstring>

// The device only needs one fixed WSS endpoint. Reject user-info, query strings,
// fragments, alternate paths, and other authority characters before TLS setup.
inline bool bella_backend_url_is_valid_wss(const char *url) {
    constexpr char scheme[] = "wss://";
    constexpr char endpoint[] = "/ws/device";
    if (!url || std::strncmp(url, scheme, sizeof(scheme) - 1) != 0) return false;

    const char *authority = url + sizeof(scheme) - 1;
    const char *path = std::strchr(authority, '/');
    if (!path || std::strcmp(path, endpoint) != 0) return false;
    const size_t authority_length = static_cast<size_t>(path - authority);
    if (authority_length == 0 || authority_length > 180) return false;

    const auto valid_port = [](const char *digits, size_t length) {
        if (length == 0 || length > 5) return false;
        unsigned value = 0;
        for (size_t i = 0; i < length; ++i) {
            if (digits[i] < '0' || digits[i] > '9') return false;
            value = value * 10U + static_cast<unsigned>(digits[i] - '0');
        }
        return value > 0 && value <= 65535;
    };
    const auto valid_domain = [](const char *host, size_t length) {
        if (length == 0 || length > 180 || host[0] == '.' || host[length - 1] == '.') return false;
        size_t label_start = 0;
        for (size_t i = 0; i <= length; ++i) {
            if (i == length || host[i] == '.') {
                if (i == label_start || host[label_start] == '-' || host[i - 1] == '-') return false;
                label_start = i + 1;
                continue;
            }
            const char c = host[i];
            if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                  (c >= '0' && c <= '9') || c == '-')) return false;
        }
        return true;
    };

    if (authority[0] == '[') {
        const char *close = static_cast<const char *>(std::memchr(authority, ']', authority_length));
        if (!close || close - authority < 3) return false;
        bool has_colon = false;
        for (const char *cursor = authority + 1; cursor < close; ++cursor) {
            const char c = *cursor;
            if (c == ':') { has_colon = true; continue; }
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
                  (c >= 'A' && c <= 'F') || c == '.')) return false;
        }
        if (!has_colon) return false;
        const size_t remaining = authority_length - static_cast<size_t>(close + 1 - authority);
        if (remaining == 0) return true;
        return close[1] == ':' && valid_port(close + 2, remaining - 1);
    }

    const char *colon = static_cast<const char *>(std::memchr(authority, ':', authority_length));
    const size_t host_length = colon ? static_cast<size_t>(colon - authority) : authority_length;
    if (!valid_domain(authority, host_length)) return false;
    return !colon || valid_port(colon + 1, authority_length - host_length - 1);
}
