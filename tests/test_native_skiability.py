"""Run the production memo invalidator against bounded, synthetic game memory."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class SkiabilityMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = (ROOT / 'native/SkiEONativeTerrain/native_terrain.c').read_text()
        start = source.index('__declspec(dllexport) int skieo_refresh_skiability(')
        end = source.index('\n/* Store authored', start)
        # Keep the function under test verbatim; only OS/memory/file services
        # are replaced. Byte fixtures come from the inspected executables.
        shim = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#define __declspec(x)
#define MAX_PATH 260
static unsigned char executable[0x5400000], owner[0x200];
static size_t owner_limit;
static const char *job_path;
static char status[160];
static int readable_range(const void *p, size_t n) {
    uintptr_t address=(uintptr_t)p;
    uintptr_t first=(uintptr_t)executable;
    if(address>=first && address-first<=sizeof(executable)
        && n<=sizeof(executable)-(address-first))return 1;
    first=(uintptr_t)owner;
    return address>=first && address-first<=owner_limit
        && n<=owner_limit-(address-first);
}
static void *GetModuleHandleW(const wchar_t *name) {(void)name;return executable;}
static int sibling_path(wchar_t *p,size_t n,const wchar_t *name) {
    (void)name;if(n)p[0]=0;return 1;
}
static FILE *_wfopen(const wchar_t *p,const wchar_t *mode) {
    (void)p;(void)mode;return fopen(job_path,"rb");
}
static void write_status(const char *message) {snprintf(status,sizeof(status),"%s",message);}
'''
        harness = r'''
const void *memory(void) {return owner;}
const char *last_status(void) {return status;}
int exercise(const char *path,int modern,int broken,size_t limit) {
    job_path=path;owner_limit=limit;status[0]=0;
    memset(executable,0,sizeof(executable));memset(owner,0xa7,sizeof(owner));
    uint64_t cls=0x123456789;
    memcpy(owner+0x10,&cls,8);
    static const unsigned char query[]={0x40,0x55,0x53,0x56,0x48,0x8d,0x6c,0x24,0xb9,0x48,0x81,0xec,0xb0,0,0,0};
    static const unsigned char old_memo[]={0x44,0x3b,0xbe,0x9c,0x01,0,0,0x75,0x27,0x0f,0x28,0xc6,0xf3,0x0f,0x5c,0x86,0xa0,0x01,0,0};
    static const unsigned char new_memo[]={0x44,0x3b,0xbe,0xb4,0x01,0,0,0x75,0x27,0x0f,0x28,0xc6,0xf3,0x0f,0x5c,0x86,0xb8,0x01,0,0};
    size_t q=modern?0x5390430:0x538df30,m=modern?0x5390712:0x538e212;
    memcpy(executable+q,query,sizeof(query));
    memcpy(executable+m,modern?new_memo:old_memo,sizeof(old_memo));
    if(broken==1)executable[q]^=1;
    if(broken==2)executable[m+3]^=1;
    struct {char magic[4];uint32_t version;uint64_t address,cls;} job={"SKSK",1,(uintptr_t)owner,cls};
    if(broken==3)job.cls++;
    FILE*f=fopen(path,"wb");if(!f)return -1;
    fwrite(&job,1,sizeof(job),f);fclose(f);
    return skieo_refresh_skiability(NULL);
}
'''
        file = folder / 'memo.c'
        file.write_text(shim + source[start:end] + harness)
        library = folder / 'memo.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(file), '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.exercise.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_size_t]
        cls.library.memory.restype = ctypes.c_void_p
        cls.library.last_status.restype = ctypes.c_char_p

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, modern, broken=0, limit=0x200):
        path = str(Path(self.temp.name) / 'memo.job').encode()
        self.assertEqual(self.library.exercise(path, modern, broken, limit), 0)
        return ctypes.string_at(self.library.memory(), 0x200), self.library.last_status().decode()

    def test_new_build_invalidates_only_the_moved_memo(self):
        data, status = self.run_case(True)
        self.assertTrue(status.startswith('ok:'), status)
        self.assertEqual(data[0x1B4:0x1B8], b'\xff' * 4)
        self.assertEqual(data[0x19C:0x1A0], b'\xa7' * 4, 'old offset corrupted a different native field')
        self.assertEqual(data[0x18:0x1B4] + data[0x1B8:], b'\xa7' * (0x200-0x18-4))
        expected = bytearray(b'\xa7' * 0x200)
        struct.pack_into('<Q', expected, 0x10, 0x123456789)
        expected[0x1B4:0x1B8] = b'\xff' * 4
        self.assertEqual(data, expected)

    def test_previous_build_keeps_its_own_offset(self):
        data, status = self.run_case(False, limit=0x1A5)
        self.assertTrue(status.startswith('ok:'), status)
        self.assertEqual(data[0x19C:0x1A0], b'\xff' * 4)
        self.assertEqual(data[0x1B4:0x1B8], b'\xa7' * 4)

    def test_unrecognized_code_class_or_short_owner_is_never_modified(self):
        for modern, broken, limit in [(True, 1, 0x200), (True, 2, 0x200),
                                      (True, 3, 0x200), (True, 0, 0x1A5),
                                      (False, 2, 0x200)]:
            with self.subTest(modern=modern, broken=broken, limit=limit):
                data, status = self.run_case(modern, broken, limit)
                self.assertTrue(status.startswith('error:'), status)
                self.assertEqual(data[0x18:], b'\xa7' * (0x200-0x18))
                expected = bytearray(b'\xa7' * 0x200)
                struct.pack_into('<Q', expected, 0x10, 0x123456789)
                self.assertEqual(data, expected)


if __name__ == '__main__':
    unittest.main()
