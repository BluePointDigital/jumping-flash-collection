"""Local disc translation and lossless ISO9660 inventory. Never edits the source."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.workbench'


def apply_bps(source, patch):
    if len(patch) < 19 or patch[:4] != b'BPS1':
        raise ValueError('Not a BPS patch')
    source_crc, target_crc, patch_crc = struct.unpack_from('<III', patch, len(patch)-12)
    if zlib.crc32(patch[:-4]) != patch_crc or zlib.crc32(source) != source_crc:
        raise ValueError('Patch/source checksum mismatch')
    cursor, end = 4, len(patch)-12

    def number():
        nonlocal cursor
        value, shift = 0, 1
        while cursor < end:
            byte = patch[cursor]
            cursor += 1
            value += (byte & 127) * shift
            if byte & 128:
                return value
            shift <<= 7
            value += shift
        raise ValueError('Truncated BPS number')

    source_size, target_size, metadata_size = number(), number(), number()
    if source_size != len(source) or target_size > 1024**3:
        raise ValueError('Unexpected disc size')
    cursor += metadata_size
    if cursor > end:
        raise ValueError('Truncated metadata')
    target = bytearray(target_size)
    output, source_relative, target_relative = 0, 0, 0
    while cursor < end:
        action = number()
        mode, length = action & 3, (action >> 2)+1
        if output + length > target_size:
            raise ValueError('Target overflow')
        if mode == 0:
            if output + length > source_size:
                raise ValueError('Source overflow')
            target[output:output+length] = source[output:output+length]
        elif mode == 1:
            if cursor + length > end:
                raise ValueError('Truncated literal')
            target[output:output+length] = patch[cursor:cursor+length]
            cursor += length
        else:
            offset = number()
            delta = (offset >> 1) * (-1 if offset & 1 else 1)
            if mode == 2:
                source_relative += delta
                if source_relative < 0 or source_relative + length > source_size:
                    raise ValueError('Invalid source copy')
                target[output:output+length] = source[source_relative:source_relative+length]
                source_relative += length
            else:
                target_relative += delta
                if not 0 <= target_relative < output:
                    raise ValueError('Invalid target copy')
                # Copy existing spans, including BPS overlapping run-length copies.
                written = 0
                while written < length:
                    span = min(length-written, output+written-target_relative, 1024*1024)
                    target[output+written:output+written+span] = target[target_relative:target_relative+span]
                    written += span
                    target_relative += span
        output += length
    if output != target_size or zlib.crc32(target) != target_crc:
        raise ValueError('Target size/checksum mismatch')
    return target


def translate():
    original = WORK / 'disc/original/Robbit mon Dieu (Japan).bin'
    patch_path = WORK / 'translation/v0.4/Robbit-English-v0.4.bps'
    destination = WORK / 'disc/english'
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / 'Robbit mon Dieu (English).bin'
    if output.exists():
        raise FileExistsError(f'Preserving existing translated disc: {output}')
    patch = patch_path.read_bytes()
    with original.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as source:
        source_sha1 = hashlib.sha1(source).hexdigest()
        if source_sha1 != '355a7db069bd51b205cf9c4226a017dbd933c148':
            raise ValueError('Unexpected Robbit source identity')
        result = apply_bps(source, patch)
    temporary = output.with_suffix('.partial')
    temporary.write_bytes(result)
    temporary.replace(output)
    (destination / 'Robbit mon Dieu (English).cue').write_text(
        'FILE "Robbit mon Dieu (English).bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n', encoding='utf-8')
    receipt = dict(author='washingtonxan', version='0.4', source_sha1=source_sha1,
                   patch_sha256=hashlib.sha256(patch).hexdigest(),
                   output_sha256=hashlib.sha256(result).hexdigest(), bytes=len(result),
                   checksums_verified=['source CRC32', 'patch CRC32', 'target CRC32'],
                   url='https://romhackplaza.org/translations/robbit-mon-dieu-english-translation-playstation')
    (WORK / 'evidence/translation.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


def inventory(language):
    directory = WORK / 'disc' / language
    bins = list(directory.glob('*.bin'))
    if len(bins) != 1:
        raise ValueError('Expected one data track')
    destination = WORK / 'disc-files' / language
    destination.mkdir(parents=True, exist_ok=True)
    records, seen = [], set()
    with bins[0].open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as disc:
        def read(lba, size):
            if lba < 0 or (lba+(size+2047)//2048)*2352 > len(disc):
                raise ValueError('Extent outside disc')
            return b''.join(disc[s*2352+24:s*2352+2072]
                            for s in range(lba, lba+(size+2047)//2048))[:size]

        def walk(lba, size, prefix=Path()):
            if (lba, size) in seen:
                raise ValueError('Directory cycle')
            seen.add((lba, size))
            data, offset = read(lba, size), 0
            while offset < len(data):
                count = data[offset]
                if not count:
                    offset = (offset//2048+1)*2048
                    continue
                if count < 34 or offset+count > len(data):
                    raise ValueError('Malformed directory record')
                row = data[offset:offset+count]
                offset += count
                name = row[33:33+row[32]]
                if name in (b'\0', b'\1'):
                    continue
                name = name.decode('ascii').split(';')[0]
                if not name or name in ('.', '..') or any(c in name for c in '/\\:'):
                    raise ValueError('Unsafe ISO filename')
                extent, length = struct.unpack_from('<I', row, 2)[0], struct.unpack_from('<I', row, 10)[0]
                relative = prefix / name
                if row[25] & 2:
                    walk(extent, length, relative)
                else:
                    payload = read(extent, length)
                    path = destination / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.exists() and path.read_bytes() != payload:
                        raise ValueError(f'Preserving conflicting file: {path}')
                    path.write_bytes(payload)
                    records.append(dict(path=relative.as_posix(), lba=extent, bytes=length,
                                        sha256=hashlib.sha256(payload).hexdigest(),
                                        psx_exe=payload[:8] == b'PS-X EXE'))
        pvd = read(16, 2048)
        if pvd[1:6] != b'CD001':
            raise ValueError('Expected ISO9660 volume')
        walk(struct.unpack_from('<I', pvd, 158)[0], struct.unpack_from('<I', pvd, 166)[0])
    (WORK / f'evidence/inventory-{language}.json').write_text(json.dumps(records, indent=2)+'\n')
    print(f'{language}: {len(records)} files, {sum(x["bytes"] for x in records)} bytes, '
          f'{sum(x["psx_exe"] for x in records)} PS-X executables')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['translate', 'inventory'])
    parser.add_argument('--language', choices=['original', 'english'], default='original')
    args = parser.parse_args()
    translate() if args.command == 'translate' else inventory(args.language)
