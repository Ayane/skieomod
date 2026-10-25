"""Exercise the actual wind-down hooks with empty native boarding state."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NativeDrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = (ROOT / 'native/SkiEOSurfaceLifts/drain.h').read_text()
        # Test the shipped hooks directly; Windows export/hook installation is
        # qualified in the isolated game, including its complete-code hashes.
        source = source[:source.index('static const char *drain_prepare')]
        shim = r'''
#include <stdint.h>
#include <string.h>
#include <math.h>
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static void AcquireSRWLockShared(SRWLOCK *p){(void)p;}
static void ReleaseSRWLockShared(SRWLOCK *p){(void)p;}
static uint8_t object[0x700];
static int evac_object(uint64_t ptr,uint64_t cls,size_t n){return ptr==(uintptr_t)object&&cls==123&&n<=sizeof object;}
static uint8_t native_state;
static float native_speed;
static uint8_t original_state(void *p){(void)p;return native_state;}
static float original_speed(void *p){(void)p;return native_speed;}
'''
        harness = r'''
int exercise(int state,float speed,float operating,int registered,float *result){
 memset(object,0,sizeof object);memcpy(object+0x464,&operating,4);
 native_state=(uint8_t)state;native_speed=speed;drain_count=registered?1:0;
 drain_entries[0]=(DrainEntry){(uintptr_t)object,123,180,0};
 drain_state_original=original_state;drain_speed_original=original_speed;
 result[0]=drain_state(object);result[1]=drain_speed(object);
 // Neither hook may invent a boarding count or mutate any native field.
 float stored;memcpy(&stored,object+0x464,4);if(stored!=operating)return -1;
 memset(object+0x464,0,4);for(size_t i=0;i<sizeof object;i++)if(object[i])return -2;
 return 0;
}
'''
        file = folder / 'drain.c'
        file.write_text(shim + source + harness)
        output = folder / 'drain.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-variable', str(file), '-lm', '-o', str(output)],
                       check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(output))
        cls.library.exercise.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float,
                                         ctypes.c_int, ctypes.POINTER(ctypes.c_float)]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_empty_return_and_priority_of_native_hard_stops(self):
        for state, speed, operating, registered, expected in [
            (1, 0, 300, 1, (1, 180)), (4, 0, 300, 1, (1, 180)),
            (1, 300, 300, 1, (1, 180)), (1, 90, 300, 1, (1, 90)),
            (3, 0, 300, 1, (3, 0)), (4, 0, 0, 1, (4, 0)),
            (0, 300, 300, 1, (0, 300)), (4, 0, 300, 0, (4, 0)),
        ]:
            with self.subTest(state=state, operating=operating, registered=registered):
                result = (ctypes.c_float * 2)()
                self.assertEqual(self.library.exercise(state, speed, operating, registered, result), 0)
                self.assertEqual(tuple(result), expected)
