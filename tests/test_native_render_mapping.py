"""Exercise the native renderer ownership guard across verified game layouts."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class RenderMappingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = folder/'guard.c'
        source.write_text('''#include "render_mapping_layout.h"
int inspect(const unsigned char *data, size_t size, uint64_t scene,
            const uint64_t *textures) {
    return skieo_render_mapping_matches_snapshot(data, size, scene, textures);
}
''')
        library = folder/'guard.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra',
            '-Werror', '-I', str(ROOT/'native/SkiEONativeTerrain'),
            str(source), '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.inspect = cls.library.inspect
        cls.inspect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint64,
                                ctypes.POINTER(ctypes.c_uint64)]
        cls.inspect.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def snapshot(self, controls):
        data = bytearray(0xE0)
        struct.pack_into('<Q', data, 8, 0x48570000)
        self.textures = [0x100100+i*0x100 for i in range(7)]
        for offset, texture in zip((0x10, 0x40, 0x48, 0x50, 0x58),
                                   (1, 3, 4, 5, 6)):
            struct.pack_into('<Q', data, offset, self.textures[texture])
        struct.pack_into('<6f', data, 0x18, -51200, -51200, 51200, 51200, 4600, 26200)
        data[controls:controls+4] = b'\x01'*4
        struct.pack_into('<I', data, controls+4, 1)
        return data

    def accepted(self, data, *, scene=0x48570000):
        before = bytes(data)
        raw = ctypes.create_string_buffer(before)
        textures = (ctypes.c_uint64*7)(*self.textures)
        result = self.inspect(raw, len(before), scene, textures)
        self.assertEqual(raw.raw[:-1], before, 'ownership inspection mutated storage')
        return bool(result)

    def test_verified_layouts(self):
        for controls in (0xB0, 0xB8, 0xD8):
            with self.subTest(controls=controls):
                data = self.snapshot(controls)
                self.assertTrue(self.accepted(data))
                for reference in self.textures[:3]:
                    struct.pack_into('<Q', data, 0x10, reference)
                    self.assertTrue(self.accepted(data))
        self.assertTrue(self.accepted(self.snapshot(0xB0)[:0xB8]))
        self.assertTrue(self.accepted(self.snapshot(0xB8)[:0xC0]))

    def test_25970577_controls_follow_native_references(self):
        data = self.snapshot(0xD8)
        # UE4SS snapshot: four native references now precede the controls.
        # These must not be interpreted as the older layout's flags.
        struct.pack_into('<4Q', data, 0xB8,
                         0x7FF0FE1F3650, 0x7FF0FE1F3640,
                         0x7FF3FE0DC290, 0x7FF3FE0DC280)
        self.assertTrue(self.accepted(data))
        for size in (0xB8, 0xC0, 0xD8, 0xDC, 0xDF):
            self.assertFalse(self.accepted(data[:size]))

    def test_unrelated_world_or_texture_is_rejected(self):
        for controls in (0xB0, 0xB8, 0xD8):
            data = self.snapshot(controls)
            self.assertFalse(self.accepted(data, scene=0x55555555))
            for offset in (0x10, 0x40, 0x48, 0x50, 0x58):
                changed = data.copy()
                struct.pack_into('<Q', changed, offset, 0xDEADBEEF)
                self.assertFalse(self.accepted(changed))

    def test_invalid_bounds_or_unrecognized_controls_are_rejected(self):
        for controls in (0xB0, 0xB8, 0xD8):
            data = self.snapshot(controls)
            for index in range(6):
                changed = data.copy()
                struct.pack_into('<f', changed, 0x18+index*4, float('nan'))
                self.assertFalse(self.accepted(changed))
            for low, high in ((0, 2), (1, 3), (4, 5)):
                changed = data.copy()
                value = struct.unpack_from('<f', changed, 0x18+high*4)[0]
                struct.pack_into('<f', changed, 0x18+low*4, value)
                self.assertFalse(self.accepted(changed))
            for offset in (controls, controls+4):
                changed = data.copy()
                changed[offset] = 0
                self.assertFalse(self.accepted(changed))

    def test_truncated_snapshot_is_rejected(self):
        data = self.snapshot(0xB8)
        for size in (0, 8, 0x60, 0xB7, 0xB8, 0xBC, 0xBF):
            self.assertFalse(self.accepted(data[:size]))


if __name__ == '__main__':
    unittest.main()
