/* Staged candidate: no-cycle raw main-RAM instruction-word access. */
#include "native_instruction_word_access.h"

extern uint8_t *memory_get_ram_ptr(void);

int psx_native_instruction_word_host(CPUState *cpu, uint32_t address, uint32_t *out)
{
    uint32_t phys, offset, bytes;
    const uint8_t *ram;
    (void)cpu;
    if (!out || (address & 3u) != 0u || address >= 0xC0000000u) return 0;
    phys = address & 0x1FFFFFFFu;
    if (phys >= PSX_MAIN_RAM_WINDOW_BYTES) return 0;
    offset = psx_ram_map_read(phys);
    bytes = memory_get_ram_bytes();
    if (offset >= bytes || bytes - offset < 4u) return 0;
    ram = memory_get_ram_ptr();
    if (!ram) return 0;
    *out = (uint32_t)ram[offset] |
           ((uint32_t)ram[offset + 1u] << 8) |
           ((uint32_t)ram[offset + 2u] << 16) |
           ((uint32_t)ram[offset + 3u] << 24);
    return 1;
}
