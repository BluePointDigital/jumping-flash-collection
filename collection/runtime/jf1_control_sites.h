#pragma once
#include <stdint.h>
// Generated from the same verified layouts as jf1_profiles.h. This is a prefilter, not a code-identity guard.
static inline int jf1_control_site(uint32_t address){address&=0x1fffffffu;
if(address-0xca514u>0x17a1cu)return 0;
switch(address){
case 0xca514u:
case 0xca978u:
case 0xcb1a8u:
case 0xcb2b0u:
case 0xd9d2cu:
case 0xda190u:
case 0xda9c0u:
case 0xdaac8u:
case 0xdc144u:
case 0xdc154u:
case 0xdc2b0u:
case 0xdc2c8u:
case 0xdc4c4u:
case 0xdc5a8u:
case 0xdc5b8u:
case 0xdc714u:
case 0xdc72cu:
case 0xdc928u:
case 0xdcdd8u:
case 0xdcde8u:
case 0xdcee0u:
case 0xdcef0u:
case 0xdcf44u:
case 0xdcf5cu:
case 0xdd04cu:
case 0xdd064u:
case 0xdd158u:
case 0xdd260u:
case 0xe1098u:
case 0xe1194u:
case 0xe14fcu:
case 0xe15f8u:
case 0xe1d2cu:
case 0xe1e28u:
case 0xe1e34u:
case 0xe1f30u:
return 1;default:return 0;}}
