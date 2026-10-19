"""Bound the native new-game settings write and preserve surrounding state."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class GameOptionsLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = folder / 'options.c'
        source.write_text('''#include "game_options_layout.h"
int apply(uint8_t *owner, size_t size, int32_t seed, float length, uint32_t days, uint32_t sandbox) {
    return skieo_game_options_apply(owner, size, seed, length, days, sandbox);
}
int matches(const uint8_t *data, size_t size) {
    return size >= sizeof(skieo_game_options_signature) &&
        !memcmp(data, skieo_game_options_signature, sizeof(skieo_game_options_signature));
}
''')
        library = folder / 'options.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'native/SkiEONativeTerrain'), str(source),
                        '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.apply = cls.library.apply
        cls.apply.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int32,
                             ctypes.c_float, ctypes.c_uint32, ctypes.c_uint32]
        cls.matches = cls.library.matches
        cls.matches.argtypes = [ctypes.c_void_p, ctypes.c_size_t]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_only_reviewed_request_fields_are_written(self):
        before = bytes([0xa5]) * 0xb0
        raw = ctypes.create_string_buffer(before)
        self.assertTrue(self.apply(raw, len(before), -1, 0.5, 3, 1))
        expected = bytearray(before)
        struct.pack_into('<i', expected, 0x78, -1)
        struct.pack_into('<fIBB', expected, 0x80, 0.5, 3, 1, 0)
        self.assertEqual(raw.raw[:-1], expected)

    def test_invalid_or_truncated_requests_leave_memory_untouched(self):
        before = bytes([0x5a]) * 0xb0
        raw = ctypes.create_string_buffer(before)
        for length, days, sandbox in [(float('nan'), 1, 0), (float('inf'), 1, 0),
                                     (0, 1, 0), (65, 1, 0), (1, 0, 0), (1, 32, 0), (1, 1, 2)]:
            self.assertFalse(self.apply(raw, len(before), 1, length, days, sandbox))
            self.assertEqual(raw.raw[:-1], before)
        for size in range(0x8a):
            self.assertFalse(self.apply(raw, size, 1, 1, 1, 0))
            self.assertEqual(raw.raw[:-1], before)

    def test_exact_assignment_signature_rejects_every_byte_of_drift(self):
        signature = bytes.fromhex('41894578488b85b0000000f20f1000f2410f1185800000008b400841898588000000')
        self.assertTrue(self.matches(signature, len(signature)))
        for size in range(len(signature)):
            self.assertFalse(self.matches(signature, size))
        for offset in range(len(signature)):
            changed = bytearray(signature)
            changed[offset] ^= 1
            self.assertFalse(self.matches(bytes(changed), len(changed)))
