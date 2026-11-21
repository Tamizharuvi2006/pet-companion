#pragma once

#include "bella_face.h"

#include <algorithm>
#include <cmath>
#include <cstdint>

// Small, deterministic RGB565 tile renderer. It intentionally uses no full-screen
// framebuffer, heap, PSRAM, fonts, or display-specific APIs.
namespace bella_face_renderer {

struct Color { uint8_t r, g, b; };

inline Color mix(Color a, Color b, float t) {
    t = std::clamp(t, 0.0f, 1.0f);
    return {static_cast<uint8_t>(a.r + (b.r - a.r) * t),
            static_cast<uint8_t>(a.g + (b.g - a.g) * t),
            static_cast<uint8_t>(a.b + (b.b - a.b) * t)};
}

inline uint16_t rgb565(Color color) {
    return static_cast<uint16_t>(((color.r & 0xF8U) << 8U) |
                                 ((color.g & 0xFCU) << 3U) |
                                 (color.b >> 3U));
}

inline bool ellipse(float x, float y, float rx, float ry) {
    if (rx <= 0.0f || ry <= 0.0f) return false;
    const float nx = x / rx, ny = y / ry;
    return nx * nx + ny * ny <= 1.0f;
}

inline bool segment(float x, float y, float ax, float ay, float bx, float by, float radius) {
    const float dx = bx - ax, dy = by - ay;
    const float length2 = dx * dx + dy * dy;
    const float t = length2 > 0.0f
        ? std::clamp(((x - ax) * dx + (y - ay) * dy) / length2, 0.0f, 1.0f)
        : 0.0f;
    const float ex = x - (ax + t * dx), ey = y - (ay + t * dy);
    return ex * ex + ey * ey <= radius * radius;
}

inline Color sample(const BellaFaceGeometry &face, float x, float y, int width, int height) {
    const float sx = static_cast<float>(width) / 240.0f;
    const float sy = static_cast<float>(height) / 240.0f;
    const float fx = (x + 0.5f) / sx;
    const float fy = (y + 0.5f) / sy;
    const float center_dx = (fx - 120.0f) / 140.0f;
    const float center_dy = (fy - 122.0f) / 156.0f;
    const float aura = std::max(0.0f, 1.0f - center_dx * center_dx - center_dy * center_dy);
    Color out = mix({10, 9, 18}, {29, 18, 43}, aura * 0.48f);
    const bool love = face.expression == FaceState::Love;
    const bool error = face.expression == FaceState::Error;
    const Color rim = love ? Color{58, 32, 70} : Color{40, 35, 61};
    const Color iris_top = error ? Color{80, 12, 43} : love ? Color{78, 19, 80} : Color{27, 17, 75};
    const Color iris_mid = error ? Color{199, 38, 105} : love ? Color{167, 63, 169} : Color{70, 44, 161};
    const Color iris_low = error ? Color{255, 155, 196} : love ? Color{255, 209, 239} : Color{166, 245, 255};
    const float openness = std::clamp(face.openness, 0.025f, 1.25f);
    const float gaze_x = std::clamp(face.gaze_x, -0.65f, 0.65f) * 13.0f;
    const float gaze_y = std::clamp(face.gaze_y, -0.5f, 0.5f) * 11.0f;

    for (int eye = 0; eye < 2; ++eye) {
        const float cx = eye == 0 ? 72.0f : 168.0f;
        const float side = std::clamp(eye == 0 ? face.left_open : face.right_open, 0.025f, 1.25f);
        const float rx = 43.0f * std::clamp(face.width, 0.82f, 1.22f);
        // Per-eye openness already includes blink; do not square it a second time.
        const float ry = 43.0f * side;
        const float ex = fx - cx;
        const float ey = fy - 120.0f;
        if (face.expression == FaceState::Offline) {
            const float nx = ex / rx;
            if (std::fabs(nx) < .70f && std::fabs(ey - (7.0f - nx * nx * 5.0f)) < 2.3f) out = {151, 205, 255};
            continue;
        }
        // Smiling/winking eyes are curved ribbons, not crushed sclera polygons.
        const float closed = std::clamp((0.42f - side) / 0.18f, 0.0f, 1.0f);
        const bool sleepy = face.expression == FaceState::Sleepy;
        if (closed > 0.01f && !sleepy) {
            const float nx = ex / rx;
            const float arc = -18.0f * (1.0f - nx * nx) + 8.0f;
            const float thickness = 2.0f + 2.0f * (1.0f - std::fabs(nx));
            if (std::fabs(nx) < 1.0f && std::fabs(ey - arc) < thickness)
                out = mix(out, {222, 173, 255}, closed);
            if (closed > .92f) {
                const float brow = -50.0f - 6.0f * (1.0f - nx * nx);
                if (std::fabs(nx) < .65f && std::fabs(ey-brow) < 1.0f) out = {190, 148, 219};
                continue;
            }
        }
        const float u = ex / (rx + 3.0f);
        const float v = ey / (ry + 3.0f);
        const float edge = std::sqrt(std::max(0.0f, 1.0f - u * u));
        const bool outer = std::fabs(u) <= 1.07f && std::fabs(v) <= edge + 0.075f;
        const float inner_u = ex / rx;
        const float inner_v = ey / ry;
        const float inner_edge = std::sqrt(std::max(0.0f, 1.0f - inner_u * inner_u));
        const float inward = (eye == 0 ? ex : -ex) / rx;
        const bool angry = face.expression == FaceState::Angry;
        const bool sad = face.expression == FaceState::Sad;
        const float lid_cut = angry ? -ry * .25f + inward * ry * .70f :
            sad ? -ry * .42f - inward * ry * .32f :
            sleepy ? -ry * .10f : face.expression == FaceState::Thinking ? -ry * (eye == 0 ? .78f : .55f) + inward * 2.5f : -ry;
        const bool white = std::fabs(inner_u) <= 1.0f && std::fabs(inner_v) <= inner_edge && ey >= lid_cut;

        if (outer) {
            out = white ? mix({246, 239, 255}, {185, 168, 211},
                                  std::clamp((inner_v + 0.65f) * 0.22f, 0.0f, 0.25f)) :
                ey < lid_cut - 3.0f ? out : rim;
            const float ix = ex - gaze_x;
            const float iy = ey + 3.0f - gaze_y;
            const float irx = 26.0f;
            const float iry = 37.0f;
            const float id = (ix * ix) / (irx * irx) + (iy * iy) / (iry * iry);
            if (white && id <= 1.0f) {
                const float vertical = std::clamp((iy / iry + 1.0f) * 0.5f, 0.0f, 1.0f);
                Color iris = mix(iris_top, iris_mid, std::clamp(vertical * 1.5f, 0.0f, 1.0f));
                if (vertical > 0.55f) iris = mix(iris, iris_low, (vertical - 0.55f) / 0.45f);
                const float ring = std::clamp((id - 0.70f) / 0.30f, 0.0f, 1.0f);
                out = mix(iris, rim, ring * 0.78f);
                // Fixed radial pigment fibers, never random per-frame sparkle.
                const float fibers = std::sin(std::atan2(iy / iry, ix / irx) * 24.0f);
                if (id > 0.24f && id < 0.86f) out = mix(out, iris_low, std::max(0.0f, fibers) * 0.06f);
                const float pupil_d = (ix * ix) / (8.8f * 8.8f) + (iy * iy) / (17.0f * 17.0f);
                if (pupil_d <= 1.0f) out = mix({24, 18, 36}, {48, 31, 65}, 1.0f - pupil_d * 0.35f);
                const float bounce = std::max(0.0f, 1.0f - (ix * ix) / 400.0f - ((iy - iry * .65f) * (iy - iry * .65f)) / 100.0f);
                out = mix(out, love ? Color{255, 190, 229} : Color{185, 250, 255}, bounce * .65f);
                if (love) {
                    const float hx = ix / 13.0f, hy = -(iy + 1.0f) / 13.0f;
                    const float q = hx * hx + hy * hy - 1.0f;
                    if (q * q * q - hx * hx * hy * hy * hy <= 0.0f) out = {255, 169, 226};
                }
                if (face.expression == FaceState::Excited &&
                    std::fabs(ix) / 15.0f + std::fabs(iy) / 24.0f < 1.0f) out = {255, 244, 172};
                if (ellipse(ix + 7.0f, iy + 10.0f, 5.4f, 7.2f)) out = {255, 252, 255};
                if (ellipse(ix - 8.0f, iy - 12.0f, 2.7f, 3.5f)) out = {255, 255, 255};
                if (ellipse(ix + 13.0f, iy - 11.0f, 1.7f, 2.0f)) out = {255, 240, 255};
            }
            // A soft upper-lid shadow and a crisp eyelash edge provide depth.
            if (white && inner_v < -0.42f) out = mix(out, {45, 35, 65}, (-inner_v - 0.42f) * 0.38f);
            const float upper_line_y = -ry * std::sqrt(std::max(0.0f, 1.0f - (ex * ex) / (rx * rx)));
            if (std::fabs(ey - upper_line_y) < 3.0f && std::fabs(ex) < rx * 0.98f) out = {33, 19, 47};
            if (std::fabs(ey - upper_line_y + 3.2f) < .9f && std::fabs(ex) < rx * .8f) out = {215, 173, 235};
            if ((angry || sad || sleepy || face.expression == FaceState::Thinking) &&
                std::fabs(ex) < rx * .93f && std::fabs(ey-lid_cut) < 2.4f) out = {205, 159, 230};
        }
        if (sad && ellipse(ex-(eye == 0 ? -30.0f : 30.0f), ey-ry*.75f, 7.0f, 3.5f)) out = {115, 197, 255};

        const float lash_side = eye == 0 ? -1.0f : 1.0f;
        if (side > .4f && (segment(ex, ey, lash_side * rx * .78f, -ry * .58f,
            lash_side * rx * 1.12f, -ry * .48f, 2.0f) ||
            segment(ex, ey, lash_side * rx * .63f, -ry * .77f,
            lash_side * rx * .92f, -ry * .94f, 1.5f))) out = {157, 117, 185};

        // Error keeps the same anime eye, replacing only the iris/pupil with X marks.
        if (face.crossed_pupils && ellipse(ex, ey, 14.0f, 22.0f)) {
            const bool slash = segment(ex, ey, -7, -12, 7, 12, 2.2f) ||
                               segment(ex, ey, 7, -12, -7, 12, 2.2f);
            if (slash) out = {225, 118, 165};
        }

        // Soft, tapered brow. It moves with expression angle but remains understated.
        const float brow_span = 28.0f;
        const float brow_x = ex;
        const float brow_curve = -58.0f - 7.0f * (1.0f - (brow_x * brow_x) / (brow_span * brow_span));
        const float thoughtful = face.expression == FaceState::Thinking ? (eye == 0 ? -8.0f : 3.0f) + brow_x * .10f : 0.0f;
        const float brow_y = brow_curve + thoughtful + (eye == 0 ? 1.0f : -1.0f) * face.eye_angle * 18.0f;
        if (std::fabs(brow_x) < brow_span && std::fabs(ey - brow_y) < 2.0f) out = {112, 88, 137};
    }

    if (face.expression == FaceState::Thinking) {
        // Gaze channel eases into this state; dots stay legible on small TFTs.
        for (int dot = 0; dot < 3; ++dot) {
            const float pulse = .5f + .5f * std::sin(face.animation_phase - dot * 1.1f);
            if (ellipse(fx - (183.0f + dot * 10.0f), fy - (43.0f - pulse * 2.0f), 2.0f + pulse, 2.0f + pulse))
                out = mix({106, 90, 177}, {226, 209, 255}, pulse);
        }
    }

    // The tiny center status light is the only connectivity indicator; no text
    // is rendered and all animation geometry remains resolution-independent.
    if (ellipse(fx - 120.0f, fy - 24.0f, 3.2f, 3.2f)) {
        out = face.expression == FaceState::Error ? Color{255, 111, 134} :
              face.offline ? Color{231, 157, 115} : Color{123, 230, 194};
    }
    return out;
}

// Four subpixel samples smooth actual RGB565 output, not just preview scaling.
// Bounded stack-only work; tile/DMA memory and transfer ordering are unchanged.
inline Color pixel(const BellaFaceGeometry &face, int x, int y, int width, int height) {
    const Color a = sample(face, x - .25f, y - .25f, width, height);
    const Color b = sample(face, x + .25f, y - .25f, width, height);
    const Color c = sample(face, x - .25f, y + .25f, width, height);
    const Color d = sample(face, x + .25f, y + .25f, width, height);
    return {static_cast<uint8_t>((unsigned(a.r)+b.r+c.r+d.r+2)/4),
            static_cast<uint8_t>((unsigned(a.g)+b.g+c.g+d.g+2)/4),
            static_cast<uint8_t>((unsigned(a.b)+b.b+c.b+d.b+2)/4)};
}

inline void render_tile(const BellaFaceGeometry &face, int width, int height,
                        int first_row, int rows, uint16_t *destination) {
    if (!destination || width <= 0 || height <= 0 || first_row < 0 || rows <= 0 ||
        first_row + rows > height) return;
    for (int row = 0; row < rows; ++row) {
        for (int column = 0; column < width; ++column) {
            destination[row * width + column] = rgb565(pixel(face, column, first_row + row, width, height));
        }
    }
}

} // namespace bella_face_renderer
