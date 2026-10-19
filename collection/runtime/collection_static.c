/* Opt-in qualification observer. Stops before interpreted execution in strict mode. */
#include "collection_static.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int collection_static_mode;
static _Atomic uint64_t dirty_attempts,oracle_attempts,compiler_requests;
static atomic_flag first_claimed=ATOMIC_FLAG_INIT;
static _Atomic int first_ready;
static uint32_t first_pc,first_instruction,first_ra;
static uint64_t first_frame;
static int first_backend;
static char report_path[4096];

int collection_static_json(char *out,int capacity){
    if(!out||capacity<=0)return 0;
    const uint64_t dirty=atomic_load(&dirty_attempts),oracle=atomic_load(&oracle_attempts);
    const uint64_t compiler=atomic_load(&compiler_requests);
#ifdef PSX_SHELLWIN_INTERP_DEFAULT
    const int shellwin_default=1;
#else
    const int shellwin_default=0;
#endif
    char first[256]="null";
    if(atomic_load_explicit(&first_ready,memory_order_acquire))
        snprintf(first,sizeof(first),"{\"backend\":\"%s\",\"pc\":\"0x%08X\",\"instruction\":\"0x%08X\",\"ra\":\"0x%08X\",\"frame\":%llu}",
            first_backend==1?"dirty_ram":"oracle",first_pc,first_instruction,first_ra,(unsigned long long)first_frame);
    int n=snprintf(out,capacity,
        "\"schema\":1,\"enabled\":%s,\"mode\":\"%s\",\"scope\":\"process_lifetime\","
        "\"semantics\":\"interpreter instruction attempts, including delay slots; compiler requests before spawn\","
        "\"dirty_instruction_attempts\":%llu,\"oracle_instruction_attempts\":%llu,\"compiler_requests\":%llu,"
        "\"no_fallback_observed\":%s,\"qualification_complete\":false,\"shellwin_forced_build\":%s,\"first_interpreter\":%s",
        collection_static_mode?"true":"false",collection_static_mode==2?"strict":collection_static_mode==1?"observe":"off",
        (unsigned long long)dirty,(unsigned long long)oracle,(unsigned long long)compiler,
        collection_static_mode&&!dirty&&!oracle&&!compiler?"true":"false",shellwin_default?"true":"false",first);
    return n>=0&&n<capacity?n:0;
}

static void write_report(void){
    if(!report_path[0])return;
    char json[1024];
    if(!collection_static_json(json,sizeof(json)))abort();
    FILE *file=fopen(report_path,"wb");
    if(!file){fprintf(stderr,"Static audit cannot write report: %s\n",report_path);fflush(stderr);_Exit(74);}
    int failed=fprintf(file,"{%s}\n",json)<0;
    if(fclose(file))failed=1;
    if(failed){fprintf(stderr,"Static audit report write failed: %s\n",report_path);fflush(stderr);_Exit(74);}
}

void collection_static_init(void){
    const char *mode=getenv("PSX_STATIC_AUDIT");
    if(!mode||!*mode||!strcmp(mode,"off")||!strcmp(mode,"0"))return;
    if(!strcmp(mode,"observe"))collection_static_mode=1;
    else if(!strcmp(mode,"strict"))collection_static_mode=2;
    else {fputs("PSX_STATIC_AUDIT must be off, observe or strict\n",stderr);exit(64);}
    const char *path=getenv("PSX_STATIC_AUDIT_REPORT");
    if(path&&*path){
        if(strlen(path)>=sizeof(report_path)){fputs("Static audit report path too long\n",stderr);exit(64);}
        strcpy(report_path,path);
    }
    atexit(write_report);
    write_report();
}

static void violation(const char *reason){
    char json[1024];collection_static_json(json,sizeof(json));write_report();
    fprintf(stderr,"PSX_STATIC_VIOLATION %s {%s}\n",reason,json);fflush(stderr);
    exit(86);
}

int collection_static_interpreter(int backend,uint32_t pc,uint32_t instruction,uint32_t ra,uint64_t frame){
    if(!collection_static_mode)return 0;
    if(backend==1)atomic_fetch_add(&dirty_attempts,1);else atomic_fetch_add(&oracle_attempts,1);
    int first=!atomic_flag_test_and_set_explicit(&first_claimed,memory_order_relaxed);
    if(first){
        first_pc=pc;first_instruction=instruction;first_ra=ra;first_frame=frame;first_backend=backend;
        atomic_store_explicit(&first_ready,1,memory_order_release);
        write_report();
    }
    if(collection_static_mode==2)violation("interpreter");
    return first;
}

void collection_static_compiler_request(void){
    if(!collection_static_mode)return;
    atomic_fetch_add(&compiler_requests,1);
    if(collection_static_mode==2)violation("compiler_request");
}
