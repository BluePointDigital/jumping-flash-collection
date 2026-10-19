import struct
import unittest
import zlib
from prepare import apply_bps


def number(value):
    result = bytearray()
    while True:
        byte, value = value & 127, value >> 7
        if not value:
            return result + bytes([byte | 128])
        result.append(byte)
        value -= 1


def patch(source, target, actions):
    body = b'BPS1' + number(len(source)) + number(len(target)) + number(0) + actions
    body += struct.pack('<II', zlib.crc32(source), zlib.crc32(target))
    return body + struct.pack('<I', zlib.crc32(body))


class BpsTests(unittest.TestCase):
    def test_all_modes_and_overlap(self):
        source, target = b'ABCDEFGH', b'AB!DE!!!'
        actions = number(4) + number(1) + b'!' + number(6) + number(6)
        actions += number(1) + b'!' + number(7) + number(10)
        self.assertEqual(apply_bps(source, patch(source, target, actions)), target)

    def test_negative_source_offset(self):
        source, target = b'ABCD', b'DA'
        actions = number(2) + number(6) + number(2) + number(9)
        self.assertEqual(apply_bps(source, patch(source, target, actions)), target)

    def test_wrong_source_and_corrupt_patch_rejected(self):
        good = patch(b'AB', b'AB', number(4))
        with self.assertRaises(ValueError):
            apply_bps(b'CD', good)
        with self.assertRaises(ValueError):
            apply_bps(b'AB', good[:-1] + bytes([good[-1] ^ 1]))

    def test_future_target_copy_rejected(self):
        with self.assertRaises(ValueError):
            apply_bps(b'A', patch(b'A', b'A', number(3) + number(0)))


if __name__ == '__main__':
    unittest.main()
