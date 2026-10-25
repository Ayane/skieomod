"""Read real native snapshot packets from guarded, immutable guest arrays."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NativeRiderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        shim = r'''
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <wchar.h>
#define __declspec(x)
#define MAX_PATH 260
typedef struct Array{uint8_t *data;int32_t count,capacity;} Array;
typedef struct Tow{uint32_t id[4];float speed;} Tow;
static uint8_t owner[0x90],cold_data[3*0xba0],hot_data[3*0x80];
static Tow lifts[16];static uint32_t count;static int installed,evac_ready,lock;
static const char *input_path,*output_path,*status_path;
static int readable(const void *p,size_t n){return (p==cold_data&&n<=sizeof cold_data)||(p==hot_data&&n<=sizeof hot_data);}
static int evac_object(uint64_t p,uint64_t cls,size_t n){return p==(uintptr_t)owner&&cls==123&&n<=sizeof owner;}
static void AcquireSRWLockShared(int *p){(void)p;}
static void ReleaseSRWLockShared(int *p){(void)p;}
static int path(wchar_t *p,const wchar_t *name){*p=wcsstr(name,L".job")?L'J':wcsstr(name,L".bin")?L'B':L'S';return 1;}
static FILE *_wfopen(const wchar_t *p,const wchar_t *mode){(void)mode;return fopen(*p==L'J'?input_path:*p==L'B'?output_path:status_path,*p==L'J'?"rb":"wb");}
'''
        harness = r'''
int exercise(const char *in,const char *out,const char *status,int broken){
 input_path=in;output_path=out;status_path=status;
 memset(owner,0,sizeof owner);memset(cold_data,0,sizeof cold_data);memset(hot_data,0,sizeof hot_data);
 installed=evac_ready=1;count=1;memset(lifts,0,sizeof lifts);lifts[0].id[0]=7;
 Array cold={cold_data,3,3},hot={hot_data,3,3};
 uint32_t guest[]={0xffffffff,2,3,4};memcpy(cold_data,guest,16);cold_data[0x1d]=1;
 memcpy(cold_data+0xa30,lifts[0].id,16);hot_data[0x68]=3;
 int32_t color=42;memcpy(hot_data+0x50,&color,4);double xyz[]={11,22,33};memcpy(hot_data,xyz,24);
 hot_data[0x80+0x68]=4;hot_data[0x100+0x68]=3;
 if(broken==1)installed=0;if(broken==2)evac_ready=0;if(broken==3)hot.count=2;
 if(broken==4)cold.capacity=1;if(broken==5)cold.count=hot.count=20001;
 if(broken==8){uint8_t tmp[0xba0];memcpy(tmp,cold_data,0xba0);memcpy(cold_data,cold_data+0xba0,0xba0);memcpy(cold_data+0xba0,tmp,0xba0);
 memcpy(tmp,hot_data,0x80);memcpy(hot_data,hot_data+0x80,0x80);memcpy(hot_data+0x80,tmp,0x80);}
 if(broken==9){double bad=NAN;memcpy(hot_data,&bad,8);}
 memcpy(owner+0x58,&cold,sizeof cold);memcpy(owner+0x68,&hot,sizeof hot);
 struct {char magic[4];uint32_t version;uint64_t owner,cls;uint32_t nonce,reserved;}job={"SKRD",1,(uintptr_t)owner,123,17,0};
 if(broken==6)job.cls++;if(broken==7)job.reserved=1;
 FILE *f=fopen(in,"wb");fwrite(&job,1,sizeof job,f);fclose(f);
 uint8_t before_cold[sizeof cold_data],before_hot[sizeof hot_data];memcpy(before_cold,cold_data,sizeof cold_data);memcpy(before_hot,hot_data,sizeof hot_data);
 skieo_surface_riders(NULL);
 return memcmp(before_cold,cold_data,sizeof cold_data)||memcmp(before_hot,hot_data,sizeof hot_data);
}
'''
        source = folder / 'riders.c'
        source.write_text(shim + (ROOT / 'native/SkiEOSurfaceLifts/riders.h').read_text() + harness)
        output = folder / 'riders.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', str(source), '-lm', '-o', str(output)],
                       check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(output))
        cls.library.exercise.argtypes = [ctypes.c_char_p] * 3 + [ctypes.c_int]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def packet(self, broken=0):
        paths = [Path(self.temp.name) / name for name in ('input', 'output', 'status')]
        self.assertEqual(self.library.exercise(*(str(p).encode() for p in paths), broken), 0)
        data = paths[1].read_bytes()
        return struct.unpack_from('<4sIII', data), data[16:]

    def test_positions_identity_palette_compaction_and_no_mutation(self):
        for broken, index in [(0, 0), (8, 1)]:
            header, rows = self.packet(broken)
            self.assertEqual(header, (b'SKRD', 1, 17, 1))
            self.assertEqual(struct.unpack('<IIiI8I3d', rows),
                             (index, 1, 42, 0, 0xffffffff, 2, 3, 4, 7, 0, 0, 0, 11, 22, 33))
        self.assertEqual(self.packet(9), ((b'SKRD', 1, 17, 0), b''))

    def test_unreviewed_or_invalid_arrays_fail_before_reading(self):
        for broken in range(1, 8):
            with self.subTest(broken=broken):
                header, rows = self.packet(broken)
                self.assertEqual(header, (b'SKER', 1, 17, 0))
                self.assertEqual(rows, b'')
