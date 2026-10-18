from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlparse, parse_qs
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from repository.server.app import Repository
from tools import custom_maps
from tools import custom_map as cli
from tools.custom_packages import inspect_package, pack_package, resolve, ManifestError

STEAM_ID = '76561198000000001'
OTHER_ID = '76561198000000002'


def mod_manifest(identifier='test.snow-tools', version='1.0.0', dependencies=None):
    return {'format': {'name': 'skieo-mod', 'version': '1.0.0'}, 'id': identifier,
            'metadata': {'name': 'Snow tools', 'description': 'Test mod', 'version': version, 'authors': ['Test']},
            'runtime': 'map-api', 'files': ['Scripts/main.lua'],
            'script': {'language': 'lua', 'api': '1.0', 'entry': 'Scripts/main.lua', 'permissions': ['gameplay']},
            'dependencies': dependencies or []}


def map_manifest():
    value = copy.deepcopy(json.loads((ROOT / 'mod/SkiEO-Veymont/custom-map.json').read_text()))
    value['id'] = 'test.alpine'
    value['metadata']['version'] = '1.0.0'
    value['terrain'] = {'size_meters': [2, 2], 'elevation_meters': [0, 100], 'origin_centimeters': [0, 0, 0],
        'source': {'file': 'Terrain/heightmap.r16', 'format': 'r16le', 'vertices': [3, 3], 'spacing_meters': 1, 'height_scale_meters': 1, 'height_offset_meters': 0},
        'preview': {'samples': [[0, 0, 0], [0, 1, 0], [0, 0, 0]]}}
    value['content'] = {'assets': []}
    value['dependencies'] = []
    value.pop('script', None)
    value.pop('editor', None)
    return value


def archive_bytes(manifest, *, extra=None, compression=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    kind = 'map' if manifest['format']['name'] == 'skieo-map' else 'mod'
    with zipfile.ZipFile(buffer, 'w', compression=compression) as archive:
        archive.writestr('custom-' + kind + '.json', json.dumps(manifest))
        archive.writestr('Terrain/heightmap.r16' if kind == 'map' else 'Scripts/main.lua', bytes(18) if kind == 'map' else b'return function(api) api:on("map.ready", function() end) end')
        if extra:
            for name, data in extra:
                archive.writestr(name, data)
    return buffer.getvalue()


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Repository(self.temporary.name, 'http://localhost:8091')
        self.repo.steam_profile = lambda identifier: {'name': 'Snow Rider', 'avatar_url': 'https://avatars.fastly.steamstatic.com/test_medium.jpg'}
        self.token = secrets.token_urlsafe(32)
        with self.repo.db() as db:
            db.execute('INSERT INTO users VALUES (?,?)', (STEAM_ID, int(time.time())))
            db.execute('INSERT INTO tokens VALUES (?,?,?,?,?)', (self.repo.hash(self.token), STEAM_ID, 'test', int(time.time()), int(time.time()) + 3600))

    def tearDown(self):
        self.temporary.cleanup()

    def request(self, path, method='GET', data=b'', token=None, headers=None):
        parsed = urlparse(path)
        env = {'REQUEST_METHOD': method, 'PATH_INFO': parsed.path, 'QUERY_STRING': parsed.query,
               'CONTENT_LENGTH': str(len(data)), 'wsgi.input': io.BytesIO(data), 'REMOTE_ADDR': '127.0.0.1', **(headers or {})}
        if token:
            env['HTTP_AUTHORIZATION'] = 'Bearer ' + token
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=headers)
        response['body'] = b''.join(self.repo(env, start))
        if not dict(response['headers']).get('Content-Type', '').startswith('application/zip'):
            response['json'] = json.loads(response['body']) if response['body'] else None
        return response

    def publish(self, manifest):
        kind = 'map' if manifest['format']['name'] == 'skieo-map' else 'mod'
        return self.request('/api/v1/packages?kind=' + kind, 'POST', archive_bytes(manifest), self.token)

    def test_publish_resolve_download_comments_and_bug_lifecycle(self):
        self.repo.refresh_profile(STEAM_ID)
        self.assertEqual(self.publish(mod_manifest())['status'], 201)
        manifest = map_manifest()
        manifest['dependencies'] = [{'id': 'test.snow-tools', 'version': '^1.0.0'}]
        self.assertEqual(self.publish(manifest)['status'], 201)
        result = self.request('/api/v1/resolve?id=test.alpine')['json']['packages']
        self.assertEqual([item['id'] for item in result], ['test.snow-tools', 'test.alpine'])
        download = self.request('/api/v1/downloads/test.alpine/1.0.0')
        self.assertEqual(hashlib.sha256(download['body']).hexdigest(), result[-1]['sha256'])
        comment = self.request('/api/v1/packages/test.alpine/comments', 'POST', json.dumps({'body': '<script>alert(1)</script>'}).encode(), self.token)
        self.assertEqual(comment['status'], 200)
        message = self.request('/api/v1/packages/test.alpine/comments')['json']['comments'][0]
        self.assertEqual(message['body'], '<script>alert(1)</script>')
        self.assertEqual(message['author_profile']['name'], 'Snow Rider')
        self.assertEqual(message['author_profile']['avatar_url'], 'https://avatars.fastly.steamstatic.com/test_medium.jpg')
        bug = self.request('/api/v1/packages/test.alpine/issues', 'POST', json.dumps({'title': 'Snow issue', 'body': 'Steps to reproduce', 'version': '1.0.0'}).encode(), self.token)
        self.assertEqual(bug['status'], 200)
        path = '/api/v1/packages/test.alpine/issues/' + str(bug['json']['id'])
        self.assertEqual(self.request(path, 'PATCH', b'{"status":"closed"}', self.token)['status'], 200)
        self.assertEqual(self.request('/api/v1/packages/test.alpine/issues')['json']['issues'][0]['status'], 'closed')
        self.assertEqual(self.request('/api/v1/packages/test.alpine/issues')['json']['issues'][0]['author_profile']['name'], 'Snow Rider')
        self.assertEqual(self.request(path, 'DELETE', token=self.token)['status'], 200)

    def test_immutable_versions_and_ownership(self):
        self.assertEqual(self.publish(mod_manifest())['status'], 201)
        self.assertEqual(self.publish(mod_manifest())['status'], 409)
        other_token = secrets.token_urlsafe(32)
        with self.repo.db() as db:
            db.execute('INSERT INTO users VALUES (?,?)', (OTHER_ID, int(time.time())))
            db.execute('INSERT INTO tokens VALUES (?,?,?,?,?)', (self.repo.hash(other_token), OTHER_ID, 'other', int(time.time()), int(time.time()) + 3600))
        result = self.request('/api/v1/packages?kind=mod', 'POST', archive_bytes(mod_manifest(version='1.0.1')), other_token)
        self.assertEqual(result['status'], 403)
        self.assertEqual(self.request('/api/v1/packages?kind=mod', 'POST', archive_bytes(mod_manifest()))['status'], 401)

    def test_missing_dependency_is_rejected_and_upload_released(self):
        manifest = map_manifest()
        manifest['dependencies'] = [{'id': 'missing.mod', 'version': '^1.0.0'}]
        self.assertEqual(self.publish(manifest)['status'], 400)
        with self.repo.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reservations').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM releases').fetchone()[0], 0)
        self.assertEqual(list((Path(self.temporary.name) / 'uploads').iterdir()), [])

    def test_store_and_deflate_packages(self):
        for compression in [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED]:
            path = Path(self.temporary.name) / 'test.zip'
            path.write_bytes(archive_bytes(mod_manifest(), compression=compression))
            kind, manifest, _ = inspect_package(path)
            self.assertEqual((kind, manifest['id']), ('mod', 'test.snow-tools'))

    def test_unsafe_zip_extra_files_and_corruption_rejected(self):
        for name in ['../escape.lua', 'Scripts/./bad.lua', 'NUL', 'x:evil', 'Scripts/main.lua', 'scripts/MAIN.lua', 'extra.txt']:
            path = Path(self.temporary.name) / 'bad.zip'
            path.write_bytes(archive_bytes(mod_manifest(), extra=[(name, b'bad')]))
            with self.assertRaises(ManifestError):
                inspect_package(path)
        value = bytearray(archive_bytes(mod_manifest(), compression=zipfile.ZIP_STORED))
        value[value.index(b'return function')] ^= 1
        path.write_bytes(value)
        with self.assertRaises(ManifestError):
            inspect_package(path)

    def test_unpacked_limit_and_symlink(self):
        path = Path(self.temporary.name) / 'test.zip'
        path.write_bytes(archive_bytes(mod_manifest()))
        with self.assertRaisesRegex(ManifestError, 'unpacked'):
            inspect_package(path, max_unpacked=10)
        info = zipfile.ZipInfo('linked.lua'); info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr(info, b'/etc/passwd')
        with self.assertRaisesRegex(ManifestError, 'links'):
            inspect_package(path)

    def test_reservations_enforce_total_and_owner_storage(self):
        with self.repo.db() as db:
            db.execute('INSERT INTO reservations VALUES (?,?,?,?)', ('other-upload', OTHER_ID, self.repo.archive_budget, int(time.time()) + 300))
        self.assertEqual(self.publish(mod_manifest())['status'], 507)
        with self.repo.db() as db:
            db.execute('DELETE FROM reservations')
        self.repo.owner_limit = 1
        self.assertEqual(self.publish(mod_manifest())['status'], 413)

    def session(self):
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.repo.db() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (self.repo.hash(session), STEAM_ID, csrf, int(time.time()) + 3600))
        return session, csrf

    def test_csrf_and_token_revocation(self):
        session, csrf = self.session()
        cookie = {'HTTP_COOKIE': 'custom_map_session=' + session}
        self.assertEqual(self.request('/api/v1/tokens', 'POST', b'{"label":"test"}', headers=cookie)['status'], 403)
        fields = {**cookie, 'HTTP_X_CSRF_TOKEN': csrf, 'HTTP_ORIGIN': self.repo.public_url}
        result = self.request('/api/v1/tokens', 'POST', b'{"label":"test"}', headers=fields)
        self.assertEqual(result['status'], 200)
        token = result['json']['token']
        self.assertEqual(self.request('/api/v1/me', token=token)['json']['user']['id'], STEAM_ID)
        self.assertEqual(self.request('/api/v1/me', token=token)['json']['user']['name'], 'Snow Rider')
        self.assertEqual(self.request('/api/v1/tokens/' + self.repo.hash(token), 'DELETE', headers=fields)['status'], 200)
        self.assertEqual(self.request('/api/v1/packages?kind=mod', 'POST', archive_bytes(mod_manifest()), token)['status'], 401)
        self.assertEqual(self.request('/api/v1/tokens', 'POST', b'{"label":"escalate"}', self.token)['status'], 403)

    def assertion(self):
        response = self.request('/auth/steam')
        state = parse_qs(urlparse(dict(response['headers'])['Location']).query)['openid.return_to'][0]
        state_value = parse_qs(urlparse(state).query)['state'][0]
        params = {'state': state_value, 'openid.ns': 'http://specs.openid.net/auth/2.0', 'openid.mode': 'id_res',
            'openid.op_endpoint': 'https://steamcommunity.com/openid/login', 'openid.return_to': state,
            'openid.claimed_id': 'https://steamcommunity.com/openid/id/' + STEAM_ID,
            'openid.identity': 'https://steamcommunity.com/openid/id/' + STEAM_ID,
            'openid.response_nonce': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) + secrets.token_hex(6),
            'openid.assoc_handle': 'test', 'openid.sig': 'signature',
            'openid.signed': 'op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle'}
        return params, {'HTTP_COOKIE': 'custom_map_login=' + state_value}

    def test_steam_login_verification_and_replay_prevention(self):
        self.repo.steam_check = lambda params: True
        params, cookie = self.assertion()
        self.assertEqual(self.request('/auth/steam/callback?' + urlencode(params), headers=cookie)['status'], 302)
        self.assertEqual(self.request('/auth/steam/callback?' + urlencode(params), headers=cookie)['status'], 400)
        params, cookie = self.assertion()
        params['openid.op_endpoint'] = 'https://evil.example'
        self.assertEqual(self.request('/auth/steam/callback?' + urlencode(params), headers=cookie)['status'], 400)
        params, cookie = self.assertion()
        self.repo.steam_check = lambda params: False
        self.assertEqual(self.request('/auth/steam/callback?' + urlencode(params), headers=cookie)['status'], 401)
        params, cookie = self.assertion()
        self.assertEqual(self.request('/auth/steam/callback?' + urlencode(params))['status'], 400)

    def test_forged_expired_and_unsigned_assertions(self):
        self.repo.steam_check = lambda params: True
        for field, value in [('openid.return_to', 'http://evil.example'), ('openid.response_nonce', '2000-01-01T00:00:00Ztest'), ('openid.signed', 'identity')]:
            params, cookie = self.assertion(); params[field] = value
            self.assertEqual(self.request('/auth/steam/callback?' + urlencode(params), headers=cookie)['status'], 400)

    def test_reproducible_mod_pack(self):
        root = Path(self.temporary.name)
        (root / 'Scripts').mkdir(); (root / 'Scripts/main.lua').write_text('return function(api) end')
        (root / 'custom-mod.json').write_text(json.dumps(mod_manifest()))
        pack_package(root / 'custom-mod.json', root / 'first.zip')
        pack_package(root / 'custom-mod.json', root / 'second.zip')
        self.assertEqual((root / 'first.zip').read_bytes(), (root / 'second.zip').read_bytes())

    def test_steam_profile_cache_and_failure_preserve_last_known_profile(self):
        with patch.object(self.repo, 'steam_profile', wraps=self.repo.steam_profile) as fetch:
            first = self.repo.refresh_profile(STEAM_ID)
            self.assertEqual(self.repo.refresh_profile(STEAM_ID), first)
            self.assertEqual(fetch.call_count, 1)
        with self.repo.db() as db:
            db.execute('UPDATE user_profiles SET expires=0')
        with patch.object(self.repo, 'steam_profile', side_effect=OSError('Steam unavailable')) as fetch:
            with self.assertLogs('custom-map', level='WARNING'):
                self.assertEqual(self.repo.refresh_profile(STEAM_ID), first)
            self.assertEqual(self.repo.refresh_profile(STEAM_ID), first)
            self.assertEqual(fetch.call_count, 1)

    def test_steam_profile_invalid_avatar_and_legacy_author_fallback(self):
        self.repo.steam_profile = lambda identifier: {'name': 'Invalid', 'avatar_url': 'https://evil.example/avatar.jpg'}
        with self.assertLogs('custom-map', level='WARNING'):
            result = self.repo.refresh_profile(STEAM_ID)
        self.assertEqual(result['name'], 'Steam · ' + STEAM_ID)
        self.assertIsNone(result['avatar_url'])
        self.publish(mod_manifest())
        self.request('/api/v1/packages/test.snow-tools/comments', 'POST', b'{"body":"Legacy comment"}', self.token)
        with self.repo.db() as db:
            db.execute('DROP TABLE user_profiles')
        self.repo = Repository(self.temporary.name, 'http://localhost:8091')
        comment = self.request('/api/v1/packages/test.snow-tools/comments')['json']['comments'][0]
        self.assertEqual(comment['author_profile']['name'], 'Steam · ' + STEAM_ID)
        self.assertEqual(comment['author_profile']['profile_url'], 'https://steamcommunity.com/profiles/' + STEAM_ID)

    def test_steam_profile_xml_identity_and_entity_rejection(self):
        valid = ('<profile><steamID64>' + STEAM_ID + '</steamID64><steamID><![CDATA[Snow & Ice]]></steamID><avatarMedium>https://avatars.fastly.steamstatic.com/test.jpg</avatarMedium></profile>').encode()
        def response(value):
            return patch('repository.server.app.urlopen', return_value=io.BytesIO(value))
        with response(valid):
            self.assertEqual(Repository._steam_profile(STEAM_ID)['name'], 'Snow & Ice')
        for value in [valid.replace(STEAM_ID.encode(), OTHER_ID.encode()), b'<!DOCTYPE profile [<!ENTITY x "bad">]>' + valid, bytes(131073)]:
            with response(value), self.assertRaises(ValueError):
                Repository._steam_profile(STEAM_ID)


class VersionTests(unittest.TestCase):
    def test_cli_resolves_shared_dependencies_together(self):
        root = mod_manifest('test.root', dependencies=[{'id': 'test.a'}, {'id': 'test.shared', 'version': '^1.0.0'}])
        releases = {
            'test.a': [self.release('test.a', '2.0.0', [{'id': 'test.shared', 'version': '^2.0.0'}]), self.release('test.a', '1.0.0', [{'id': 'test.shared', 'version': '^1.0.0'}])],
            'test.shared': [self.release('test.shared', '2.0.0'), self.release('test.shared', '1.0.0')],
        }
        result = cli.check_dependencies(root, 'mod', [release for versions in releases.values() for release in versions])
        self.assertEqual(result[-2]['version'], '1.0.0')

    def test_semver_constraints_and_prerelease_order(self):
        for version, range_, expected in [('1.2.0+build-tag', '*', True), ('1.2.0', '^1.0.0', True), ('2.0.0', '^1.0.0', False), ('0.2.4', '^0.2.0', True), ('0.3.0', '^0.2.0', False), ('1.2.9', '~1.2.0', True), ('1.3.0', '~1.2.0', False), ('1.2.0', '>=1.0.0 <2.0.0', True), ('1.2.0-beta', '*', False)]:
            self.assertEqual(custom_maps.version_matches(version, range_), expected)
        self.assertLess(custom_maps.semver_compare('1.0.0-beta.2', '1.0.0-beta.11'), 0)
        self.assertLess(custom_maps.semver_compare('1.0.0-beta.11', '1.0.0'), 0)

    def release(self, identifier, version, deps=None):
        return {'id': identifier, 'kind': 'mod', 'version': version, 'manifest': mod_manifest(identifier, version, deps)}

    def test_conflicts_backtrack_and_cycles_rejected(self):
        packages = [self.release('test.root', '1.0.0', [{'id': 'test.a', 'version': '*'}, {'id': 'test.shared', 'version': '^1.0.0'}]),
            self.release('test.a', '2.0.0', [{'id': 'test.shared', 'version': '^2.0.0'}]), self.release('test.a', '1.0.0', [{'id': 'test.shared', 'version': '^1.0.0'}]),
            self.release('test.shared', '2.0.0'), self.release('test.shared', '1.0.0')]
        result = resolve(packages, 'test.root')
        self.assertEqual([(item['id'], item['version']) for item in result], [('test.shared', '1.0.0'), ('test.a', '1.0.0'), ('test.root', '1.0.0')])
        cyclic = [self.release('test.a', '1.0.0', [{'id': 'test.b'}]), self.release('test.b', '1.0.0', [{'id': 'test.a'}])]
        with self.assertRaises(ManifestError): resolve(cyclic, 'test.a')


if __name__ == '__main__':
    unittest.main()
