#pragma once
#include "robbit_profiles.h"

template<class Read> inline bool robbit_profile_matches(const RobbitProfile& profile,Read read){
    for(const auto& guard:profile.guards){
        const uint64_t end=uint64_t(guard.address)+uint64_t(guard.words)*4;
        if(!guard.words||(guard.address&3)||guard.address<0x80000000u||end>0x80200000ull)return false;
        if(read(guard.address)!=guard.first||read(uint32_t(end)-4)!=guard.last)return false;
        uint64_t hash=14695981039346656037ull;
        for(uint32_t i=0;i<guard.words;++i){
            const uint32_t word=read(guard.address+i*4);
            for(unsigned shift=0;shift<32;shift+=8)hash=(hash^uint8_t(word>>shift))*1099511628211ull;
        }
        if(hash!=guard.hash)return false;
    }
    return true;
}

inline bool robbit_profile_site(const RobbitProfile& profile,uint32_t pc){
    pc&=0x1fffffffu;
    return pc==(profile.update&0x1fffffffu)||pc==(profile.pitch&0x1fffffffu)||
        pc==(profile.vector&0x1fffffffu)||pc==(profile.rotation_return&0x1fffffffu);
}

template<class Read> inline const RobbitProfile* robbit_find_profile(const RobbitProfile* previous,Read read){
    if(previous&&robbit_profile_matches(*previous,read))return previous;
    for(const auto& candidate:robbit_profiles)if(&candidate!=previous&&robbit_profile_matches(candidate,read))return &candidate;
    return nullptr;
}
