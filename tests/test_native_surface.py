"""Compare native sampling against actual rendered triangles, including seams."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
LUA=os.environ.get('CUSTOM_MAP_LUA') or shutil.which('lua5.4') or shutil.which('lua')


@unittest.skipUnless(shutil.which('cc') and LUA,'C compiler and Lua 5.4 required')
class NativeSurfaceTests(unittest.TestCase):
    def test_native_sampler_matches_rendered_triangles(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            source=folder/'sample.c'
            source.write_text('''#include "surface_sampling.h"
double sample(const uint8_t *bytes, const uint8_t *bits, uint32_t w, uint32_t h,
    uint32_t step, uint32_t fine, uint32_t flags, double x, double y) {
    SkiEOSurface s={bytes,bits,w,h,step,fine,(w-2)/step+1,(h-2)/step+1,flags};
    return skieo_surface_sample(&s,x,y);
}''')
            library=folder/'sample.so'
            subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'native/SkiEONativeTerrain'),str(source),'-lm','-o',str(library)],
                check=True,capture_output=True)
            lib=ctypes.CDLL(str(library));sample=lib.sample
            sample.restype=ctypes.c_double
            sample.argtypes=[ctypes.c_void_p,ctypes.c_void_p,*([ctypes.c_uint32]*5),ctypes.c_double,ctypes.c_double]
            fixture=folder/'surfaces.json'
            subprocess.run([LUA,'tests/export_surface_samples.lua',str(fixture)],cwd=ROOT,check=True,capture_output=True)
            for case in json.loads(fixture.read_text()):
                width,height,step=case['width'],case['height'],case['step']
                endian='<' if case['flags']&1 else '>'
                raw=ctypes.create_string_buffer(struct.pack(endian+str(len(case['values']))+'H',*case['values']))
                cells=((width-2)//step+1)*((height-2)//step+1)
                bits=bytearray((cells+7)//8)
                for key in case['refined']:bits[(key-1)//8]|=1<<((key-1)%8)
                mask=ctypes.create_string_buffer(bytes(bits))
                for x,y,expected in case['points']:
                    actual=sample(raw,mask,width,height,step,case['fine'],case['flags'],x,y)
                    self.assertAlmostEqual(actual,expected,places=7,
                        msg=f'{step=} {case["flags"]=} at {x,y}')
