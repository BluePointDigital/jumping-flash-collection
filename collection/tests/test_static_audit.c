#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "collection_static.h"

int main(int argc,char **argv){
    const char *mode=argc>1?argv[1]:"off";
    _putenv_s("PSX_STATIC_AUDIT",mode);_putenv_s("PSX_STATIC_AUDIT_REPORT",argc>3?argv[3]:"");
    collection_static_init();
    if(argc>2&&!strcmp(argv[2],"compiler")){
        collection_static_compiler_request();return 7; /* strict must exit before this */
    }
    if(argc>2&&!strcmp(argv[2],"oracle")){
        collection_static_interpreter(2,0xbfc01000,0,0,0);return 7;
    }
    char json[1024];assert(collection_static_json(json,sizeof(json)));
    if(!strcmp(mode,"off")){
        assert(!collection_static_interpreter(1,0x80010000,0,0,0));collection_static_compiler_request();
        assert(collection_static_json(json,sizeof(json)));
        assert(strstr(json,"\"enabled\":false")&&strstr(json,"\"no_fallback_observed\":false"));
        assert(strstr(json,"\"dirty_instruction_attempts\":0"));
    }else{
        assert(strstr(json,"\"no_fallback_observed\":true"));
        assert(collection_static_interpreter(1,0xa0030000,0x03e00008,0x80010010,22));
        assert(!collection_static_interpreter(1,0xa0030004,0,0x80010010,22)); /* nested delay slot */
        assert(!collection_static_interpreter(2,0xbfc01000,0,0,0));
        collection_static_compiler_request();
        assert(collection_static_json(json,sizeof(json)));
        assert(strstr(json,"\"dirty_instruction_attempts\":2"));
        assert(strstr(json,"\"oracle_instruction_attempts\":1"));
        assert(strstr(json,"\"compiler_requests\":1"));
        assert(strstr(json,"0xA0030000")&&strstr(json,"\"frame\":22"));
        assert(strstr(json,"\"no_fallback_observed\":false"));
    }
    assert(!collection_static_json(json,16));
    puts("PASS: static audit modes, exact first-PC identity, both interpreters, compiler requests and bounded output");
    return 0;
}
