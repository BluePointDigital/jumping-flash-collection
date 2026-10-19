"""Prepare exact game-constructed code variants from independently verified sources."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct

PALETTE_LAYOUTS={};LAYOUTS_SHA={}
for _game,_serial in [('jf1','SCUS-94103'),('jf2','SCES-00111')]:
    _layout_bytes=(Path(__file__).resolve().parents[1]/f'runtime/{_game}_initialized_images.json').read_bytes()
    _layout_document=json.loads(_layout_bytes)
    if (_layout_document.get('schema'),_layout_document.get('game'),_layout_document.get('serial'))!=(1,_game,_serial):
        raise ValueError('Unsupported installed-image layout descriptor')
    PALETTE_LAYOUTS[_game]=_layout_document['images']
    LAYOUTS_SHA[_game]=hashlib.sha256(_layout_bytes).hexdigest()


def installed_game_records(game,name,source_sha,load,body):
    if name not in PALETTE_LAYOUTS.get(game,{}):return [],[]
    layout=PALETTE_LAYOUTS[game][name]
    if load!=int(layout['load_addr'],16) or hashlib.sha256(body).hexdigest()!=layout['body_sha256']:
        raise ValueError('Installed palette recipe requires the exact verified world image')
    writer_address=int(layout['writer'],16);constructor=int(layout['constructor'],16)
    template=int(layout['template'],16);argument=int(layout['argument'],16);size=layout['size']
    def read(pc,size):
        offset=pc-load
        if offset<0 or offset+size>len(body):raise ValueError('Palette source outside image')
        return body[offset:offset+size]
    writer=read(writer_address,0x44)
    if hashlib.sha256(writer).hexdigest()!=layout['writer_sha256']:
        raise ValueError('Palette instruction-halfword writer changed')
    init=read(constructor,16)
    if (hashlib.sha256(init).hexdigest()!=layout['constructor_sha256'] or
        struct.unpack('<4I',init)!=(0x3c040000|((argument+0x8000)>>16&0xffff),
            0x24840000|(argument&0xffff),0x0c000000|((writer_address>>2)&0x03ffffff),0)):
        raise ValueError('Palette initialization no longer supplies the verified literal')
    code=bytearray(read(template,size))
    if hashlib.sha256(code).hexdigest()!=layout['template_sha256'] or struct.unpack_from('<2I',code)!=(0x3c080000,0x35080000):
        raise ValueError('Palette template opcode/register fields changed')
    # Execute the source setter's two SH writes for the proven initialization
    # argument. This adds one exact variant; it grants no variable-operand guard.
    struct.pack_into('<H',code,4,argument&0xffff)
    struct.pack_into('<H',code,0,argument>>16)
    entries={label:[f'0x{segment|(template&0x1fffffff):08X}'] for label,segment in
             [('kuseg',0),('kseg0',0x80000000),('kseg1',0xa0000000)]}
    record=dict(schema='psxrecomp overlay capture v3',producer='verified_game_installed_code',
        producer_name=f'GAME/{name.split("/")[0]}-PALETTE-{argument:08X}',source_executable_sha256=source_sha,
        load_addr=f'0x{template:08X}',size=len(code),bytes_b64=base64.b64encode(code).decode(),
        executed_pcs=[],dispatch_entry_pcs=entries['kseg0'],static_dispatch_entry_pcs=entries['kseg0'],
        function_entry_pcs=[],seeds=[],dispatch_entry_segments=entries,
        producer_ranges=[dict(start=f'0x{template:08X}',end=f'0x{template+size:08X}')])
    proof=dict(name=record['producer_name'],source_executable_sha256=source_sha,
        source_decoded_body_sha256=layout['body_sha256'],writer_address=hex(writer_address),
        writer_sha256=layout['writer_sha256'],argument_constructor_address=hex(constructor),layout_descriptor_sha256=LAYOUTS_SHA[game],
        argument_constructor_sha256=hashlib.sha256(init).hexdigest(),argument=hex(argument),
        installed_range=[f'0x{template:08X}',f'0x{template+size:08X}'],code_sha256=hashlib.sha256(code).hexdigest(),
        transform='Verified LUI/ADDIU literal passed to the verified two-SH instruction setter',
        runtime_capture_used=False,coverage_limit='Only the proven initialization value; every emitted guard remains a full exact-byte CRC')
    return [record],[proof]


def initialized_image_record(game,source,source_sha):
    """Keep a native CPS bundle coherent after the verified palette writes."""
    load=int(source['load_addr'],16)
    body=base64.b64decode(source['bytes_b64'],validate=True)
    records,proofs=installed_game_records(game,source['producer_name'],source_sha,load,body)
    if not records:return None,None
    if source.get('producer')!='verified_psx_exe_lz1' or source.get('executed_pcs'):
        raise ValueError('Initialized image requires independent static disc metadata')
    installed=records[0];proof=proofs[0]
    offset=int(installed['load_addr'],16)-load
    variant=bytearray(body)
    variant[offset:offset+installed['size']]=base64.b64decode(installed['bytes_b64'],validate=True)
    result=copy.deepcopy(source)
    result.update(producer='verified_game_installed_code',producer_name=installed['producer_name'].replace('-PALETTE-','-INITIALIZED-'),
        source_executable_sha256=source_sha,bytes_b64=base64.b64encode(variant).decode(),
        required_entry_pcs=[pc for entries in installed['dispatch_entry_segments'].values() for pc in entries])
    for key in ('dispatch_entry_pcs','static_dispatch_entry_pcs'):
        result[key]=sorted(set(result.get(key,[]))|set(installed[key]),key=lambda pc:int(pc,16))
    # The two operand writes do not create new executable segment views.
    # Keep all aliases on the small installed snippet, and inherit image views.
    segments={label:list(entries) for label,entries in source.get('dispatch_entry_segments',{}).items() if entries}
    if not segments:
        pcs=[int(pc,16) for key in ('function_entry_pcs','static_dispatch_entry_pcs','dispatch_entry_pcs') for pc in source.get(key,[])]
        segments={label:[f'0x{pc:08X}' for pc in pcs if pc&0xe0000000==segment]
                  for label,segment in [('kuseg',0),('kseg0',0x80000000),('kseg1',0xa0000000)]
                  if any(pc&0xe0000000==segment for pc in pcs)}
    for label in segments:
        segments[label]=sorted(set(segments[label])|set(installed['dispatch_entry_segments'][label]),key=lambda pc:int(pc,16))
    result['dispatch_entry_segments']=segments
    proof=dict(proof,name=result['producer_name'],image_range=[hex(load),hex(load+len(body))],
        executable_segments=list(segments),
        code_sha256=hashlib.sha256(variant).hexdigest(),
        transform='Full verified world image with only the source-proven palette setter writes; static entry metadata retained',
        coverage_limit='One exact initialized image variant; full native-bundle coherence and exact CRC guards remain required')
    return result,proof


def initialized_compile_record(initialized,source):
    """Carry byte-matched observed admissions as hints, keeping the audit pure."""
    if (initialized.get('producer')!='verified_game_installed_code' or '-INITIALIZED-' not in initialized.get('producer_name','') or
        source.get('producer')!='verified_psx_exe_lz1' or initialized['load_addr']!=source['load_addr'] or initialized['size']!=source['size']):
        raise ValueError('Initialized guidance requires matching verified source/constructed images')
    original=base64.b64decode(source['bytes_b64'],validate=True)
    constructed=base64.b64decode(initialized['bytes_b64'],validate=True)
    if len(original)!=source['size'] or len(constructed)!=len(original):raise ValueError('Initialized guidance image size mismatch')
    load=int(source['load_addr'],16);matched=[];changed=[]
    for raw in source.get('executed_pcs',[]):
        pc=int(raw,16);offset=pc-load
        if pc%4 or offset<0 or offset+16>len(original):raise ValueError('Observed initialized admission outside verified image')
        if original[offset:offset+16]==constructed[offset:offset+16]:matched.append(raw)
        else:changed.append(raw)
    result=copy.deepcopy(initialized);result['executed_pcs']=sorted(set(matched),key=lambda pc:int(pc,16))
    result['dispatch_entry_pcs']=sorted(set(result.get('dispatch_entry_pcs',[]))|set(matched),key=lambda pc:int(pc,16))
    # Each observation was already respelled into its verified source view.
    label={0:'kuseg',0x80000000:'kseg0',0xa0000000:'kseg1'}[load&0xe0000000]
    if matched:
        entries=result.setdefault('dispatch_entry_segments',{}).setdefault(label,[])
        result['dispatch_entry_segments'][label]=sorted(set(entries)|set(matched),key=lambda pc:int(pc,16))
    return result,dict(name=initialized['producer_name'],matched_entries=result['executed_pcs'],
        excluded_changed_prefixes=changed,byte_authority='Unchanged constructed disc-image recipe; runtime bytes are admission guidance only')
