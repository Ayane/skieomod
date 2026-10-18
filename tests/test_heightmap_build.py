import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from tools import custom_map as cli, skieo_project as projects
from tools.custom_packages import ManifestError


def png16(width, height, samples, filtering=0):
    def chunk(tag, payload):
        return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload))
    rows = bytearray()
    previous = bytes(width * 2)
    for y in range(height):
        row = struct.pack('>' + 'H' * width, *samples[y * width:(y + 1) * width])
        rows.append(filtering)
        for x, value in enumerate(row):
            a, b, c = row[x - 2] if x >= 2 else 0, previous[x], previous[x - 2] if x >= 2 else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            paeth = a if pa <= pb and pa <= pc else b if pb <= pc else c
            prediction = (0, a, b, (a + b) // 2, paeth)[filtering]
            rows.append((value - prediction) & 255)
        previous = row
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 16, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


class HeightmapBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / 'project'
        projects.create('map', self.project, 'Test terrain', 'test.terrain')
        self.samples = [1000, 30000, 65535, 250, 14000, 50000, 0, 900, 12345, 60000, 4567, 8910, 3456, 6543, 4321]
        self.raw = struct.pack('<15H', *self.samples)

    def configure(self, data, suffix='.png', **settings):
        self.input = self.project / ('Terrain/source' + suffix)
        self.input.write_bytes(data)
        path = self.project / 'custom-map.json'
        manifest = json.loads(path.read_text())
        manifest['build'] = {'heightmap': {'file': 'Terrain/source' + suffix,
                                         'spacing_meters': 8, 'elevation_meters': [800, 2200], **settings}}
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        return manifest

    def build(self, **options):
        with contextlib.redirect_stdout(io.StringIO()):
            return projects.build(self.project, **options)

    def omit_elevation(self):
        path = self.project / 'custom-map.json'
        manifest = json.loads(path.read_text())
        del manifest['build']['heightmap']['elevation_meters']
        path.write_text(json.dumps(manifest))

    def test_minimal_raw_build_infers_square_and_reports_relative_elevation(self):
        samples = [1200, 2400, 6000, 9500, 15000, 17000, 32000, 41000, 54000]
        for format, order in [('r16le', '<'), ('r16be', '>')]:
            with self.subTest(format=format):
                self.configure(struct.pack(order + '9H', *samples), '.r16', format=format)
                self.omit_elevation()
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    path, release = projects.build(self.project)
                terrain = release['manifest']['terrain']
                self.assertEqual(terrain['source']['vertices'], [3, 3])
                self.assertEqual(terrain['size_meters'], [16, 16])
                self.assertEqual(terrain['elevation_meters'], [0, 1000])
                self.assertEqual(terrain['preview']['samples'][0][0], 0)
                self.assertEqual(terrain['preview']['samples'][-1][-1], 1)
                self.assertIn('assumed square', output.getvalue())
                self.assertIn('Real altitudes are unknown', output.getvalue())
                working = json.loads((self.project / 'custom-map.json').read_text())
                self.assertNotIn('vertices', working['build']['heightmap'])
                self.assertNotIn('elevation_meters', working['build']['heightmap'])
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.read('Terrain/heightmap.r16'), struct.pack('<9H', *samples))
                    report = json.loads(archive.read('Terrain/Generated/build-report.json'))['heightmap']
                    self.assertEqual(report['elevation_mode'], 'relative_range')
                    self.assertEqual(len(report['assumptions']), 2)
                before = path.read_bytes()
                self.build()
                self.assertEqual(path.read_bytes(), before)

    def test_minimal_png_uses_rectangular_header_and_relative_elevation(self):
        self.configure(png16(3, 5, [value + 100 for value in range(15)]))
        self.omit_elevation()
        path, release = self.build()
        terrain = release['manifest']['terrain']
        self.assertEqual(terrain['source']['vertices'], [3, 5])
        self.assertEqual(terrain['size_meters'], [16, 32])
        self.assertEqual(terrain['elevation_meters'], [0, 1000])
        with zipfile.ZipFile(path) as archive:
            assumptions = json.loads(archive.read('Terrain/Generated/build-report.json'))['heightmap']['assumptions']
        self.assertEqual(len(assumptions), 1)
        self.assertNotIn('square', assumptions[0])

    def test_raw_one_dimension_and_known_rectangle_override_square_assumption(self):
        for vertices in ([3, None], [None, 5]):
            self.configure(self.raw, '.r16', vertices=vertices)
            _, release = self.build()
            self.assertEqual(release['manifest']['terrain']['source']['vertices'], [3, 5])
            self.assertEqual(release['manifest']['terrain']['elevation_meters'], [800, 2200])
        self.configure(struct.pack('<36H', *range(36)), '.r16', vertices=[3, 12])
        path, release = self.build()
        self.assertEqual(release['manifest']['terrain']['source']['vertices'], [3, 12])
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(json.loads(archive.read('Terrain/Generated/build-report.json'))['heightmap']['assumptions'], [])

    def test_inference_fails_clearly_for_unknown_rectangle_and_incomplete_encoding(self):
        self.configure(self.raw, '.r16')
        with self.assertRaisesRegex(ValueError, 'not a square'):
            self.build()
        self.configure(self.raw, '.r16', vertices=[4, None])
        with self.assertRaisesRegex(ValueError, 'not divisible'):
            self.build()
        for invalid in ({'height_scale_meters': .1}, {'height_offset_meters': 10},
                        {'elevation_meters': [None, 1000]}, {'height_scale_meters': None}):
            self.configure(png16(3, 5, self.samples))
            self.omit_elevation()
            path = self.project / 'custom-map.json'
            manifest = json.loads(path.read_text())
            manifest['build']['heightmap'].update(invalid)
            path.write_text(json.dumps(manifest))
            before = path.read_bytes()
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.build()
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse((self.project / '.heightmap-backups').exists())

    def test_test_with_inferred_metadata_leaves_project_unchanged(self):
        self.configure(struct.pack('<9H', *range(9)), '.r16')
        self.omit_elevation()
        before = {file.relative_to(self.project): file.read_bytes() for file in self.project.rglob('*') if file.is_file()}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['test', str(self.project)]), 0)
        after = {file.relative_to(self.project): file.read_bytes() for file in self.project.rglob('*') if file.is_file()}
        self.assertEqual(after, before)

    def test_all_png_filters_preserve_samples_and_calculate_metadata(self):
        for filtering in range(5):
            with self.subTest(filtering=filtering):
                original = png16(3, 5, self.samples, filtering)
                self.configure(original)
                path, release = self.build()
                terrain = release['manifest']['terrain']
                self.assertEqual(terrain['source']['vertices'], [3, 5])
                self.assertEqual(terrain['size_meters'], [16, 32])
                self.assertEqual(terrain['elevation_meters'], [800, 2200])
                self.assertEqual(terrain['origin_centimeters'], [-800, -1600, 0])
                self.assertEqual(terrain['preview']['samples'][0][0], round(1000 / 65535, 5))
                self.assertEqual(terrain['preview']['samples'][-1][-1], round(4321 / 65535, 5))
                self.assertEqual(self.input.read_bytes(), original)
                self.assertEqual((self.project / 'Terrain/heightmap.r16').read_bytes(), self.raw)
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.read('Terrain/heightmap.r16'), self.raw)
                    self.assertNotIn('build', json.loads(archive.read('custom-map.json')))
                    self.assertNotIn('Terrain/source.png', archive.namelist())
                working = json.loads((self.project / 'custom-map.json').read_text())
                self.assertEqual(working['terrain'], terrain)
                self.assertEqual(working['build']['heightmap']['file'], 'Terrain/source.png')

    def test_raw_endianness_and_nonzero_sample_range(self):
        for order, encoding in [('<', 'r16le'), ('>', 'r16be')]:
            self.configure(struct.pack(order + '15H', *self.samples), '.r16', format=encoding, vertices=[3, 5])
            _, release = self.build()
            self.assertEqual((self.project / 'Terrain/heightmap.r16').read_bytes(), self.raw)
            self.assertEqual(release['manifest']['terrain']['source']['format'], 'r16le')
        self.configure(struct.pack('<15H', *[value + 10 for value in range(15)]), '.r16', vertices=[3, 5])
        _, release = self.build()
        source = release['manifest']['terrain']['source']
        self.assertAlmostEqual(source['height_offset_meters'] + 10 * source['height_scale_meters'], 800)
        self.assertAlmostEqual(source['height_offset_meters'] + 24 * source['height_scale_meters'], 2200)

    def test_exporter_encoding_row_order_and_explicit_rendering_stride(self):
        self.configure(png16(3, 5, self.samples), elevation_meters=None,
                       height_scale_meters=.025, height_offset_meters=724,
                       row_order='south_to_north', sample_step=2)
        manifest = json.loads((self.project / 'custom-map.json').read_text())
        del manifest['build']['heightmap']['elevation_meters']
        (self.project / 'custom-map.json').write_text(json.dumps(manifest))
        _, release = self.build()
        terrain = release['manifest']['terrain']
        self.assertEqual(terrain['elevation_meters'], [724, 724 + 65535 * .025])
        self.assertEqual(terrain['preview']['samples'][0][0], round(3456 / 65535, 5))
        self.assertEqual(terrain['runtime']['sample_step'], 2)

    def test_plain_build_is_reproducible_and_reads_updated_source(self):
        self.configure(png16(3, 5, self.samples))
        path, _ = self.build()
        before = path.read_bytes()
        manifest = (self.project / 'custom-map.json').read_bytes()
        backups = len(list((self.project / '.heightmap-backups').iterdir()))
        self.build()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.project / 'custom-map.json').read_bytes(), manifest)
        self.assertEqual(len(list((self.project / '.heightmap-backups').iterdir())), backups)
        updated = list(reversed(self.samples))
        self.input.write_bytes(png16(3, 5, updated))
        self.build()
        self.assertNotEqual(path.read_bytes(), before)
        self.assertEqual((self.project / 'Terrain/heightmap.r16').read_bytes(), struct.pack('<15H', *updated))

    def test_project_test_has_no_source_mutations_and_cli_has_no_heightmap_parameter(self):
        self.configure(png16(3, 5, self.samples))
        before = (self.project / 'custom-map.json').read_bytes()
        raw_before = (self.project / 'Terrain/heightmap.r16').read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['test', str(self.project)]), 0)
            self.assertEqual(cli.main(['build', str(self.project)]), 0)
        self.assertNotEqual((self.project / 'custom-map.json').read_bytes(), before)
        self.assertNotEqual((self.project / 'Terrain/heightmap.r16').read_bytes(), raw_before)
        self.assertNotIn('--heightmap', cli.create_parser()[1]['build'].format_help().split('Examples:')[0])
        # Read-only test before the build, in a fresh project.
        self.configure(png16(3, 5, self.samples))
        before = (self.project / 'custom-map.json').read_bytes()
        backups = len(list((self.project / '.heightmap-backups').iterdir()))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['test', str(self.project)]), 0)
        self.assertEqual((self.project / 'custom-map.json').read_bytes(), before)
        self.assertEqual(len(list((self.project / '.heightmap-backups').iterdir())), backups)

    def test_failed_build_keeps_previous_archive_manifest_and_generated_terrain(self):
        self.configure(png16(3, 5, self.samples))
        path, _ = self.build()
        for invalid in [png16(3, 5, self.samples)[:-2], b'not a PNG', png16(3, 5, self.samples) + b'corrupt trailer']:
            self.input.write_bytes(invalid)
            before = [(file, file.read_bytes()) for file in [path, self.project / 'custom-map.json', self.project / 'Terrain/heightmap.r16']]
            with self.assertRaises((ValueError, ManifestError)):
                self.build()
            for file, content in before:
                self.assertEqual(file.read_bytes(), content)

    def test_rejected_settings_and_invalid_raw_dimensions_do_not_write_sources(self):
        cases = [({'spacing_meters': 0}, '.png'), ({'vertices': [4, 5]}, '.png'),
                 ({'elevation_meters': [2200, 800]}, '.png'), ({'height_scale_meters': 1}, '.png'),
                 ({'sample_step': 0}, '.png'), ({'vertices': [3, 6]}, '.r16'),
                 ({'vertices': [True, 5]}, '.r16'), ({}, '.r16'), ({'row_order': 'wrong'}, '.png')]
        for settings, suffix in cases:
            with self.subTest(settings=settings):
                self.configure(self.raw if suffix == '.r16' else png16(3, 5, self.samples), suffix, **settings)
                before = (self.project / 'custom-map.json').read_bytes()
                with self.assertRaises((ValueError, ManifestError)):
                    self.build()
                self.assertEqual((self.project / 'custom-map.json').read_bytes(), before)
                self.assertFalse((self.project / '.heightmap-backups').exists())

    def test_archive_commit_failure_restores_generated_files(self):
        self.configure(png16(3, 5, self.samples))
        path, _ = self.build()
        self.input.write_bytes(png16(3, 5, list(reversed(self.samples))))
        before = [(file, file.read_bytes()) for file in [path, self.project / 'custom-map.json', self.project / 'Terrain/heightmap.r16']]
        replace = Path.replace
        def fail_archive(file, target):
            if file.name.endswith('.part'):
                raise OSError('simulated archive commit failure')
            return replace(file, target)
        with patch.object(Path, 'replace', fail_archive), self.assertRaises(OSError):
            self.build()
        for file, content in before:
            self.assertEqual(file.read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
