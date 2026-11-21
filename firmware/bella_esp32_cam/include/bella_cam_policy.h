#pragma once

#include <cstddef>
#include <cstring>

namespace bella_cam_policy {

inline bool valid_ssid(const char *value) {
    if (!value) return false;
    const size_t length = std::strlen(value);
    return length > 0 && length <= 32;
}

inline bool valid_password(const char *value) {
    if (!value) return false;
    const size_t length = std::strlen(value);
    return length >= 8 && length <= 64;
}

inline bool valid_token(const char *value) {
    if (!value) return false;
    const size_t length = std::strlen(value);
    if (length < 16 || length > 192) return false;
    return std::strspn(value, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-") == length;
}

} // namespace bella_cam_policy
