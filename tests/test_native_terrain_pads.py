"""Exercise fail-closed terrain-pad code fingerprints without game writes."""
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class TerrainPadCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = folder / 'guard.c'
        source.write_text('''#include "terrain_pads_layout.h"
uint64_t fingerprint(const uint8_t *data, size_t size) {
    return skieo_terrain_pads_hash(data, size);
}
int inspect(const uint8_t *data, size_t size, uint32_t rva) {
    return skieo_terrain_pads_matches(data, size, rva);
}
int inspect_cleanup(const uint8_t *data, size_t size, uint32_t rva) {
    return skieo_terrain_pads_cleanup_matches(data, size, rva);
}
''')
        library = folder / 'guard.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'native/SkiEONativeTerrain'), str(source),
                        '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.inspect = cls.library.inspect
        cls.inspect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        cls.inspect.restype = ctypes.c_int
        cls.inspect_cleanup = cls.library.inspect_cleanup
        cls.inspect_cleanup.argtypes = cls.inspect.argtypes
        cls.inspect_cleanup.restype = ctypes.c_int
        cls.fingerprint = cls.library.fingerprint
        cls.fingerprint.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        cls.fingerprint.restype = ctypes.c_uint64

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_standard_fingerprint_and_read_only_storage(self):
        for data, expected in [(b'', 0xcbf29ce484222325), (b'a', 0xaf63dc4c8601ec8c),
                               (b'foobar', 0x85944171f73967e8)]:
            raw = ctypes.create_string_buffer(data)
            self.assertEqual(self.fingerprint(raw, len(data)), expected)
            self.assertEqual(raw.raw[:-1], data)

    def test_unknown_code_and_truncated_snapshots_are_refused(self):
        raw = ctypes.create_string_buffer(0x828)
        for rva in (0x4fe0c00, 0x4fdf110, 0, 0x4fe0c01):
            for size in range(0x829):
                self.assertFalse(self.inspect(raw, size, rva))
        self.assertEqual(raw.raw, bytes(len(raw)))
        for rva in (0x4fcbe40, 0x4fca360, 0):
            for size in range(0x10c):
                self.assertFalse(self.inspect_cleanup(raw, size, rva))

    def test_reviewed_installed_code_and_single_byte_drift(self):
        # Optional evidence from local licensed copies; never store game code
        # in the repository. CI still runs the portable refusal/hash tests.
        from tools.check_game_compatibility import PEImage
        from tools.skieo_install import load_config
        config = load_config()
        binary = Path(config.get('binary_dir', ROOT / 'build/no-configured-game')) / 'skieogame.exe'
        candidates = [
            (ROOT / 'build/update-25996759/session/game/SkiResortSimulator/Binaries/Win64/skieogame.exe', 0x4fdf110),
        ]
        reference = json.loads((ROOT / 'compatibility/game-contract.json').read_text())
        if binary.is_file() and hashlib.sha256(binary.read_bytes()).hexdigest() == reference['reference_executable_sha256']:
            candidates.append((binary, 0x4fe0c00))
        found = 0
        for path, rva in candidates:
            if not path.is_file():
                continue
            found += 1
            code = PEImage(path.read_bytes()).read(rva, 0x828)
            raw = ctypes.create_string_buffer(code)
            self.assertTrue(self.inspect(raw, len(code), rva))
            self.assertFalse(self.inspect(raw, len(code), 0))
            for offset in range(len(code)):
                raw[offset] = bytes([code[offset] ^ 1])
                self.assertFalse(self.inspect(raw, len(code), rva), hex(offset))
                raw[offset] = bytes([code[offset]])
            self.assertEqual(raw.raw[:-1], code)
            cleanup_rva = {0x4fe0c00: 0x4fcbe40, 0x4fdf110: 0x4fca360}[rva]
            code = PEImage(path.read_bytes()).read(cleanup_rva, 0x10b)
            raw = ctypes.create_string_buffer(code)
            self.assertTrue(self.inspect_cleanup(raw, len(code), cleanup_rva))
            for offset in range(len(code)):
                raw[offset] = bytes([code[offset] ^ 1])
                self.assertFalse(self.inspect_cleanup(raw, len(code), cleanup_rva), hex(offset))
                raw[offset] = bytes([code[offset]])
        if not found:
            self.skipTest('No local reviewed game binary available')


if __name__ == '__main__':
    unittest.main()
