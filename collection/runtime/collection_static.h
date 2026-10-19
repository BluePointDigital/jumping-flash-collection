#ifndef COLLECTION_STATIC_H
#define COLLECTION_STATIC_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Set once before emulation; the disabled instruction path is one branch. */
extern int collection_static_mode;
void collection_static_init(void);
/* Returns one on the first observed interpreter attempt; strict mode exits. */
int collection_static_interpreter(int backend,uint32_t pc,uint32_t instruction,uint32_t ra,uint64_t frame);
void collection_static_compiler_request(void);
int collection_static_json(char *out,int capacity);
#ifdef __cplusplus
}
#endif
#endif
