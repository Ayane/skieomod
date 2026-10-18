"""Production C and read-only Python resolvers must agree after game relocation."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools import trail_rating_profile as profile
from tools import check_game_compatibility as protocol

ROOT = Path(__file__).resolve().parents[1]


def fixture(code_shift=0, constant_shift=0, data_shift=0):
    code, const, data = bytearray(0x3000), bytearray(0x1000), bytearray(0x100)
    first, ro, rw = 0x1000+code_shift, 0x5000+constant_shift, 0x7000+data_shift
    addresses = dict(calculate=first+0x100, palette=first+0x500, color=first+0x900, style=rw+0x10)
    guards = profile.guards()
    for name in ('calculate', 'palette', 'color'):
        at = addresses[name]-first
        blob = guards[name]
        code[at:at+len(blob)] = blob
    def relative(name, offset, end, target):
        struct.pack_into('<i', code, addresses[name]-first+offset, target-addresses[name]-end)
    for i, offset in enumerate((3, 15, 27)):
        relative('calculate', offset, offset+4, ro+i*4)
        struct.pack_into('<f', const, i*4, (33, 27, 16)[i])
    for offset in (27, 43, 56):
        relative('palette', offset, offset+5, addresses['style'])
    relative('color', 13, 17, addresses['palette'])
    relative('color', 32, 36, 0)
    struct.pack_into('<I', code, addresses['color']-first+39, first+0xB00)
    struct.pack_into('<7I', code, 0xB00, *(addresses['color']+x for x in (0x30, 0x4C, 0x68, 0x84, 0xBA, 0x84, 0x9C)))
    relative('color', 189, 193, ro+0x100)
    struct.pack_into('<4f', const, 0x100, 1, 1, 1, 1)
    data[0x10] = 1
    return [(first, code, profile.CODE), (ro, const, profile.CONST), (rw, data, profile.DATA)], addresses


def pe_fixture(sections):
    data=bytearray(0x400+sum((len(blob)+0x1ff)&~0x1ff for _,blob,_ in sections))
    data[:2]=b'MZ';struct.pack_into('<I',data,0x3c,0x80);data[0x80:0x84]=b'PE\0\0'
    struct.pack_into('<HH',data,0x84,0x8664,len(sections))
    struct.pack_into('<H',data,0x94,0xf0);struct.pack_into('<H',data,0x98,0x20b)
    raw=0x400
    for i,(rva,blob,kind) in enumerate(sections):
        at=0x188+i*40
        struct.pack_into('<IIII',data,at+8,len(blob),rva,len(blob),raw)
        struct.pack_into('<I',data,at+36,{profile.CODE:0x60000020,profile.CONST:0x40000040,profile.DATA:0xc0000040}[kind])
        data[raw:raw+len(blob)]=blob
        raw+=(len(blob)+0x1ff)&~0x1ff
    return protocol.PEImage(bytes(data))


class ProtocolRatingResolverTests(unittest.TestCase):
    def guards(self):
        shapes=profile.guards()
        return [dict(id='trail_ratings.'+label,mode='rating_semantic',rva='0x1000',bytes=shapes[name].hex())
                for label,name in (('classifier','calculate'),('palette','palette'),('color','color'))]

    def test_protocol_uses_the_native_semantic_contract_for_relocations(self):
        sections,expected=fixture(0x40000,0x80000,0x100000)
        image=pe_fixture(sections)
        self.assertEqual(profile.resolve(profile.pe_sections(image)),expected)
        result=protocol.inspect_guards(image,self.guards())
        self.assertTrue(all(row['status']=='pass' and row['relocated'] for row in result))
        sections[0][1][expected['color']-sections[0][0]+0x50]^=1
        result=protocol.inspect_guards(pe_fixture(sections),self.guards())
        self.assertEqual([row['status'] for row in result],['pass','pass','fail'])

    def test_unknown_or_weakened_semantic_guard_is_rejected(self):
        image=pe_fixture(fixture()[0])
        for change in ({'id':'hubs.color'},{'bytes':'90'*205}):
            guard=self.guards()[2];guard.update(change)
            with self.assertRaises(ValueError):protocol.inspect_guards(image,[guard])


@unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
class NativeRatingResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        folder = Path(cls.temp.name)
        source = folder/'resolver.c'
        source.write_text('#include "rating_resolver.h"\n'
            'void resolve(const RatingSection *s,size_t count,uint32_t *out) {'
            'RatingImage image={s,count};RatingResolution r=rating_resolve(&image);'
            'out[0]=r.calculate;out[1]=r.palette;out[2]=r.color;out[3]=r.style;}\n')
        library = folder/'resolver.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
            '-I', str(ROOT/'native/SkiEOTrailRatings'), str(source), '-o', str(library)],
            check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(library))
        class Section(ctypes.Structure):
            _fields_ = [('data', ctypes.c_void_p), ('rva', ctypes.c_uint32), ('size', ctypes.c_uint32), ('kind', ctypes.c_uint32)]
        cls.Section = Section
        cls.lib.resolve.argtypes = [ctypes.POINTER(Section), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint32)]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def resolve(self, sections):
        before = [(a, bytes(b), c) for a, b, c in sections]
        buffers = [ctypes.create_string_buffer(bytes(data)) for _, data, _ in sections]
        entries = (self.Section*len(sections))(*[
            self.Section(ctypes.addressof(buffer), rva, len(data), kind)
            for buffer, (rva, data, kind) in zip(buffers, sections)])
        out = (ctypes.c_uint32*4)()
        self.lib.resolve(entries, len(entries), out)
        result = dict(zip(('calculate', 'palette', 'color', 'style'), out))
        self.assertEqual(result, profile.resolve(sections), 'C/Python compatibility checks diverged')
        self.assertEqual(before, [(a, bytes(b), c) for a, b, c in sections], 'read-only resolver changed memory')
        return result

    def test_independently_moved_code_literals_cache_and_jump_table(self):
        for shifts in ((0, 0, 0), (0x40000, 0x80000, 0x100000), (0x20000, 0, 0)):
            with self.subTest(shifts=shifts):
                sections, expected = fixture(*shifts)
                self.assertEqual(self.resolve(sections), expected)

    def test_valid_native_default_threshold_changes_remain_supported(self):
        sections, expected = fixture()
        struct.pack_into('<f', sections[1][1], 0, 34)
        self.assertEqual(self.resolve(sections), expected)

    def test_invalid_native_thresholds_disable_only_custom_thresholds(self):
        for value in (float('nan'), float('inf'), 10, 91):
            sections, expected = fixture()
            struct.pack_into('<f', sections[1][1], 0, value)
            expected['calculate'] = 0
            self.assertEqual(self.resolve(sections), expected)

    def test_conflicting_palette_references_disable_style_and_colors_only(self):
        sections, expected = fixture()
        at = expected['palette']-sections[0][0]+43
        displacement = struct.unpack_from('<i', sections[0][1], at)[0]
        struct.pack_into('<i', sections[0][1], at, displacement+1)
        expected.update(palette=0, color=0, style=0)
        self.assertEqual(self.resolve(sections), expected)

    def test_color_call_table_base_and_fallback_must_agree(self):
        for target in ('call', 'table', 'base', 'literal', 'opcode'):
            with self.subTest(target=target):
                sections, expected = fixture()
                offset = expected['color']-sections[0][0]
                if target == 'literal':
                    sections[1][1][0x100] ^= 1
                else:
                    at = {'call': offset+13, 'table': 0xB00, 'base': offset+32, 'opcode': offset+0x50}[target]
                    sections[0][1][at] ^= 1
                expected['color'] = 0
                self.assertEqual(self.resolve(sections), expected)

    def test_duplicate_semantically_valid_entry_is_rejected(self):
        for name in ('calculate', 'palette', 'color'):
            with self.subTest(name=name):
                sections, expected = fixture()
                # Relink a second function to the original literals/globals.
                # A byte copy alone would point to the wrong addresses.
                code = sections[0][1];base = sections[0][0]
                destination = base+0x1800
                length = 35 if name == 'calculate' else 65 if name == 'palette' else 205
                source = expected[name]
                blob = bytearray(code[source-base:source-base+length])
                refs = {'calculate': (3,15,27), 'palette': (27,43,56), 'color': (13,32,189)}[name]
                for at in refs:
                    value = struct.unpack_from('<i', blob, at)[0]
                    struct.pack_into('<i', blob, at, value+source-destination)
                if name == 'color':
                    struct.pack_into('<I', blob, 39, base+0x1A00)
                    struct.pack_into('<7I', code, 0x1A00, *(destination+x for x in (0x30,0x4c,0x68,0x84,0xba,0x84,0x9c)))
                code[destination-base:destination-base+len(blob)] = blob
                expected[name] = 0
                if name == 'palette':
                    expected.update(color=0, style=0)
                self.assertEqual(self.resolve(sections), expected)

    def test_permissions_bounds_overlaps_and_truncation_are_rejected(self):
        for index in (0, 1, 2):
            sections, expected = fixture()
            a, b, _ = sections[index]
            sections[index] = (a, b, (profile.DATA, profile.CODE, profile.CONST)[index])
            result = self.resolve(sections)
            self.assertFalse(result['color'])
        for sections in ([], [(1, bytearray(2), profile.CODE), (2, bytearray(2), profile.CODE)],
                         [(0xFFFFFFF0, bytearray(100), profile.CODE)]):
            self.assertEqual(self.resolve(sections), dict(calculate=0, palette=0, color=0, style=0))
        sections, expected = fixture()
        sections[0] = (sections[0][0], sections[0][1][:0x900+204], profile.CODE)
        expected['color'] = 0
        self.assertEqual(self.resolve(sections), expected)


if __name__ == '__main__':
    unittest.main()
