"""Relocation accepts address operands while refusing layout drift/ambiguity."""
import ctypes
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import native_layouts

ROOT = Path(__file__).resolve().parents[1]


class NativeLayoutTests(unittest.TestCase):
    def setUp(self):
        self.code = b'\x48\x8b\x81\x60\x0b\x00\x00\xe8\x12\x34\x56\x78\xc3'
        self.guard = {'id': 'test', 'bytes': self.code[:7].hex(), 'normalized': {
            'size': len(self.code), 'masks': [[8, 4]],
            'fnv1a64': '%016x' % native_layouts.fingerprint(self.code, [[8, 4]])}}

    def resolve(self, code, executable=True):
        image = type('Image', (), {'data': code, 'sections': [(4096, len(code), 0, executable)]})()
        return native_layouts.resolve(image, self.guard)

    def test_relocated_code_and_address_operand(self):
        moved = self.code[:8] + b'\xaa\xbb\xcc\xdd' + self.code[12:]
        self.assertEqual(self.resolve(b'\xcc'*35 + moved), [4096+35])

    def test_fields_and_instructions_are_not_masked(self):
        for i in list(range(8)) + [12]:
            changed = bytearray(self.code); changed[i] ^= 1
            self.assertEqual(self.resolve(changed), [], i)

    def test_duplicate_and_non_executable_candidates(self):
        self.assertEqual(len(self.resolve(self.code + self.code)), 2)
        self.assertEqual(self.resolve(self.code, False), [])

    def test_truncation_and_section_boundary(self):
        for i in range(len(self.code)):
            self.assertEqual(self.resolve(self.code[:i]), [])
        self.assertEqual(self.resolve(self.code), [4096])
        data = b'XX' + self.code
        image = type('Image', (), {'data': data, 'sections': [
            (4096, len(data)-1, 0, True), (8192, 1, len(data)-1, True)]})()
        self.assertEqual(native_layouts.resolve(image, self.guard), [])

    def test_branch_target_disambiguates_identical_wrappers(self):
        import struct
        target_code = b'\x40\x57\x48\x83\xec\x20\xc3'
        target = {'id': 'hubs.rebuild', 'bytes': target_code.hex(), 'normalized': {
            'size': len(target_code), 'masks': [],
            'fnv1a64': '%016x' % native_layouts.fingerprint(target_code, [])}}
        self.guard['id'] = 'hubs.deferred'
        self.guard['normalized']['rel32_target'] = {'offset':8, 'end':12, 'layout':'hubs.rebuild'}
        correct = self.code[:8] + struct.pack('<i', 40-12) + self.code[12:]
        wrong = self.code[:8] + struct.pack('<i', 1234) + self.code[12:]
        data = correct + wrong + b'\xcc'*(40-26) + target_code
        image = type('Image', (), {'data':data,'sections':[(4096,len(data),0,True)]})()
        self.assertEqual(native_layouts.resolve(image,self.guard,[self.guard,target]),[4096])
        image.data = wrong + data[13:]
        self.assertEqual(native_layouts.resolve(image,self.guard,[self.guard,target]),[])

    def test_bad_masks_and_generated_header(self):
        for masks in ([[6,4]], [[8,8]], [[8,4],[9,4]], [[12,4]]):
            self.guard['normalized']['masks'] = masks
            with self.assertRaises(ValueError): native_layouts.validate(self.guard)
        contract = json.loads((ROOT/'compatibility/game-contract.json').read_text())
        self.assertEqual(native_layouts.header(contract),
            (ROOT/'native/SkiEONativeTerrain/layout_profiles.h').read_text())

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_shipped_c_scan_agrees_and_does_not_mutate_input(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p/'probe.c').write_text('''#include "layout_resolution.h"
unsigned probe(const uint8_t *data, size_t size, size_t *offset, uint64_t hash) {
    const uint8_t prefix[]={0x48,0x8b,0x81,0x60,0x0b,0,0};
    const SkiEOAddressMask masks[]={{8,4}};
    const SkiEOCodeLayout layout={prefix,7,13,masks,1,hash};
    return skieo_code_layout_scan(&layout,data,size,offset);
}''')
            subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                '-I',str(ROOT/'native/SkiEONativeTerrain'),str(p/'probe.c'),'-o',str(p/'probe.so')],check=True,capture_output=True)
            fn = ctypes.CDLL(str(p/'probe.so')).probe
            fn.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t),ctypes.c_uint64]
            fn.restype=ctypes.c_uint
            for data in (b'', self.code[:-1], self.code, b'XX'+self.code, self.code*2,
                         self.code[:8]+b'\x00'*4+self.code[12:]):
                raw=ctypes.create_string_buffer(data);offset=ctypes.c_size_t()
                count=fn(raw,len(data),ctypes.byref(offset),int(self.guard['normalized']['fnv1a64'],16))
                expected=self.resolve(data)
                self.assertEqual(count,len(expected))
                if count==1:self.assertEqual(offset.value,expected[0]-4096)
                self.assertEqual(raw.raw[:-1],data)
