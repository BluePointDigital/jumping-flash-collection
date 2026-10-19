#ifndef COLLECTION_METRICS_H
#define COLLECTION_METRICS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void collection_metrics_guest_tick(uint64_t frame);
void collection_metrics_swap(int generated);
uint64_t collection_metrics_swap_count(void);
int collection_metrics_json(char *out, int capacity, uint64_t after);
#ifdef __cplusplus
}
#endif
#endif
