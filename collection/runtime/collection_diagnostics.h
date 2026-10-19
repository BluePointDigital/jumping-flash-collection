#ifndef COLLECTION_DIAGNOSTICS_H
#define COLLECTION_DIAGNOSTICS_H
#include <stdlib.h>

/* Explicit per-feature values override the development-wide opt-in. */
static inline int collection_diagnostic_enabled(const char *name) {
    const char *value = getenv(name);
    if (!value || !*value) value = getenv("PSX_COLLECTION_DIAGNOSTICS");
    return value && *value && *value != '0';
}
#endif
