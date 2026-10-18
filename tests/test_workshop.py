import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import custom_map as cli, skieo_project as projects, skieo_workshop as workshop
from tools.custom_packages import ManifestError, resolve


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'SKIEOMOD_CONFIG_DIR': str(self.root / 'config')})
        env.start(); self.addCleanup(env.stop)

    def project(self, kind='map'):
        path = self.root / kind
        projects.create(kind, path, 'Snow slope', 'author.' + kind)
        archive, release = projects.build(path)
        return path, archive, release

    def test_all_templates_stage_loose_content_and_small_query_metadata(self):
        for kind in ['map', 'mod', 'mapmod']:
            path, archive, release = self.project(kind)
            output, request = workshop.prepare(archive, path)
            self.assertTrue((output / 'content' / (release['manifest']['script']['entry'] if kind == 'map' else 'Scripts/main.lua')).is_file())
            self.assertFalse(any(p.suffix in {'.skieomap', '.skieomod', '.zip'} for p in (output / 'content').rglob('*')))
            self.assertEqual(request['visibility'], 'private')
            self.assertEqual(request['published_file_id'], '0')
            self.assertEqual(json.loads(request['metadata'])['package_version'], release['version'])
            self.assertNotIn('terrain', json.loads(request['metadata']))
            self.assertEqual((output / 'preview.png').read_bytes(), (path / 'preview.png').read_bytes())

    def test_required_dependencies_need_pinned_workshop_ids(self):
        path, _, _ = self.project()
        source = path / 'custom-map.json'
        manifest = json.loads(source.read_text())
        manifest['dependencies'] = [{'id': 'author.snow', 'version': '^1.0.0'}]
        source.write_text(json.dumps(manifest))
        archive, _ = projects.build(path)
        with self.assertRaises(ManifestError): workshop.prepare(archive, path)
        manifest['dependencies'][0]['workshop_id'] = '9007199254740993'
        source.write_text(json.dumps(manifest))
        archive, _ = projects.build(path)
        _, request = workshop.prepare(archive, path)
        self.assertEqual(request['required_items'], ['9007199254740993'])
        with self.assertRaises(ManifestError): workshop.prepare(archive, path, published_id='9007199254740993')

    def test_optional_dependency_is_not_forced_into_steam_required_items(self):
        path, _, _ = self.project()
        source = path / 'custom-map.json'; manifest = json.loads(source.read_text())
        manifest['dependencies'] = [{'id': 'author.extra', 'optional': True}]
        source.write_text(json.dumps(manifest))
        archive, _ = projects.build(path)
        self.assertEqual(workshop.prepare(archive, path)[1]['required_items'], [])

    def test_uint64_ids_keep_precision_and_reject_numeric_json(self):
        for value in ['1', '9007199254740993', '18446744073709551614']:
            self.assertEqual(workshop.item_id(value), value)
        for value in [1, 1.0, '', '0', '-1', '01', '18446744073709551615', '18446744073709551616', '1;bad']:
            with self.assertRaises(ManifestError): workshop.item_id(value)

    def test_failed_preview_validation_preserves_previous_staging(self):
        path, archive, _ = self.project()
        output, _ = workshop.prepare(archive, path)
        original = (output / 'publish-request.json').read_bytes()
        with self.assertRaises(ManifestError): workshop.prepare(archive, path, preview='missing.png')
        self.assertEqual((output / 'publish-request.json').read_bytes(), original)

    def test_duplicate_staging_replaces_previous_build_without_source_loss(self):
        path, archive, _ = self.project()
        output, _ = workshop.prepare(archive, path)
        (output / 'content/obsolete.txt').write_text('old')
        workshop.prepare(archive, path, changenote='Update')
        self.assertFalse((output / 'content/obsolete.txt').exists())
        self.assertTrue((path / 'Scripts/main.lua').exists())

    def test_publisher_persists_created_id_even_when_legal_acceptance_is_needed(self):
        path, archive, _ = self.project()
        _, request = workshop.prepare(archive, path)
        with patch.object(workshop, 'call', return_value={'published_file_id': '12345678', 'needs_legal_agreement': True}):
            result = workshop.publish(request, path)
        self.assertTrue(result['needs_legal_agreement'])
        self.assertEqual(workshop.prepare(archive, path)[1]['published_file_id'], '12345678')

    def test_update_cannot_silently_change_article_identity(self):
        path, archive, _ = self.project()
        _, request = workshop.prepare(archive, path, published_id='123')
        with patch.object(workshop, 'call', return_value={'published_file_id': '456'}), self.assertRaises(ManifestError):
            workshop.publish(request, path)
        self.assertEqual(json.loads((path / 'workshop.json').read_text())['published_file_id'], '0')

    def test_client_rejects_cross_game_response_and_uses_no_shell(self):
        payload = workshop.request('query', workshop.APP_ID, page=1)
        response = {'format': workshop.FORMAT, 'version': 1, 'app_id': '480', 'ok': True}
        with patch.object(workshop.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr='')) as process:
            with self.assertRaises(ManifestError): workshop.call(payload, '/path with spaces/steam-helper')
            self.assertEqual(process.call_args.args[0], ['/path with spaces/steam-helper'])
            self.assertFalse(process.call_args.kwargs.get('shell', False))

    def test_missing_client_never_falls_back_to_web_repository(self):
        with self.assertRaisesRegex(ManifestError, 'not connected'):
            workshop.call(workshop.request('query', workshop.APP_ID), config={})

    def test_prepare_command_is_functional_without_steam_or_game(self):
        path, _, _ = self.project('mapmod')
        with patch.object(workshop, 'call') as client, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['publish', str(path), '--prepare']), 0)
            client.assert_not_called()
        self.assertTrue((path / 'bin/workshop/content/custom-mod.json').is_file())

    def test_manifest_workshop_pin_prevents_same_name_from_different_publisher(self):
        _, _, mod = self.project('mapmod')
        root = {'id': 'author.map', 'kind': 'map', 'version': '1.0.0', 'manifest': {'dependencies': [{'id': mod['id'], 'workshop_id': '123'}]}}
        with self.assertRaises(ManifestError): resolve([root, {**mod, 'workshop_id': '456'}], root['id'])
        resolved = resolve([root, {**mod, 'workshop_id': '123'}], root['id'])
        self.assertEqual(resolved[0]['workshop_id'], '123')

    def test_offline_discovery_reads_steam_inventory_not_arbitrary_folders(self):
        steamapps = self.root / 'steamapps'; folder = steamapps / 'workshop/content' / workshop.APP_ID / '123'
        projects.create('mapmod', folder, 'Tools', 'author.tools')
        (steamapps / 'workshop/appworkshop_4493130.acf').write_text('"AppWorkshop" { "appid" "4493130" "WorkshopItemsInstalled" { "123" { "manifest" "9" } } }')
        projects.create('mapmod', folder.parent / '456', 'Untracked', 'author.untracked')
        with patch.object(workshop.desktop, 'steam_libraries', return_value=[]), tempfile.TemporaryDirectory() as temporary:
            releases, _ = workshop.installed({'steamapps_dir': str(steamapps), 'app_id': workshop.APP_ID}, temporary)
        self.assertEqual([r['workshop_id'] for r in releases], ['123'])


if __name__ == '__main__': unittest.main()
