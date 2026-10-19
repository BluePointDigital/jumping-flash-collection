#include "function_analysis.h"
#include "ps1_exe_parser.h"
#include <cstring>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <vector>

using namespace PSXRecomp;
static void require_at(bool value,int line) {
    if (!value) { std::fprintf(stderr,"inclusive assertion at line %d\n",line);
        throw std::runtime_error("inclusive emitter assertion"); }
}
#define require(value) require_at((value),__LINE__)
static void put(std::vector<uint8_t>& data, size_t offset, uint32_t word) {
    for (unsigned i=0;i<4;++i) data.at(offset+i)=uint8_t(word>>(8*i));
}
static PS1Executable parse(const std::vector<uint8_t>& data) {
    std::string error;auto exe=PS1ExeParser::parse_buffer(data,error);
    require(exe.has_value());return *exe;
}
static std::vector<uint8_t> fixture(uint32_t load) {
    std::vector<uint8_t> data(2048+128);std::memcpy(data.data(),"PS-X EXE",8);
    put(data,0x10,load+32);put(data,0x18,load);put(data,0x1c,128);
    for(unsigned i=0;i<3;++i) {
        put(data,2048+4*i,load+76+8*i);put(data,2048+76+8*i,0x03e00008);
    }
    const uint32_t words[]={0x34020002,0x0043102b,0x1440000c,0x00031080,
        0x3c010000|((load+0x8000)>>16),0x24210000|(load&0xffff),
        0x00220821,0x8c220000,0,0x00400008,0};
    for(unsigned i=0;i<11;++i)put(data,2048+32+4*i,words[i]);
    return data;
}
static bool resolve(const std::vector<uint8_t>& bytes,uint32_t load, ExactJumpTable& table) {
    const auto exe=parse(bytes);
    return resolve_exact_bounded_jump_table(exe,load+32,load+100,load+68,2,table);
}
int main(int argc,char** argv) {
    for(uint32_t load:{0x80010000u,0x80018000u}) {
        auto data=fixture(load);ExactJumpTable table;
        require(resolve(data,load,table));require(table.table_count==3);
        require(table.table_base==load);require(table.targets.at(0).second==load+76);
        auto loop=data;put(loop,2048+84,0x08000000|((load+36)>>2&0x03ffffff));
        put(loop,2048+88,0x34020002);require(resolve(loop,load,table));
        for(auto change:std::vector<std::pair<unsigned,uint32_t>>{
            {32,0x34021000},{36,0x0043102a},{40,0x1040000c},
            {44,0x000310c0},{60,0x8c220004},{64,0x24020001},
            {72,0x24020001},{0,load+68},{4,load+101},
            {48,0x3c010000|(((load+0x8000)>>16)^1)}}) {
            auto bad=data;put(bad,2048+change.first,change.second);
            require(!resolve(bad,load,table));
        }
        for(auto target:{load+36,load+44,load+52}) {
            auto bad=data;put(bad,2048+84,0x08000000|(target>>2&0x03ffffff));
            put(bad,2048+88,0x34020003);require(!resolve(bad,load,table));
        }
        auto delay=data;put(delay,2048+4,load+80);require(!resolve(delay,load,table));
        const auto exe=parse(data);
        require(!resolve_exact_bounded_jump_table(exe,load+32,load+100,load+68,2,table,nullptr,load+4,load+128));
    }
    // Optional original, decoded JM1 bytes exercise the actual failing switch.
    if(argc==2 || argc==8) {
        std::ifstream file(argv[1],std::ios::binary);
        std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)),{});
        const auto exe=parse(bytes);ExactJumpTable table;
        auto number=[&](int i) { return uint32_t(std::stoul(argv[i],nullptr,0)); };
        require(resolve_exact_bounded_jump_table(exe,argc==2?0x800b1788:number(2),
            argc==2?0x800b1b28:number(3),argc==2?0x800b17cc:number(4),
            argc==2?2:number(5),table));
        require(table.table_base==(argc==2?0x800b0070:number(6)) &&
            table.table_count==(argc==2?7:number(7)));
        if(argc==2) {
            bool found=false;for(auto pair:table.targets)found|=pair.second==0x800b1ad0;
            require(found);
        }
    }
    return 0;
}
