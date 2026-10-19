"""Resolve a crash report RVA against the built binary's COFF symbols."""
from pathlib import Path
import argparse
import struct
parser=argparse.ArgumentParser();parser.add_argument('exe',type=Path);parser.add_argument('rva',nargs='+');args=parser.parse_args()
data=args.exe.read_bytes();pe=struct.unpack_from('<I',data,60)[0]
machine,sections,stamp,pointer,count,optional,flags=struct.unpack_from('<HHIIIHH',data,pe+4)
table=pe+24+optional;strings=pointer+count*18;symbols=[];index=0
while index<count:
    offset=pointer+index*18;name=data[offset:offset+8]
    if name[:4]==b'\0'*4:
        start=strings+struct.unpack_from('<I',name,4)[0];name=data[start:data.find(b'\0',start)]
    value,section,kind,storage,aux=struct.unpack_from('<IhHBB',data,offset+8)
    if 0<section<=sections:
        rva=struct.unpack_from('<I',data,table+(section-1)*40+12)[0]+value
        symbols.append((rva,name.decode('utf-8',errors='replace')))
    index+=1+aux
symbols.sort()
for value in args.rva:
    rva=int(value,16);near=[s for s in symbols if s[0]<=rva]
    print(value,near[-3:],f'+{rva-near[-1][0]:X}' if near else 'no symbols')
