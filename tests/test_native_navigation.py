"""Keep native navigation invalidation paired with a verified subsystem layout."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TICKS = (
    '48895c2418564883ec30488d71c8',
    '40534883ec300f29742420488bd948897424400f28f1488d71c8',
    '48895c24184889742420574883ec60488d71c80f29742450488bd9',
)
HANDLERS = ('c6816806000001c6414901c3', 'c6814808000001c6416901c3')


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NavigationLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = folder / 'guard.c'
        source.write_text('''#include "navigation_layout.h"
const void *inspect(const unsigned char *tick, size_t size) {
    return skieo_navigation_changed_signature(tick, size);
}
''')
        library = folder / 'guard.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra',
                        '-Werror', '-I', str(ROOT / 'native/SkiEONativeTerrain'),
                        str(source), '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.inspect = cls.library.inspect
        cls.inspect.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        cls.inspect.restype = ctypes.c_void_p

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def handler(self, tick):
        storage = ctypes.create_string_buffer(tick)
        result = self.inspect(storage, len(tick))
        self.assertEqual(storage.raw[:-1], tick)
        return ctypes.string_at(result, 12).hex() if result else None

    def test_each_tick_selects_its_own_handler(self):
        for index, tick in enumerate(TICKS):
            with self.subTest(index=index):
                self.assertEqual(self.handler(bytes.fromhex(tick)), HANDLERS[index == 2])

    def test_changed_tick_or_owner_adjustment_is_rejected(self):
        for tick in map(bytes.fromhex, TICKS):
            for offset in range(len(tick)):
                changed = bytearray(tick)
                changed[offset] ^= 0x01
                self.assertIsNone(self.handler(bytes(changed)))

    def test_truncated_tick_is_rejected(self):
        for tick in map(bytes.fromhex, TICKS):
            for size in range(len(tick)):
                self.assertIsNone(self.handler(tick[:size]))


if __name__ == '__main__':
    unittest.main()
