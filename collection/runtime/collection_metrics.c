/* Bounded CPU-clock observation. Neither producer nor reader acquires GL. */
#include "collection_metrics.h"
#include "collection_diagnostics.h"
#include <SDL3/SDL.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#define COLLECTION_METRIC_CAP 256
typedef struct { uint64_t sequence, ns, guest; int generated; } SwapSample;
static SwapSample samples[COLLECTION_METRIC_CAP];
static atomic_flag sample_lock = ATOMIC_FLAG_INIT;
static _Atomic uint64_t guest_frame, swaps, generated_swaps, dropped_samples;
static _Atomic int enabled = -1;
static uint64_t stored;

static int metrics_enabled(void) {
    int value=atomic_load(&enabled);
    if(value<0){const char *e=getenv("PSX_COLLECTION_METRICS");value=!(e&&*e=='0');atomic_store(&enabled,value);}
    return value;
}
void collection_metrics_guest_tick(uint64_t frame) { if(metrics_enabled())atomic_store(&guest_frame, frame); }
uint64_t collection_metrics_swap_count(void) { return atomic_load(&swaps); }

void collection_metrics_swap(int generated) {
    if(!metrics_enabled())return;
    uint64_t sequence = atomic_fetch_add(&swaps, 1) + 1;
    if (generated) atomic_fetch_add(&generated_swaps, 1);
    if (atomic_flag_test_and_set_explicit(&sample_lock, memory_order_acquire)) {
        atomic_fetch_add(&dropped_samples, 1);
        return;
    }
    const uint64_t ticks = SDL_GetPerformanceCounter(), freq = SDL_GetPerformanceFrequency();
    SwapSample *sample = &samples[stored++ % COLLECTION_METRIC_CAP];
    *sample = (SwapSample){sequence, (ticks / freq) * UINT64_C(1000000000) +
        (ticks % freq) * UINT64_C(1000000000) / freq, atomic_load(&guest_frame), !!generated};
    atomic_flag_clear_explicit(&sample_lock, memory_order_release);
}

int collection_metrics_json(char *out, int capacity, uint64_t after) {
    SwapSample copy[COLLECTION_METRIC_CAP];
    unsigned count = 0;
    int busy = atomic_flag_test_and_set_explicit(&sample_lock, memory_order_acquire);
    if (!busy) {
        uint64_t first = stored > COLLECTION_METRIC_CAP ? stored - COLLECTION_METRIC_CAP : 0;
        for (uint64_t i = first; i < stored; ++i) {
            SwapSample sample = samples[i % COLLECTION_METRIC_CAP];
            if (sample.sequence > after) copy[count++] = sample;
        }
        atomic_flag_clear_explicit(&sample_lock, memory_order_release);
    }
    int length = snprintf(out, capacity,
        "\"schema\":1,\"metrics_enabled\":%s,\"clock\":\"host_monotonic_ns\","
        "\"semantics\":\"completed swap calls; guest counter is not source-image identity\","
        "\"physical_presents\":null,\"world_updates\":null,\"source_images\":null,"
        "\"guest_frame\":%llu,\"swap_calls\":%llu,\"generated_swap_calls\":%llu,"
        "\"sample_drops\":%llu,\"snapshot_busy\":%s,"
        "\"diagnostic_policy\":{\"display_ring\":%d,\"present_image_ring\":%d,\"gl_perf\":%d,\"phase_sampler\":%d,\"interpreter_trace\":%d},\"samples\":[",
        metrics_enabled()?"true":"false",(unsigned long long)atomic_load(&guest_frame), (unsigned long long)atomic_load(&swaps),
        (unsigned long long)atomic_load(&generated_swaps),
        (unsigned long long)atomic_load(&dropped_samples), busy ? "true" : "false",
        collection_diagnostic_enabled("PSX_DISPLAY_RING"),collection_diagnostic_enabled("PSX_PRESENT_IMAGE_RING"),
        collection_diagnostic_enabled("PSX_GL_PERF"),collection_diagnostic_enabled("PSX_PHASE_SAMPLER"),
        collection_diagnostic_enabled("PSX_INTERPRETER_TRACE"));
    if (length < 0 || length >= capacity) return 0;
    for (unsigned i = 0; i < count; ++i) {
        SwapSample *s = &copy[i];
        int written = snprintf(out + length, capacity - length, "%s[%llu,%llu,%llu,%d]",
            i ? "," : "", (unsigned long long)s->sequence, (unsigned long long)s->ns,
            (unsigned long long)s->guest, s->generated);
        if (written < 0 || written >= capacity - length) return 0;
        length += written;
    }
    if (capacity - length < 2) return 0;
    memcpy(out + length, "]", 2);
    return length + 1;
}
