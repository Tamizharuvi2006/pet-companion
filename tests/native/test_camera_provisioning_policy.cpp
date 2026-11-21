#include "bella_cam_policy.h"

#include <cassert>

int main() {
    assert(bella_cam_policy::valid_ssid("bella-network"));
    assert(!bella_cam_policy::valid_ssid(""));
    assert(!bella_cam_policy::valid_ssid(nullptr));
    assert(bella_cam_policy::valid_password("correct-horse"));
    assert(!bella_cam_policy::valid_password("short"));
    assert(bella_cam_policy::valid_token("aB3._~-0123456789"));
    assert(!bella_cam_policy::valid_token("too-short"));
    assert(!bella_cam_policy::valid_token("not safe / token"));
}
