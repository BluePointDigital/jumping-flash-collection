#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
namespace jf1 {
inline int wrap(int angle){return ((angle+2048)&4095)-2048;}
inline int heading(float x,float forward){return (int)std::lround(std::atan2(x,forward)*4096/(2*3.141592653589793));}
inline float magnitude(float x,float forward){return std::min(1.f,std::hypot(x,forward));}
struct Look {
    double dx=0,dy=0,pitch=0;bool initialized=false;
    void clear(){dx=dy=0;initialized=false;}
    void move(double x,double y){dx+=x;dy+=y;}
    int update(int yaw,int native_pitch,int sensitivity,bool invert){
        if(!initialized){pitch=native_pitch;initialized=true;}
        const double factor=sensitivity/100.;
        yaw=wrap(yaw+(int)std::lround(dx*factor));
        pitch=std::clamp(pitch+dy*factor*(invert?-1:1),-896.,768.);
        dx=dy=0;return yaw;
    }
};
inline bool manual(uint32_t demo,uint32_t live,uint32_t pause,uint32_t block,
                   uint32_t finish,uint32_t finish2,uint32_t movie,uint32_t ready){
    return demo==0&&live==1&&pause==0&&block==0&&finish==0&&finish2==0&&(movie!=0||ready!=0);
}
}
