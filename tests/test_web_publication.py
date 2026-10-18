import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError

from tools import custom_map as cli, skieo_repository as web
from tools.custom_packages import ManifestError
from tests.test_repository import archive_bytes, map_manifest, mod_manifest
from tests import test_repository as repository_tests


class WebPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / 'map.skieomap'
        self.archive.write_bytes(archive_bytes(map_manifest()))
        self.env = patch.dict(os.environ, {'CUSTOM_MAP_TOKEN': 'test-token',
            'CUSTOM_MAP_REPOSITORY': 'https://skieomod.emillon.fr'})
        self.env.start(); self.addCleanup(self.env.stop)

    def opener(self, result=None):
        opener = Mock()
        opener.open.return_value.__enter__ = lambda _: io.BytesIO(json.dumps(
            result or {'id': 'test.alpine', 'version': '1.0.0'}).encode())
        opener.open.return_value.__exit__ = lambda *args: None
        return opener

    def test_archive_publication_reaches_existing_api_and_is_discoverable(self):
        fixture = repository_tests.RepositoryTests(); fixture.setUp(); self.addCleanup(fixture.tearDown)
        os.environ['CUSTOM_MAP_TOKEN'] = fixture.token
        opener = self.opener()
        def request(req, timeout):
            self.assertEqual(req.get_method(), 'POST')
            self.assertEqual(req.full_url, 'https://skieomod.emillon.fr/api/v1/packages?kind=map')
            self.assertEqual(req.get_header('Content-type'), 'application/zip')
            token = req.get_header('Authorization').removeprefix('Bearer ')
            response = fixture.request(req.full_url, 'POST', req.data, token)
            self.assertEqual(response['status'], 201, response)
            result = io.BytesIO(response['body'])
            return result
        opener.open.side_effect = request
        with patch.object(web, 'build_opener', return_value=opener), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['publish', str(self.archive)]), 0)
        registry = fixture.request('/api/v1/registry')['json']
        self.assertEqual([p['id'] for p in registry['packages']], ['test.alpine'])

    def test_mod_archives_use_the_mod_endpoint(self):
        self.archive.write_bytes(archive_bytes(mod_manifest()))
        opener = self.opener({'id': 'test.snow-tools', 'version': '1.0.0'})
        with patch.object(web, 'build_opener', return_value=opener): web.publish(self.archive)
        self.assertTrue(opener.open.call_args.args[0].full_url.endswith('?kind=mod'))

    def test_missing_token_and_invalid_archive_never_send_a_request(self):
        with patch.object(web, 'build_opener') as transport:
            os.environ.pop('CUSTOM_MAP_TOKEN')
            with self.assertRaisesRegex(ManifestError, 'CUSTOM_MAP_TOKEN'): web.publish(self.archive)
            os.environ['CUSTOM_MAP_TOKEN'] = 'test-token'
            self.archive.write_bytes(b'not a package')
            with self.assertRaises(ManifestError): web.publish(self.archive)
            transport.assert_not_called()

    def test_unsafe_origins_are_rejected_before_transport(self):
        with patch.object(web, 'build_opener') as transport:
            for origin in ['http://example.com', 'https://user:pass@example.com', 'https://example.com/path', 'https://example.com?q=1']:
                with self.subTest(origin=origin), self.assertRaises(ManifestError): web.publish(self.archive, origin)
            transport.assert_not_called()

    def test_legacy_domain_is_migrated_before_sending_token(self):
        opener = self.opener()
        with patch.object(web, 'build_opener', return_value=opener): web.publish(self.archive, 'https://skieomap.emillon.fr')
        self.assertTrue(opener.open.call_args.args[0].full_url.startswith('https://skieomod.emillon.fr/'))
        self.assertIsNone(web.NoRedirect().redirect_request(None, None, 308, '', {}, 'https://other.example'))

    def test_server_errors_do_not_echo_tokens_and_bad_identity_is_rejected(self):
        opener = self.opener({'id': 'wrong.map', 'version': '1.0.0'})
        with patch.object(web, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(ManifestError, 'Unexpected publication'): web.publish(self.archive)
            opener.open.side_effect = HTTPError('https://example.com', 403, 'test-token', {}, None)
            with self.assertRaises(ManifestError) as error: web.publish(self.archive)
            self.assertNotIn('test-token', str(error.exception))


if __name__ == '__main__': unittest.main()
