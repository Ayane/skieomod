import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools import custom_map as cli
from tools.custom_packages import inspect_package


COMMANDS = ('editor', 'uri', 'create', 'new', 'build', 'test', 'run', 'publish', 'pack', 'list',
            'install', 'play', 'setup', 'update', 'uninstall-self', 'config', 'help')


class HelpTests(unittest.TestCase):
    def invoke(self, argv, exits=False):
        output = io.StringIO()
        with patch.object(cli.desktop, 'load_config', side_effect=AssertionError('help must not read configuration')), \
             patch.object(cli.desktop, 'configure', side_effect=AssertionError('help must not configure the game')), \
             patch.object(cli.workshop, 'call', side_effect=AssertionError('help must not contact Steam')), \
             contextlib.redirect_stdout(output):
            if exits:
                with self.assertRaises(SystemExit) as result:
                    cli.main(argv)
                self.assertEqual(result.exception.code, 0)
            else:
                self.assertEqual(cli.main(argv), 0)
        return output.getvalue()

    def test_general_help_and_empty_invocation_need_no_game(self):
        general = self.invoke([])
        self.assertEqual(self.invoke(['help']), general)
        for flag in ('-h', '--help'):
            self.assertEqual(self.invoke([flag], exits=True), general)
        self.assertIn('skieomod create map', general)
        self.assertIn('Steamworks client', general)
        for command in COMMANDS:
            self.assertIn(command, general)

    def test_every_command_has_help_descriptions_and_examples(self):
        for command in COMMANDS:
            with self.subTest(command=command):
                direct = self.invoke([command, '--help'], exits=True)
                self.assertEqual(self.invoke(['help', command]), direct)
                self.assertEqual(self.invoke([command, '-h'], exits=True), direct)
                self.assertIn('Example', direct)
                self.assertIn('skieomod ', direct)

    def test_template_help_works_before_creating_anything(self):
        for kind in ('map', 'mod', 'mapmod'):
            with self.subTest(kind=kind):
                help_text = self.invoke(['create', kind, '--help'], exits=True)
                self.assertIn('--author', help_text)
                self.assertIn('--output', help_text)
                self.assertIn('mapmod', help_text)

    def test_unknown_help_topic_and_command_report_usage_errors(self):
        for argv in (['help', 'unknown'], ['unknown'], ['uninstall'], ['help', 'uninstall'],
                     ['create'], ['create', 'unknown']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as result:
                    cli.main(argv)
                self.assertEqual(result.exception.code, 2)
                self.assertIn('usage: skieomod', errors.getvalue())


class CreateCommandTests(unittest.TestCase):
    def test_large_rectangular_map_builds_with_matching_source_and_documentation(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / 'large map'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['create', 'map', '-o', str(project),
                    '--size', '16000', '12000', '--spacing', '8']), 0)
                self.assertEqual(cli.main(['build', str(project)]), 0)
                self.assertEqual(cli.main(['test', str(project)]), 0)
            terrain = json.loads((project / 'custom-map.json').read_text())['terrain']
            self.assertEqual(terrain['source']['vertices'], [2001, 1501])
            self.assertEqual(terrain['size_meters'], [16000, 12000])
            self.assertEqual(terrain['origin_centimeters'], [-800000, -600000, 0])
            self.assertEqual(terrain['runtime']['sample_step'], 4)
            self.assertIn('2001 x 1501', (project / 'docs/terrain.md').read_text())
            with zipfile.ZipFile(next((project / 'bin').glob('*.skieomap'))) as archive:
                self.assertEqual(len(archive.read('Terrain/heightmap.r16')), 2001 * 1501 * 2)

    def test_invalid_dimensions_do_not_create_partial_projects(self):
        cases = [('map', ['--size', '16000', '12001', '--spacing', '8']),
                 ('map', ['--size', '0', '12000']),
                 ('map', ['--size', 'nan', '12000']),
                 ('map', ['--spacing', '0']),
                 ('map', ['--size', '1e308', '12000', '--spacing', '1e-300']),
                 ('map', ['--size', '32000', '32000', '--spacing', '4']),
                 ('map', ['--size', '20000', '16', '--spacing', '1']),
                 ('mod', ['--size', '16000', '12000']),
                 ('mapmod', ['--spacing', '8'])]
        with tempfile.TemporaryDirectory() as temporary:
            for index, (kind, options) in enumerate(cases):
                with self.subTest(kind=kind, options=options):
                    project = Path(temporary) / str(index)
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        self.assertNotEqual(cli.main(['create', kind, '-o', str(project), *options]), 0)
                    self.assertFalse(project.exists())

    def test_create_and_new_build_all_templates_from_another_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for command in ('create', 'new'):
                for kind in ('map', 'mod', 'mapmod'):
                    with self.subTest(command=command, kind=kind):
                        project = root / (command + ' ' + kind)
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(cli.main([command, kind, '-o', str(project),
                                '--name', 'Ma station', '--id', 'author.' + kind, '--author', 'Auteur']), 0)
                            self.assertEqual(cli.main(['build', str(project)]), 0)
                            self.assertEqual(cli.main(['test', str(project)]), 0)
                        self.assertIn(str(project / 'README.md'), output.getvalue())
                        self.assertIn('skieomod build "' + str(project) + '"', output.getvalue())
                        archive = next((project / 'bin').glob('*'))
                        _, manifest, _ = inspect_package(archive)
                        self.assertEqual(manifest['metadata']['authors'], ['Auteur'])

    def test_create_conflict_is_reported_without_touching_existing_docs(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / 'docs').mkdir()
            existing = project / 'docs/scripting.md'
            existing.write_text('authored guide', encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(['create', 'mod', '-o', str(project)]), 2)
            self.assertIn('Refusing to overwrite', errors.getvalue())
            self.assertEqual(existing.read_text(), 'authored guide')
            self.assertEqual(list(project.rglob('*')), [project / 'docs', existing])


if __name__ == '__main__':
    unittest.main()
