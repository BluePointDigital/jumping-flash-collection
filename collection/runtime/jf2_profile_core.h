#pragma once
#include "jf2_profiles.h"

template<class Read> inline bool jf2_profile_matches(const Jf2Profile& profile,Read read){
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

inline uint32_t jf2_profile_role(const Jf2Profile& p,uint32_t pc){
    pc&=0x1fffffffu;
    if(pc==(p.update&0x1fffffffu))return 0xe1528;
    if(pc==(p.camera&0x1fffffffu))return 0xe7f1c;
    if(pc==(p.pitch&0x1fffffffu))return 0xe2b4c;
    if(pc==(p.movement&0x1fffffffu))return 0xe2550;
    if(pc==(p.restore&0x1fffffffu))return 0xe2b90;
    return 0;
}

template<class Read> inline const Jf2Profile* jf2_find_profile(const Jf2Profile* previous,Read read){
    if(previous&&jf2_profile_matches(*previous,read))return previous;
    for(const auto& candidate:jf2_profiles)if(&candidate!=previous&&jf2_profile_matches(candidate,read))return &candidate;
    return nullptr;
}
