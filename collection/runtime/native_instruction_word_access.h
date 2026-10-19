#ifndef PSX_NATIVE_INSTRUCTION_WORD_ACCESS_H
#define PSX_NATIVE_INSTRUCTION_WORD_ACCESS_H

#include "cpu_state.h"
#include "psx_memory.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Side-effect-free raw RAM fetch with the current interpreter's byte mapping.
 * It does not call CPUState read callbacks, advance cycles, or touch diagnostic
 * read hooks. Returns 0 for unaligned/non-RAM/out-of-live-bounds addresses. */
int psx_native_instruction_word_host(CPUState *cpu, uint32_t address,
                                     uint32_t *out);

#ifdef __cplusplus
}
#endif
#endif
