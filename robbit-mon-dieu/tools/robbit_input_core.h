#pragma once
#include <array>
#include <cstdint>
#include <cstddef>
#include <algorithm>
#include <cmath>

template <std::size_t Count> struct RobbitKeyPulses {
    std::array<uint64_t, Count> until{};
    std::array<uint8_t, Count> keys{};
    std::array<uint8_t, Count> blocked{};
    void press(int key, uint64_t now) {
        if (key > 0 && static_cast<std::size_t>(key) < Count) until[key] = now + 80;
    }
    void clear() { until.fill(0); keys.fill(0); blocked.fill(0); }
    void block_held(const uint8_t* physical) {
        clear(); std::copy(physical,physical+Count,blocked.begin());
    }
    const uint8_t* sample(const uint8_t* physical, uint64_t now) {
        for (std::size_t i=0; i<Count; ++i) {
            if (!physical[i]) blocked[i]=0;
            keys[i]=!blocked[i] && (physical[i] || now<until[i]);
        }
        return keys.data();
    }
};

// Robbit uses 4096 angle units per turn and 12 fractional bits in player state.
struct RobbitMouseLook {
    double dx=0, dy=0, pitch=0;
    bool initialized=false;
    void clear() { dx=dy=pitch=0; initialized=false; }
    void move(double x,double y) {
        if (std::isfinite(x) && std::isfinite(y)) {
            dx=std::clamp(dx+x,-16384.0,16384.0);
            dy=std::clamp(dy+y,-16384.0,16384.0);
        }
    }
    int update(int yaw,int guest_pitch,int sensitivity,bool invert) {
        if (!initialized) { pitch=std::clamp(double(guest_pitch),-896.0,896.0); initialized=true; }
        const double rate=1.5*std::clamp(sensitivity,10,300)/100.0;
        yaw=(yaw+int(std::lround(dx*rate)))&4095;
        // Camera rotation negates the player's pitch: moving down decreases it.
        pitch=std::clamp(pitch-dy*rate*(invert?-1:1),-896.0,896.0);
        dx=dy=0;
        return yaw;
    }
};
inline bool robbit_live_flags(uint32_t flags,int mode,int locks) {
    return (flags&0x00300018)==0x00100000 && mode==1 && locks==0;
}
// A unit direction selects the guest's existing walking speed, including diagonals.
inline int robbit_move_angle(int x,int forward) {
    if (!x && !forward) return 0;
    return int(std::lround(std::atan2(double(x),double(forward))*4096.0/6.283185307179586))&4095;
}
