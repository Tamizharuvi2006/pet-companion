#include "bella_face.h"
#include "bella_face_renderer.h"
#include "bella_touch_gesture.h"

#include <array>
#include <cassert>
#include <cstdint>

int main() {
    BellaFace face;
    std::array<uint16_t, 240 * 16> tile{};
    const auto geometry = face.geometry(0);
    bella_face_renderer::render_tile(geometry, 240, 240, 96, 16, tile.data());
    bool has_iris = false;
    for (const uint16_t color : tile) {
        const unsigned red = ((color >> 11) & 0x1fU) * 8U;
        const unsigned green = ((color >> 5) & 0x3fU) * 4U;
        const unsigned blue = (color & 0x1fU) * 8U;
        if (blue > red + 40 && blue > green + 40 && blue > 100) has_iris = true;
    }
    assert(has_iris);

    tile.fill(0xffff);
    bella_face_renderer::render_tile(geometry, 240, 320, 304, 16, tile.data());
    assert(tile.front() != 0xffff);
    tile.fill(0xffff);
    bella_face_renderer::render_tile(geometry, 240, 320, 305, 16, tile.data());
    assert(tile.front() == 0xffff); // out-of-bounds request is a no-op

    BellaTouch4Gesture gesture;
    gesture.press(0xfffffff0U);
    assert(gesture.poll(20U, 900, true) == BellaTouch4Action::None); // wrap-safe short hold
    assert(gesture.release() == BellaTouch4Action::ShortTap);
    gesture.press(1000);
    assert(gesture.poll(1900, 900, true) == BellaTouch4Action::StartPushToTalk);
    assert(gesture.poll(2000, 900, true) == BellaTouch4Action::None);
    assert(gesture.release() == BellaTouch4Action::StopPushToTalk);
    gesture.press(3000);
    assert(gesture.poll(5000, 900, false) == BellaTouch4Action::None);
    assert(gesture.release() == BellaTouch4Action::ShortTap);
}
