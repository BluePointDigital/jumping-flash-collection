#ifndef COLLECTION_OVERLAY_LIMITS_H
#define COLLECTION_OVERLAY_LIMITS_H
/* Host-only table budget. Native shard layout, API ABI and emitted instructions
 * are unchanged. The build exports the matching compiler descriptor. */
#define COLLECTION_OVERLAY_LIMITS_SCHEMA 1
/* JF1's emitted canonical primaries require at least 131,916 candidate rows,
 * before supplements and other segment views. The 131,072-slot budget cannot
 * hold that set. This changes host tables only; qualify footprint separately. */
#define COLLECTION_OVERLAY_CANDIDATE_CAP 262144
#endif
