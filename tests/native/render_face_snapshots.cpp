#include "bella_face.h"
#include "bella_face_renderer.h"

#include <array>
#include <fstream>
#include <string>

struct Snapshot {
    const char *name;
    FaceState status;
    int touch_pad;
};

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const std::array<Snapshot, 15> snapshots{{
        {"idle", FaceState::Idle, -1},
        {"happy", FaceState::Idle, 0},
        {"love", FaceState::Idle, 1},
        {"curious", FaceState::Idle, 2},
        {"wink", FaceState::Idle, 3},
        {"thinking", FaceState::Thinking, -1},
        {"error", FaceState::Error, -1},
        {"offline", FaceState::Offline, -1},
        {"excited", FaceState::Excited, -1},
        {"surprised", FaceState::Surprised, -1},
        {"sad", FaceState::Sad, -1},
        {"angry", FaceState::Angry, -1},
        {"sleepy", FaceState::Sleepy, -1},
        {"listening", FaceState::Listening, -1},
        {"speaking", FaceState::Speaking, -1},
    }};
    constexpr int width = 240;
    constexpr int height = 240;
    for (const Snapshot &snapshot : snapshots) {
        BellaFace face;
        face.status = snapshot.status;
        if (snapshot.touch_pad >= 0) face.touch(static_cast<unsigned>(snapshot.touch_pad), 1000);
        for (uint32_t now = 1000; now <= 1660; now += 33) face.tick(now, 0.033f);
        const BellaFaceGeometry geometry = face.geometry(1660);
        std::ofstream image(std::string(argv[1]) + "/" + snapshot.name + ".ppm", std::ios::binary);
        if (!image) return 3;
        image << "P6\n" << width << " " << height << "\n255\n";
        for (int y = 0; y < height; ++y) {
            for (int x = 0; x < width; ++x) {
                const auto color = bella_face_renderer::pixel(geometry, x, y, width, height);
                // Preview the actual RGB565 panel quantization, not RGB888 artwork.
                const uint16_t packed = bella_face_renderer::rgb565(color);
                const char rgb[] = {static_cast<char>(((packed >> 11) & 31) * 255 / 31),
                                    static_cast<char>(((packed >> 5) & 63) * 255 / 63),
                                    static_cast<char>((packed & 31) * 255 / 31)};
                image.write(rgb, sizeof(rgb));
            }
        }
        if (!image) return 4;
    }
}
