"""Read-only semantic counterpart of native/SkiEOTrailRatings/rating_resolver.h.

Both resolvers are exercised against identical relocated/malformed fixtures.
This is a code contract, not automatic approval of an untested game version.
"""
from pathlib import Path
import math
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
CODE, CONST, DATA = 1, 2, 4


def guards():
    header = (ROOT / 'native/SkiEOTrailRatings/rating_profile.h').read_text()
    result = {}
    for name in ('calculate', 'palette', 'color'):
        body = re.search(r'rating_' + name + r'_guard\[\]\s*=\s*\{([^}]+)\}', header)[1]
        result[name] = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]{2})', body))
    return result


def pe_sections(image):
    """Keep section permissions and virtual zero-fill for writable globals."""
    data = image.data
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    count, optional = struct.unpack_from('<H', data, pe+6)[0], struct.unpack_from('<H', data, pe+20)[0]
    result = []
    for i in range(count):
        at = pe+24+optional+i*40
        size, rva, raw_size, raw = struct.unpack_from('<IIII', data, at+8)
        if not size:
            continue
        flags = struct.unpack_from('<I', data, at+36)[0]
        if size > 512*1024*1024 or rva+size > 0xFFFFFFFF:
            raise ValueError('unbounded rating section')
        kind = CODE if flags & 0x20000000 else DATA if flags & 0x80000000 else CONST
        result.append((rva, data[raw:raw+min(size, raw_size)].ljust(size, b'\0'), kind))
    return result


def resolve(sections):
    expected = guards()
    invalid = not 0 < len(sections) <= 96
    for i, (start, data, kind) in enumerate(sections):
        invalid |= start < 0 or not data or start+len(data) > 0xFFFFFFFF or kind not in (CODE, CONST, DATA)
        invalid |= any(start+len(data) > other and other+len(values) > start for other, values, _ in sections[:i])
    if invalid:
        return dict(calculate=0, palette=0, color=0, style=0)

    def read(rva, size, kind):
        for start, data, flags in sections:
            if flags & kind and start <= rva and rva-start+size <= len(data):
                return data[rva-start:rva-start+size]
        return b''

    def relative(code, rva, at, end):
        return rva+end+struct.unpack_from('<i', code, at)[0]

    def shape(code, name, addresses, size):
        if len(code) != size:
            return False
        ignored = {x for at in addresses for x in range(at, at+4)}
        return all(i in ignored or v == expected[name][i] for i, v in enumerate(code))

    def candidate(name, rva, palette):
        if name == 'calculate':
            code = read(rva, 35, CODE)
            if not shape(code, name, (3, 15, 27), 35):
                return False
            limits = [read(relative(code, rva, at, at+4), 4, CONST) for at in (3, 15, 27)]
            if any(len(value) != 4 for value in limits):
                return False
            a, b, c = (struct.unpack('<f', value)[0] for value in limits)
            return all(math.isfinite(v) for v in (a, b, c)) and 0 < c < b < a <= 90
        if name == 'palette':
            code = read(rva, 65, CODE)
            if not shape(code, name, (27, 43, 56), 65):
                return 0
            targets = [relative(code, rva, at, at+5) for at in (27, 43, 56)]
            value = read(targets[0], 1, DATA)
            return targets[0] if 0 < targets[0] < 0xFFFFFFFF and len(set(targets)) == 1 and value and value[0] <= 3 else 0
        code = read(rva, 205, CODE)
        if not palette or not shape(code, name, (13, 32, 39, 189), 205):
            return False
        if relative(code, rva, 13, 17) != palette or relative(code, rva, 32, 36) != 0:
            return False
        table = read(struct.unpack_from('<I', code, 39)[0], 28, CODE)
        return table == struct.pack('<7I', *(rva+x for x in (0x30, 0x4c, 0x68, 0x84, 0xba, 0x84, 0x9c))) and (
            read(relative(code, rva, 189, 193), 16, CONST) == struct.pack('<4f', 1, 1, 1, 1))

    result = dict(calculate=0, palette=0, color=0, style=0)
    for name in ('palette', 'calculate', 'color'):
        matches = []
        for start, data, flags in sections:
            if not flags & CODE:
                continue
            lead = b'\x40' if name == 'color' else b'\x0f'
            at = data.find(lead)
            while at >= 0:
                rva = start+at
                if rva % 16 == 0:
                    value = candidate(name, rva, result['palette'])
                    if value:
                        matches.append((rva, value))
                        if len(matches) > 1:
                            break
                at = data.find(lead, at+1)
            if len(matches) > 1:
                break
        if len(matches) == 1:
            result[name] = matches[0][0]
            if name == 'palette':
                result['style'] = matches[0][1]
    return result
