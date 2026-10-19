"""Derive installed code from verified BIOS constructors, never live captures."""
import base64
import hashlib
import struct
from pathlib import Path

SUPPORTED_BIOS={
    '71af94d1e47a68c11e8fdb9f8368040601514a42a5a399cda48c7d3bff1e99d3',
    '1faaa18fa820a0225e488d9f086296b8e6c46df739666093987ff7d8fd352c09',
    '9c0421858e217805f4abe18698afea8d5aa36ff0727eb8484944e00eb5e7eadb',
}
SIO_INSTALLER=(
    0x3c010000,0x3c020000,0x3c1a0000,0x3c1b0000,0xac2075c0,
    0x24420cf0,0x275a6408,0x277b6418,0x8f430000,0x275a0004,
    0x24420004,0x175bfffc,0xac43fffc,0x08001a9c,0,
    0x3c020000,0x8c4275c0,0x03e00008,0,
)
SIO_WORDS=(0x3c020000,0x2442641c,0x0040f809,0)
VECTOR_INSTALLER=(0x3c028000,0x3c1a0000,0x3c1b0000,0x34420080,
    0x275a0f0c,0x277b0f1c,0x8f430000,0x275a0004,0x24420004,0x175bfffc,0xac43fffc)
VECTOR_WORDS=(0x3c1a0000,0x275a0c80,0x03400008,0)


def installed_records(bios_path,expected_sha256):
    bios=Path(bios_path).read_bytes()
    digest=hashlib.sha256(bios).hexdigest()
    if len(bios)!=0x80000 or digest!=expected_sha256 or digest not in SUPPORTED_BIOS:
        raise ValueError('Installed-code preparation requires the exact supported BIOS import')
    records=[];evidence=[]
    for name,destination,constructor,source,expected,words in [
        ('BIOS/SIO-CF0',0xcf0,0x15ebc,0x15f08,SIO_INSTALLER,SIO_WORDS),
        ('BIOS/EXCEPTION-80',0x80,0x109b0,0x10a0c,VECTOR_INSTALLER,VECTOR_WORDS),
    ]:
        installer=bios[constructor:constructor+len(expected)*4];code=bios[source:source+16]
        if struct.unpack(f'<{len(expected)}I',installer)!=expected or struct.unpack('<4I',code)!=words:
            raise ValueError(f'{name}: constructor or source differs from the verified copy recipe')
        record,proof=_copy_record(name,destination,constructor,source,installer,code,digest)
        records.append(record);evidence.append(proof)
    return records,evidence


def _copy_record(name,destination,constructor,source,installer,code,digest):
    # Both exact constructors copy a 16-byte interval from the relocated
    # part-2 BIOS image (ROM 10000 -> RAM 500) to the declared destination.
    record=resident_record(name,destination,code,digest)
    evidence=dict(name=record['producer_name'],bios_sha256=digest,
        constructor_rom_offset=f'0x{constructor:X}',constructor_bytes=len(installer),
        constructor_sha256=hashlib.sha256(installer).hexdigest(),
        source_rom_offset=f'0x{source:X}',source_ram_range=[f'0x{source-0x10000+0x500:X}',f'0x{source-0x10000+0x510:X}'],
        installed_range=[f'0x{destination:X}',f'0x{destination+len(code):X}'],code_sha256=hashlib.sha256(code).hexdigest(),
        transform='Exact BIOS kernel relocation followed by verified four-word copy loop',
        runtime_capture_used=False)
    return record,evidence


def resident_record(name,destination,code,digest):
    if destination%4 or destination<0 or not code or len(code)%4 or destination+len(code)>0x10000:
        raise ValueError('Resident code must be word-aligned inside kernel RAM')
    entries={name:[f'0x{seg|destination:08X}'] for name,seg in
             [('kuseg',0),('kseg0',0x80000000),('kseg1',0xa0000000)]}
    return dict(schema='psxrecomp overlay capture v3',producer='bios_resident_manifest',
        producer_name=name,bios_sha256=digest,load_addr=f'0x{0x80000000|destination:08X}',size=len(code),
        bytes_b64=base64.b64encode(code).decode(),executed_pcs=[],
        dispatch_entry_pcs=entries['kseg0'],static_dispatch_entry_pcs=entries['kseg0'],
        function_entry_pcs=entries['kseg0'],seeds=entries['kseg0'],
        dispatch_entry_segments=entries,
        producer_ranges=[dict(start=f'0x{0x80000000|destination:08X}',end=f'0x{0x80000000|(destination+len(code)):08X}')])
