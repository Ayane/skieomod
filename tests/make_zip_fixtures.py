"""Create temporary ZIP fixtures used by the Lua format/registry tests."""
from pathlib import Path
import io
import json
import sys
import zipfile
import zlib
from test_repository import archive_bytes, map_manifest, mod_manifest


def create(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, compression in [('store', zipfile.ZIP_STORED), ('deflate', zipfile.ZIP_DEFLATED)]:
        (root / (name + '.zip')).write_bytes(archive_bytes(map_manifest(), compression=compression))
    updated = map_manifest()
    updated['metadata']['version'] = '2.0.0'
    (root / 'z-new.zip').write_bytes(archive_bytes(updated))
    for version in ('1.0.0', '2.0.0'):
        featured = map_manifest()
        featured['id'] = 'community.veymont'
        featured['metadata']['version'] = version
        (root / 'featured').mkdir(exist_ok=True)
        (root / 'featured' / ('featured-' + version + '.skieomap')).write_bytes(archive_bytes(featured))
    for version, mod_version in [('3.0.0', '1.0.0'), ('4.0.0', '2.0.0')]:
        featured = map_manifest()
        featured.update(id='community.veymont', dependencies=[{'id': 'test.foxes', 'version': '=' + mod_version}])
        featured['metadata']['version'] = version
        (root / 'featured' / ('featured-' + version + '.skieomap')).write_bytes(archive_bytes(featured))
        (root / 'featured' / ('foxes-' + mod_version + '.skieomod')).write_bytes(archive_bytes(mod_manifest('test.foxes', mod_version)))
    class Unseekable(io.BytesIO):
        def seek(self, *args):
            raise OSError('unseekable')
    buffer = Unseekable()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('test.txt', b'overlapping backreferences ' * 3000)
    (root / 'descriptor.zip').write_bytes(buffer.getvalue())
    (root / 'unsafe.zip').write_bytes(archive_bytes(map_manifest(), extra=[('../bad', b'x')]))
    bad = bytearray(archive_bytes(map_manifest(), compression=zipfile.ZIP_STORED))
    bad[bad.index(b'Veymont')] ^= 1
    (root / 'bad-crc.zip').write_bytes(bad)
    (root / 'mod.skieomod').write_bytes(archive_bytes(mod_manifest()))
    raw = b'fixed blocks and overlaps ' * 4000
    compressor = zlib.compressobj(wbits=-15, strategy=zlib.Z_FIXED)
    (root / 'fixed.deflate').write_bytes(compressor.compress(raw) + compressor.flush())
    (root / 'expected.txt').write_bytes(raw)


if __name__ == '__main__':
    create(sys.argv[1])
