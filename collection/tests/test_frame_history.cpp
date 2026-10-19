#include "frame_history.h"
#include <cstdio>
static int failures=0;
static void check(bool condition,const char *label){if(!condition){std::fprintf(stderr,"FAIL: %s\n",label);++failures;}}
int main(){
    CollectionFrameRecord records[6]{};
    const int origins[]={0,256,512,0,256,512};
    for(int i=0;i<6;i++){
        records[i].sequence=i+1;records[i].valid=1;
        records[i].rect[0]=origins[i];records[i].rect[2]=252;records[i].rect[3]=216;
    }
    int older=-1,display[]={0,0,252,216};
    // Two complete future buffers exist, but the displayed frame is sequence 4.
    int newer=collection_frame_pair(records,6,5,display,3,&older);
    check(newer==3 && older==2,"triple buffer uses displayed sequence 4 after sequence 3, not newest drawing");
    display[0]=256;
    newer=collection_frame_pair(records,6,5,display,4,&older);
    check(newer==4 && older==3,"next flip follows presentation order");
    display[0]=512;
    newer=collection_frame_pair(records,6,5,display,5,&older);
    check(newer==-1 && older==-1,"capturing list and older reuse of the same buffer are excluded");
    records[5].valid=0;
    newer=collection_frame_pair(records,6,-1,display,5,&older);
    check(newer==-1,"partial list cannot be interpolated");
    records[5].valid=1;records[4].valid=0;
    newer=collection_frame_pair(records,6,-1,display,5,&older);
    check(newer==5 && older==-1,"missing previous display resets continuity");
    display[2]=320;
    newer=collection_frame_pair(records,6,-1,display,0,&older);
    check(newer==-1,"display mode changes cannot reuse a differently sized list");
    std::printf("Frame history: %d failures\n",failures);return failures?1:0;
}
