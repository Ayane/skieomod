"""Exercise the shipped native snow-clear protocol and fail-closed guards."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class SnowGradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        shim = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <wchar.h>
#define __declspec(x)
#define MAX_PATH 260
#define SNOW_CLEAR_RVA 0
#define SNOW_CLEAR_SIZE 1
#define SNOW_CLEAR_HASH UINT64_C(11)
#define SNOW_CLEAR_CORE_RVA 1
#define SNOW_CLEAR_CORE_SIZE 1
#define SNOW_CLEAR_CORE_HASH UINT64_C(12)
static const char *job_path,*status_path;
static unsigned calls;static int broken;
static float target_seen,budget_seen;static double x_seen,y_seen;
static void clear(void *owner,const double *p,float radius,float target,float budget){
 if((uintptr_t)owner!=123||radius<100||radius>300)broken=8;
 calls++;target_seen=target;budget_seen=budget;x_seen=p[0];y_seen=p[1];
}
static void *GetModuleHandleW(const wchar_t *name){(void)name;return(void *)(uintptr_t)&clear;}
static int readable(const void *p,size_t n){(void)p;(void)n;return broken!=1;}
static uint64_t hash(const uint8_t *p,size_t n){(void)n;return broken==2?0:(uintptr_t)p==(uintptr_t)&clear?11:12;}
static int contact_object(uint64_t owner,uint64_t cls){return owner==123&&cls==456;}
static int path(wchar_t *out,const wchar_t *name){out[0]=wcsstr(name,L".job")?L'J':L'S';out[1]=0;return 1;}
static FILE *_wfopen(const wchar_t *name,const wchar_t *mode){(void)mode;return fopen(name[0]==L'J'?job_path:status_path,name[0]==L'J'?"rb":"wb");}
'''
        harness = r'''
unsigned exercise(const char *input,const char *output,int failure){
 job_path=input;status_path=output;calls=0;broken=failure;
 skieo_surface_grade(NULL);return calls;
}
float observed_target(void){return target_seen;}
float observed_budget(void){return budget_seen;}
double observed_x(void){return x_seen;}
double observed_y(void){return y_seen;}
'''
        source = folder / 'grade.c'
        source.write_text(shim + (ROOT / 'native/SkiEOSurfaceLifts/snow_grade.h').read_text() + harness)
        library = folder / 'grade.so'
        subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', str(source), '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.exercise.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        cls.lib.exercise.restype = ctypes.c_uint
        cls.lib.observed_target.restype = cls.lib.observed_budget.restype = ctypes.c_float
        cls.lib.observed_x.restype = cls.lib.observed_y.restype = ctypes.c_double

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_job(self, packet, failure=0):
        root = Path(self.temp.name)
        job, status = root / 'input.job', root / 'result.status'
        job.write_bytes(packet)
        calls = self.lib.exercise(str(job).encode(), str(status).encode(), failure)
        return calls, status.read_text()

    @staticmethod
    def packet(points=((120.5, -320.25, 250, 500),), **values):
        fields = dict(magic=b'SKSG', version=2, count=len(points), reserved=0, owner=123, cls=456)
        fields.update(values)
        return struct.pack('<4sIIIQQ', *fields.values()) + b''.join(struct.pack('<ddff', *p) for p in points)

    def test_valid_brush_reaches_native_operation_with_cm_units_and_depth_cap(self):
        calls, status = self.run_job(self.packet())
        self.assertEqual(calls, 1)
        self.assertTrue(status.startswith('ok:'))
        self.assertEqual(self.lib.observed_target(), 80)
        self.assertEqual(self.lib.observed_budget(), 500)
        self.assertEqual((self.lib.observed_x(), self.lib.observed_y()), (120.5, -320.25))
        self.assertEqual(self.run_job(self.packet(points=((0, 0, 100, 1),) * 256))[0], 256)

    def test_malformed_packets_unknown_owner_or_changed_native_code_cannot_clear(self):
        packets = [self.packet(**v) for v in [dict(magic=b'bad!'), dict(version=1), dict(count=257), dict(reserved=1), dict(owner=124), dict(cls=457)]]
        packets += [self.packet()[:-1], self.packet() + b'X', self.packet(points=())]
        packets += [self.packet(points=(p,)) for p in [(float('nan'), 0, 250, 500), (0, float('inf'), 250, 500), (0, 0, 99, 500), (0, 0, 301, 500), (0, 0, 250, 0), (0, 0, 250, 501)]]
        for packet in packets:
            with self.subTest(packet=packet):
                calls, status = self.run_job(packet)
                self.assertEqual(calls, 0)
                self.assertTrue(status.startswith('error:'))
        for failure in (1, 2):
            self.assertEqual(self.run_job(self.packet(), failure)[0], 0)
