#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace jf2 {
struct TitleInputGate {
    bool armed = false;
    bool update(uint32_t held) {
        if (armed) return true;
        if (!(held & 0x8e0u)) armed = true;
        return false; // A movie-skip press must be released before title selection.
    }
};
struct Movement { int angle = 0; bool active = false; };
inline bool lateral_command(uint16_t pad) { return (pad & 0x0c00) != 0x0c00; }
inline uint16_t strafe_arrows(uint16_t pad, bool enabled) {
    if (!enabled) return pad;
    if (!(pad & 0x0080)) { pad |= 0x0080; pad &= ~0x0400; }
    if (!(pad & 0x0020)) { pad |= 0x0020; pad &= ~0x0800; }
    return pad;
}
// A direction command only. The guest retains its speed, inertia and gravity.
inline Movement movement(uint16_t pad, int yaw) {
    const int forward = !(pad & 0x0010) - (int)!(pad & 0x0040);
    const int right = !(pad & 0x0800) - (int)!(pad & 0x0400);
    if (!forward && !right) return {yaw & 4095, false};
    const double direction = std::atan2((double)right, (double)forward) * 4096.0 / (2.0 * 3.141592653589793);
    return {((yaw & 4095) + (int)std::lround(direction)) & 4095, true};
}
// PAL guest pad bits are the byte-swapped, positive version of the host pad.
inline uint16_t host_pad(uint32_t guest_pad) {
    return (uint16_t)~((guest_pad>>8) | (guest_pad<<8));
}
inline uint32_t movement_pad(uint32_t guest_pad, bool active) {
    return (guest_pad & ~0x500cu) | (active ? 0x1000u : 0u);
}
inline bool grounded(uint8_t contact, int state, int vertical_speed) {
    return contact != 0 && state == 0 && vertical_speed == 0;
}
inline int ground_boost(int base, bool enabled, bool airborne, int percent) {
    return enabled && !airborne ? base * std::clamp(percent, 125, 200) / 100 : base;
}
inline int title_hit(int x, int y) {
    if(x<96 || x>=544 || y<294 || y>=438) return -1;
    return (y-294)/24;
}
struct MouseLook {
    double dx = 0, dy = 0, pitch = 0;
    bool initialized = false;
    uint64_t consumed = UINT64_MAX;
    void clear() { dx = dy = pitch = 0; initialized = false; consumed = UINT64_MAX; }
    void move(double x, double y) { dx += x; dy += y; }
    int update(int yaw, int guest_pitch, uint64_t tick, int sensitivity, bool invert) {
        if (!initialized) { pitch = std::clamp(guest_pitch, -880, 760); initialized = true; }
        if (consumed == tick) return yaw;
        consumed = tick;
        const double rate = std::clamp(sensitivity, 10, 300) * 0.02;
        double angle = std::fmod(yaw + dx * rate, 4096.0);
        if (angle < 0) angle += 4096;
        pitch = std::clamp(pitch + dy * rate * (invert ? -1 : 1), -880.0, 760.0);
        dx = dy = 0;
        return static_cast<int>(std::lround(angle)) & 4095;
    }
};
inline void integer_rect(int ww, int wh, int base_w, int base_h, int& x, int& y, int& w, int& h) {
    const int scale = std::min(ww / base_w, wh / base_h);
    if (scale < 1) return; // Small windows keep the usual aspect-preserving fit.
    w = base_w * scale; h = base_h * scale;
    x = (ww - w) / 2; y = (wh - h) / 2;
}
}
