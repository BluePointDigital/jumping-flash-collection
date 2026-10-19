"""Verified SDK payloads installed into a selected BIOS's kernel RAM."""
import hashlib
import struct
from pathlib import Path
from bios_aot import resident_record

JF2_BOOT_SHA='08b7af5208fc40eac532ec62b2f0bf02ea4d9c0d7ee4043bbd0e4c833beb38d8'
PAL_BIOS_SHA='1faaa18fa820a0225e488d9f086296b8e6c46df739666093987ff7d8fd352c09'
ROBBIT_BOOT_SHA='705ff577f06f7e696ee7ececbfd7dd8a3215b84e74d0bd3d625d8f79ab401cc3'
JP_BIOS_SHA='9c0421858e217805f4abe18698afea8d5aa36ff0727eb8484944e00eb5e7eadb'
ROBBIT_INSTALLER_SHA='ebca3d8753d423fe0a3dfbd4c0189a83068ab67dbbf77a8a6d95beea308413cb'
ROBBIT_PAYLOADS=[
    ('SDK/CARD-6444',0x6444,0x8001e380,20,'b36de06c1ca67f8de8d55e2b94471d8e303ec65e824241960490f69dc87ef06a'),
    ('SDK/PAD-4D98',0x4d98,0x8001e394,20,'f36310f78a7d75f8252fc57ea2a5f81016e786750dbffa4787d41dfda2e38270'),
    ('SDK/DRIVER-DF80',0xdf80,0x8001e310,112,'f88eb04a75e4335fe5a48cba7c7d1468959f836c5c08ceeedbd644ab08dfca0a'),
]
INSTALLER=(0x3c018004,0xac3f5a20,0x0c008fd4,0,0x240a00b0,0x0140f809,0x24090056,
    0x3c0a8003,0x3c098003,0x8c420018,0x254a8024,0x2529805c,
    0x8d430000,0x254a0004,0x24420004,0x1549fffc,0xac43fffc,
    0x0c00a017,0,0x0c00907c,0,0x3c1f8004,0x8fff5a20,0,0x03e00008,0)
PAYLOAD=(0,0,0x241a0100,0x8f5a0008,0,0x8f5a0000,0,0x235a0008,
    0xaf410004,0xaf420008,0xaf43000c,0xaf5f007c,0x40026800,0)


def installed_sdk_records(game,boot_exe,bios_path,expected_bios_sha256):
    if game=='robbit':return installed_robbit_records(boot_exe,bios_path,expected_bios_sha256)
    if game!='jf2':return [],[]
    if not isinstance(boot_exe,bytes):raise ValueError('Verified SDK boot executable is missing')
    bios=Path(bios_path).read_bytes();bios_sha=hashlib.sha256(bios).hexdigest()
    source_sha=hashlib.sha256(boot_exe).hexdigest()
    if len(bios)!=0x80000 or bios_sha!=expected_bios_sha256 or bios_sha!=PAL_BIOS_SHA or source_sha!=JF2_BOOT_SHA:
        raise ValueError('SDK installed-code preparation requires the exact supported boot executable and BIOS')
    if boot_exe[:8]!=b'PS-X EXE' or struct.unpack_from('<I',boot_exe,0x18)[0]!=0x80018000:
        raise ValueError('SDK source executable layout changed')
    def read(pc,size):
        offset=2048+pc-0x80018000
        if offset<2048 or offset+size>len(boot_exe):raise ValueError('SDK source outside executable')
        return boot_exe[offset:offset+size]
    constructor=read(0x80027fbc,len(INSTALLER)*4);payload=read(0x80028024,len(PAYLOAD)*4)
    if struct.unpack('<26I',constructor)!=INSTALLER or struct.unpack('<14I',payload)!=PAYLOAD:
        raise ValueError('SDK copy constructor or literal payload changed')
    # B0:56 names RAM65C, whose getter returns C0 table674. Its entry6
    # selects C80. This verifies the copy destination independently of a trace.
    if (struct.unpack_from('<I',bios,0x104cc)[0]!=0x65c or
        struct.unpack_from('<3I',bios,0x1015c)!=(0x3c020000,0x03e00008,0x24420674) or
        struct.unpack_from('<I',bios,0x1018c)[0]!=0xc80):
        raise ValueError('BIOS B0/C0 lookup no longer establishes the SDK patch destination')
    code=payload[8:];record=resident_record('SDK/GTE-C88',0xc88,code,bios_sha)
    proof=dict(name=record['producer_name'],bios_sha256=bios_sha,source_executable_sha256=source_sha,
        constructor_address='0x80027FBC',constructor_sha256=hashlib.sha256(constructor).hexdigest(),
        source_address='0x8002802C',installed_range=['0xC88','0xCB8'],code_sha256=hashlib.sha256(code).hexdigest(),
        transform='Verified SDK copy of fourteen words to the BIOS C0:6 handler; compile its changed C88..CB8 interval',
        runtime_capture_used=False)
    return [record],[proof]


def installed_robbit_records(boot_exe,bios_path,expected_bios_sha256):
    if not isinstance(boot_exe,bytes):raise ValueError('Verified SDK boot executable is missing')
    bios=Path(bios_path).read_bytes();bios_sha=hashlib.sha256(bios).hexdigest()
    source_sha=hashlib.sha256(boot_exe).hexdigest()
    if (len(bios)!=0x80000 or bios_sha!=expected_bios_sha256 or bios_sha!=JP_BIOS_SHA or
        source_sha!=ROBBIT_BOOT_SHA or boot_exe[:8]!=b'PS-X EXE' or
        struct.unpack_from('<I',boot_exe,0x18)[0]!=0x80014800):
        raise ValueError('Robbit SDK requires the exact supported boot executable and Japanese BIOS')
    def read(pc,size):
        offset=2048+pc-0x80014800
        if offset<2048 or offset+size>len(boot_exe):raise ValueError('Robbit SDK source outside executable')
        return boot_exe[offset:offset+size]
    constructor=read(0x8001e3a8,0x138)
    if hashlib.sha256(constructor).hexdigest()!=ROBBIT_INSTALLER_SHA:
        raise ValueError('Robbit SDK copy constructors changed')
    from bios_aot import installed_records
    installed_records(bios_path,expected_bios_sha256) # Pins the CF0 installer whose target identifies CARD+28.
    if (struct.unpack_from('<2I',bios,0x104cc)!=(0x65c,0x668) or
        struct.unpack_from('<6I',bios,0x1015c)!=(0x3c020000,0x03e00008,0x24420674,0x3c020000,0x03e00008,0x24420874) or
        struct.unpack_from('<I',bios,0x1018c)[0]!=0xc80 or
        struct.unpack_from('<I',bios,0x104e0)[0]!=0x43d0):
        raise ValueError('BIOS lookup no longer establishes Robbit SDK destinations')
    records=[];proofs=[]
    for name,destination,source,size,payload_sha in ROBBIT_PAYLOADS:
        code=read(source,size)
        if hashlib.sha256(code).hexdigest()!=payload_sha:raise ValueError('Robbit SDK literal payload changed')
        record=resident_record(name,destination,code,bios_sha)
        if destination==0xdf80:
            # The two installed stubs enter separate halves of this copied driver.
            for segment,entries in record['dispatch_entry_segments'].items():
                entries.append(f'0x{(int(entries[0],16)&0xe0000000)|0xdfac:08X}')
            for key in ('dispatch_entry_pcs','static_dispatch_entry_pcs','function_entry_pcs','seeds'):
                record[key]=list(record['dispatch_entry_segments']['kseg0'])
        proof=dict(name=name,bios_sha256=bios_sha,source_executable_sha256=source_sha,
            constructor_address='0x8001E3A8',constructor_sha256=ROBBIT_INSTALLER_SHA,
            source_address=f'0x{source:08X}',installed_range=[hex(destination),hex(destination+size)],
            code_sha256=payload_sha,transform='Verified SDK copies: C0:6 -> installed CF0 target 641C + 28; B0:5B -> 43D0 + 9C8; literal DF80 driver',
            runtime_capture_used=False)
        records.append(record);proofs.append(proof)
    return records,proofs
