"""Exercise the shipped CPU snow reader with sparse old/new cache layouts."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NativeSnowMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = (ROOT / 'native/SkiEONativeTerrain/native_terrain.c').read_text()
        function = source[source.index('__declspec(dllexport) int skieo_sample_snow('):]
        shim = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <math.h>
#define __declspec(x)
#define MAX_PATH 260
#include "layout_profiles.h"
static uint32_t native_layout_rva(enum SkiEOLayoutId id) {(void)id; return 0;}
static unsigned char executable[0x5400000],cache[0x300],entries[112];
static float samples[4096*8];
static size_t entry_limit;
static const char *input_path,*output_path;
static int contains(const void *p,size_t n,const void *base,size_t length) {
    uintptr_t address=(uintptr_t)p,first=(uintptr_t)base;
    return address>=first && address-first<=length && n<=length-(address-first);
}
static int readable_range(const void *p,size_t n) {
    return contains(p,n,executable,sizeof(executable)) || contains(p,n,cache,sizeof(cache))
        || contains(p,n,entries,entry_limit) || contains(p,n,samples,sizeof(samples));
}
static void *GetModuleHandleW(const wchar_t *name) {(void)name;return executable;}
static int sibling_path(wchar_t *path,size_t n,const wchar_t *name) {
    if(n)path[0]=wcsstr(name,L".job")?L'J':L'O';return n>0;
}
static FILE *_wfopen(const wchar_t *path,const wchar_t *mode) {
    (void)mode;return fopen(path[0]==L'J'?input_path:output_path,path[0]==L'J'?"rb":"wb");
}
'''
        harness = r'''
int exercise(const char *input,const char *output,int modern,int broken) {
    input_path=input;output_path=output;
    memset(executable,0,sizeof(executable));memset(cache,0,sizeof(cache));
    memset(entries,0,sizeof(entries));memset(samples,0,sizeof(samples));
    static const unsigned char validity[]={0x0f,0xb6,0x81,0xa5,0x01,0,0,0x41,0x88,0};
    static const unsigned char mapping[]={0xf2,0x0f,0x10,0x89,0xf8,0,0,0,0x0f,0x57,0xd2,0xf2,0x0f,0x5c,0x89,0xe8,0,0,0};
    static const unsigned char old_lookup[]={0x49,0x63,0xc1,0x4c,0x8d,0x04,0x40,0x49,0xc1,0xe0,0x04};
    static const unsigned char new_lookup[]={0x49,0x63,0xc0,0x48,0x6b,0xd0,0x38,0x49,0x03,0xd2,0x48,0x8b,0x0a,0x41,0x3b,0xc9};
    static const unsigned char ready[]={0x41,0x38,0x54,0x24,0x20,0x0f,0x84,0xe3,0xfd,0xff,0xff};
    size_t v=modern==2?0x4f5ac15:modern?0x4f5a315:0x4f576f5;
    size_t l=modern==2?0x52eccc0:modern?0x52ea970:0x5284fb0;
    size_t m=modern==2?0x52eae50:modern?0x52e8900:0x52863d0;
    size_t r=modern==2?0x52ecf06:0x52eabb6;
    memcpy(executable+v,validity,sizeof(validity));memcpy(executable+m,mapping,sizeof(mapping));
    memcpy(executable+l,modern?new_lookup:old_lookup,modern?sizeof(new_lookup):sizeof(old_lookup));
    if(modern)memcpy(executable+r,ready,sizeof(ready));
    if(broken==1)executable[v]^=1;
    if(broken==2)executable[l]^=1;
    if(broken==3)executable[m]^=1;
    if(broken==4)executable[r]^=1;
    uint64_t cls=0x123456789,pointer=(uintptr_t)entries;
    memcpy(cache+0x10,&cls,8);cache[0x1a5]=broken==5?0:1;
    double bounds[]={0,0,409600,409600};memcpy(cache+0xe8,bounds,sizeof(bounds));
    int32_t tiles=64,count=2,allocated=2;memcpy(cache+0x10c,&tiles,4);
    memcpy(cache+0x48,&pointer,8);memcpy(cache+0x50,&count,4);memcpy(cache+0x54,&count,4);
    memcpy(cache+0x58,&allocated,4);memcpy(cache+0x70,&count,4);
    unsigned stride=modern?56:48;entry_limit=2*stride-(broken==7?1:0);
    int32_t key[]={2,3},length=4096;
    // Slot zero has the same key but is free; reading it must not hide slot one.
    memcpy(entries,key,8);memcpy(entries+16,&length,4);
    unsigned char *entry=entries+stride;
    memcpy(entry,key,8);pointer=(uintptr_t)samples;memcpy(entry+8,&pointer,8);memcpy(entry+16,&length,4);
    entry[modern?0x28:0x24]=broken==6?0:1;
    samples[(7*64+5)*8]=73.5f;samples[(7*64+5)*8+1]=20.0f;
    struct {char magic[4];uint32_t version;uint64_t owner,cls;double x,y;} job={"SKSN",1,(uintptr_t)cache,cls,13301,19901};
    if(broken==8)job.cls++;
    if(broken==9)job.x=-1;
    FILE*f=fopen(input,"wb");if(!f)return -1;fwrite(&job,1,sizeof(job),f);fclose(f);
    unsigned char before_cache[sizeof(cache)],before_entries[sizeof(entries)];
    float before_samples[sizeof(samples)/sizeof(samples[0])];
    memcpy(before_cache,cache,sizeof(cache));memcpy(before_entries,entries,sizeof(entries));
    memcpy(before_samples,samples,sizeof(samples));
    int result=skieo_sample_snow(NULL);
    if(memcmp(cache,before_cache,sizeof(cache)) || memcmp(entries,before_entries,sizeof(entries))
        || memcmp(samples,before_samples,sizeof(samples)))return -2;
    return result;
}
'''
        file = folder / 'snow.c'
        file.write_text(shim + function + harness)
        library = folder / 'snow.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'native/SkiEONativeTerrain'),
                        '-Wno-misleading-indentation', str(file), '-lm', '-o', str(library)],
                       check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.exercise.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def sample(self, modern, broken=0):
        input_path = Path(self.temp.name) / 'snow.job'
        output_path = Path(self.temp.name) / 'snow.bin'
        self.assertEqual(self.library.exercise(str(input_path).encode(), str(output_path).encode(), modern, broken), 0)
        return struct.unpack('<4f', output_path.read_bytes())

    def test_sparse_tile_lookup_and_readiness_in_both_layouts(self):
        for modern in (0, 1, 2):
            with self.subTest(modern=modern):
                self.assertEqual(self.sample(modern), (1.0, 73.5, 20.0, 100.0))

    def test_bad_guards_unready_or_short_data_and_outside_points_are_rejected(self):
        for modern in (1, 2):
            for broken in range(1, 10):
                with self.subTest(modern=modern, broken=broken):
                    self.assertEqual(self.sample(modern, broken), (0.0, 0.0, 0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
