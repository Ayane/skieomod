"""Exercise the shipped classifier and input validation, including float edges."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NativeTrailRatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        source = Path(cls.temp.name) / 'policy.c'
        source.write_text('#include "' + str(ROOT / 'native/SkiEOTrailRatings/rating_policy.h') + '"\n'
            '#include "' + str(ROOT / 'native/SkiEOTrailRatings/rating_colors.h') + '"\n'
            'int valid(unsigned count,float a,float b,float c) { RatingPolicy p={count,{a,b,c}}; return rating_policy_valid(&p); }\n'
            'int classify(float angle,unsigned count,float a,float b,float c) { RatingPolicy p={count,{a,b,c}}; return rating_from_slope(angle,&p); }\n'
            'int colors_valid(unsigned mask,unsigned a,unsigned b,unsigned c,unsigned d) { RatingColors p={mask,{a,b,c,d}}; return rating_colors_valid(&p); }\n'
            'void linear_color(unsigned srgb,float *rgba) { RatingColor c=rating_linear_color(srgb); rgba[0]=c.r; rgba[1]=c.g; rgba[2]=c.b; rgba[3]=c.a; }\n')
        library = source.with_suffix('.so')
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', str(source), '-lm', '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.valid.argtypes = [ctypes.c_uint, *[ctypes.c_float] * 3]
        cls.lib.classify.argtypes = [ctypes.c_float, ctypes.c_uint, *[ctypes.c_float] * 3]
        cls.lib.colors_valid.argtypes = [ctypes.c_uint] * 5
        cls.lib.linear_color.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_float)]
        cls.lib.linear_color.restype = None

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_two_thresholds_disable_fourth_tier_and_use_inclusive_boundaries(self):
        self.assertTrue(self.lib.valid(2, 15, 25, 0))
        for angle, rating in [(-1, 0), (0, 0), (14.999, 0), (15, 1), (24.999, 1), (25, 2), (90, 2)]:
            self.assertEqual(self.lib.classify(angle, 2, 15, 25, 0), rating)

    def test_three_thresholds_and_native_nan_behavior(self):
        self.assertTrue(self.lib.valid(3, 16, 27, 33))
        for angle, rating in [(15.999, 0), (16, 1), (27, 2), (33, 3), (float('nan'), 0), (float('inf'), 3)]:
            self.assertEqual(self.lib.classify(angle, 3, 16, 27, 33), rating)

    def test_invalid_policy_and_unused_fields_are_rejected(self):
        for count, values in [(1, (10, 0, 0)), (4, (10, 20, 30)), (2, (0, 20, 0)),
                              (2, (20, 10, 0)), (2, (20, 20, 0)), (2, (10, 20, 30)),
                              (3, (10, 20, 91)), (2, (float('nan'), 20, 0)),
                              (2, (10, float('inf'), 0)), (0, (10, 0, 0))]:
            with self.subTest(count=count, values=values): self.assertFalse(self.lib.valid(count, *values))
        self.assertTrue(self.lib.valid(0, 0, 0, 0))

    def test_color_mask_distinguishes_black_from_native_fallback(self):
        for mask, values in [(0, (0, 0, 0, 0)), (4, (0, 0, 0, 0)),
                             (15, (0x0080FF, 0xFF0000, 0, 0xFF8000))]:
            self.assertTrue(self.lib.colors_valid(mask, *values))
        for mask, values in [(16, (0, 0, 0, 0)), (1, (0x1000000, 0, 0, 0)),
                             (1, (0, 0xFF0000, 0, 0)), (0, (0, 0, 0, 1))]:
            self.assertFalse(self.lib.colors_valid(mask, *values))

    def test_hex_colors_are_converted_from_srgb_to_opaque_linear_rgba(self):
        for srgb in (0, 0xFFFFFF, 0x0080FF, 0x0A0B20, 0x8844CC):
            actual = (ctypes.c_float * 4)()
            self.lib.linear_color(srgb, actual)
            for index, shift in enumerate((16, 8, 0)):
                channel = ((srgb >> shift) & 255) / 255
                expected = channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
                self.assertAlmostEqual(actual[index], expected, places=6)
            self.assertEqual(actual[3], 1)


if __name__ == '__main__': unittest.main()
