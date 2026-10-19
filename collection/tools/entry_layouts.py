"""Validate recovered entry hints against disc bytes before ordinary analysis."""
import binascii
import hashlib
import json
from pathlib import Path


def nominations(game,disc_sha256,image_name,load,body,profile_path=None):
    if game!='jf1':return []
    path=Path(profile_path) if profile_path else Path(__file__).resolve().parents[1]/'runtime/jf1_entry_layouts.json'
    document=json.loads(path.read_text(encoding='utf-8'))
    if document.get('schema')!=1 or document.get('game')!=game or document.get('disc_sha256')!=disc_sha256:
        raise ValueError('Recovered entry layout does not match the verified disc')
    image=document.get('images',{}).get(image_name)
    if image is None:return []
    if image.get('body_sha256')!=hashlib.sha256(body).hexdigest():raise ValueError('Recovered layout image bytes changed')
    physical=load&0x1fffffff;entries=set()
    for row in image['nominations']:
        entry=int(row['entry'],16);crc=0;contains=False
        if entry%4 or entry&0xe0000000 not in (0,0x80000000,0xa0000000):raise ValueError('Invalid layout entry segment/alignment')
        if not row['ranges']:raise ValueError('Layout entry has no byte guards')
        for address,length in row['ranges']:
            start=int(address,16)&0x1fffffff;offset=start-physical
            if start%4 or not isinstance(length,int) or length<=0 or length%4 or offset<0 or offset+length>len(body):
                raise ValueError('Layout guard outside the verified executable')
            crc=binascii.crc32(body[offset:offset+length],crc)
            contains|=start<=(entry&0x1fffffff)<start+length
        if not contains or crc&0xffffffff!=int(row['code_crc32'],16):raise ValueError('Recovered layout code identity changed')
        entries.add(entry)
    return sorted(entries)
