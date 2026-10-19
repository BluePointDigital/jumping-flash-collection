#pragma once
#include "robbit_input_core.h"
static RobbitKeyPulses<SDL_NUM_SCANCODES> robbit_pulses;
static const uint8_t* robbit_input_keys(const uint8_t* physical) {
    static bool checked=false;
    if (!checked) {
        checked=true;
        // Migrate only the inherited conflicting preset. S must confirm in
        // menus without also pressing Down; modern WASD is handled separately.
        if (psx_keybinds_get_button(1,PSX_KB_UP)==SDL_SCANCODE_W &&
            psx_keybinds_get_button(1,PSX_KB_DOWN)==SDL_SCANCODE_S &&
            psx_keybinds_get_button(1,PSX_KB_LEFT)==SDL_SCANCODE_A &&
            psx_keybinds_get_button(1,PSX_KB_RIGHT)==SDL_SCANCODE_D &&
            psx_keybinds_get_button(1,PSX_KB_CIRCLE)==SDL_SCANCODE_S &&
            psx_keybinds_get_button(1,PSX_KB_TRIANGLE)==SDL_SCANCODE_A) {
            psx_keybinds_set_button(1,PSX_KB_UP,SDL_SCANCODE_UP);
            psx_keybinds_set_button(1,PSX_KB_DOWN,SDL_SCANCODE_DOWN);
            psx_keybinds_set_button(1,PSX_KB_LEFT,SDL_SCANCODE_LEFT);
            psx_keybinds_set_button(1,PSX_KB_RIGHT,SDL_SCANCODE_RIGHT);
            psx_keybinds_save();
        }
    }
    return robbit_pulses.sample(physical, SDL_GetTicks());
}
static uint16_t robbit_input_pad(const uint8_t*,int);
static bool robbit_input_event(const SDL_Event&);
