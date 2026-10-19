#ifndef COLLECTION_FRAME_HISTORY_H
#define COLLECTION_FRAME_HISTORY_H
#include <stdint.h>
/* Presentation may lag drawing by two buffers. Pair the displayed list with
 * the previous displayed list, and never interpolate across a missing history. */
typedef struct { uint64_t sequence; int valid, rect[4]; } CollectionFrameRecord;
static inline int collection_frame_pair(const CollectionFrameRecord *records, int count,
                                       int capturing, const int rect[4], uint64_t previous,
                                       int *older) {
    int newer=-1; *older=-1;
    for(int i=0;i<count;i++) {
        if(i==capturing || !records[i].valid)continue;
        if(records[i].sequence==previous)*older=i;
        int same=1;
        for(int k=0;k<4;k++)if(records[i].rect[k]!=rect[k])same=0;
        if(same && records[i].sequence>previous &&
           (newer<0 || records[i].sequence>records[newer].sequence))newer=i;
    }
    if(newer<0)*older=-1;
    return newer;
}
#endif
