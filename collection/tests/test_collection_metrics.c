#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "collection_metrics.h"
#include "collection_diagnostics.h"

int main(int argc,char **argv) {
    if(argc>1&&!strcmp(argv[1],"--disabled")){
        _putenv_s("PSX_COLLECTION_METRICS","0");
        collection_metrics_guest_tick(10);collection_metrics_swap(0);
        char json[32768];assert(collection_metrics_json(json,sizeof(json),0));
        assert(strstr(json,"\"metrics_enabled\":false")&&strstr(json,"\"samples\":[]"));
        assert(collection_metrics_swap_count()==0);
        puts("PASS: metrics-off observer control records no swaps");return 0;
    }
    _putenv_s("PSX_COLLECTION_METRICS","");
    _putenv_s("PSX_COLLECTION_DIAGNOSTICS", "");
    _putenv_s("PSX_GL_PERF", "");
    assert(!collection_diagnostic_enabled("PSX_GL_PERF"));
    _putenv_s("PSX_COLLECTION_DIAGNOSTICS", "1");
    assert(collection_diagnostic_enabled("PSX_GL_PERF"));
    _putenv_s("PSX_GL_PERF", "0");
    assert(!collection_diagnostic_enabled("PSX_GL_PERF"));
    _putenv_s("PSX_COLLECTION_DIAGNOSTICS", "");
    _putenv_s("PSX_GL_PERF", "1");
    assert(collection_diagnostic_enabled("PSX_GL_PERF"));
    _putenv_s("PSX_GL_PERF", "");
    char json[32768];
    assert(collection_metrics_json(json,sizeof(json),0));
    assert(strstr(json,"\"samples\":[]"));
    collection_metrics_guest_tick(99);
    for(int i=1;i<=300;++i)collection_metrics_swap(i%3==0);
    assert(collection_metrics_swap_count()==300);
    assert(collection_metrics_json(json,sizeof(json),298));
    assert(strstr(json,"\"guest_frame\":99"));
    assert(strstr(json,"\"generated_swap_calls\":100"));
    assert(strstr(json,"\"physical_presents\":null"));
    assert(strstr(json,"\"samples\":[[299,"));
    assert(strstr(json,"],[300,"));
    assert(collection_metrics_json(json,sizeof(json),0));
    assert(strstr(json,"\"samples\":[[45,"));
    assert(!collection_metrics_json(json,32,0));
    puts("PASS: diagnostic opt-ins, independent swap counts, ring wrap, sequence filtering, bounded output");
    return 0;
}
