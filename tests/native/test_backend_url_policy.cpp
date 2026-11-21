#include "bella_backend_url_policy.h"

#include <cassert>

int main() {
    assert(bella_backend_url_is_valid_wss("wss://bella.example/ws/device"));
    assert(bella_backend_url_is_valid_wss("wss://service.up.railway.app/ws/device"));
    assert(bella_backend_url_is_valid_wss("wss://[2001:db8::1]:443/ws/device"));
    assert(!bella_backend_url_is_valid_wss(nullptr));
    assert(!bella_backend_url_is_valid_wss("ws://bella.example/ws/device"));
    assert(!bella_backend_url_is_valid_wss("wss://bella.example@evil.test/ws/device"));
    assert(!bella_backend_url_is_valid_wss("wss://bella.example/ws/device?token=x"));
    assert(!bella_backend_url_is_valid_wss("wss://bella.example/ws/device/"));
    assert(!bella_backend_url_is_valid_wss("wss://bella.example/other"));
    assert(!bella_backend_url_is_valid_wss("wss://:443/ws/device"));
    assert(!bella_backend_url_is_valid_wss("wss://bella.example:bad/ws/device"));
    assert(!bella_backend_url_is_valid_wss("wss://bella.example:0/ws/device"));
}
