"""Exercise release selection, untrusted downloads and deployment rollback."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from deployment import github_autopublish as auto
from deployment import github_release as github
from deployment import publish_loader_updates as publisher
from tools import skieo_install


class AutopublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.old = self.root / 'releases/old'
        self.old.mkdir(parents=True)
        (self.old / 'downloads').mkdir()
        (self.old / 'downloads/loader-latest.json').write_text('{"release":"1.23.0"}')
        self.current = self.root / 'current'
        self.current.symlink_to(self.old)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.release = {'id': 1, 'tag_name': 'v1.24.2', 'draft': False, 'prerelease': False,
                        'assets': [{'id': 2, 'name': 'skieomod-server-1.24.2.tar.gz', 'state': 'uploaded',
                                    'size': 10, 'digest': 'sha256:' + 'a' * 64,
                                    'browser_download_url': 'https://github.com/Ayane/skieomod/releases/download/v1.24.2/skieomod-server-1.24.2.tar.gz'}]}

    def test_stable_release_requires_exact_tag_asset_digest_and_origin(self):
        self.assertEqual(auto.select_asset(self.release)[0], '1.24.2')
        for field, value in [('draft', True), ('prerelease', True), ('tag_name', '1.24.2'),
                             ('tag_name', 'v1.24.2-rc.1')]:
            with self.subTest(field=field), patch.dict(self.release, {field: value}):
                with self.assertRaises(ValueError):
                    auto.select_asset(self.release)
        for field, value in [('digest', None), ('size', auto.MAX_BUNDLE + 1),
                             ('browser_download_url', 'https://example.com/bundle'), ('state', 'new')]:
            with self.subTest(field=field), patch.dict(self.release['assets'][0], {field: value}):
                with self.assertRaises(ValueError):
                    auto.select_asset(self.release)
        self.release['assets'] *= 2
        with self.assertRaises(ValueError):
            auto.select_asset(self.release)

    def test_download_checks_actual_size_and_sha256(self):
        data = b'release archive'
        asset = {**self.release['assets'][0], 'size': len(data),
                 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
        with patch.object(auto, 'urlopen', return_value=io.BytesIO(data)):
            auto.download(asset, self.root / 'good.tar.gz')
        for key, value in [('size', len(data) - 1), ('size', len(data) + 1), ('digest', 'sha256:' + '0' * 64)]:
            with self.subTest(key=key, value=value), patch.dict(asset, {key: value}), \
                    patch.object(auto, 'urlopen', return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError):
                    auto.download(asset, self.root / ('bad-' + str(value)))

    def bundle(self, extra=None, version='1.24.2'):
        path = self.root / 'bundle.tar.gz'
        names = ['repository/web/dist/browser/index.html', 'repository/server/app.py',
                 'repository/server/requirements.txt', 'deployment/custom-map.service',
                 'deployment/nginx.conf', 'deployment/publish_loader_updates.py']
        with tarfile.open(path, 'w:gz') as archive:
            for name in ['release.json', *names]:
                data = json.dumps({'format': 'skieomod-server-v1', 'version': version, 'commit': 'a' * 40}).encode() if name == 'release.json' else b'fixture'
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra, io.BytesIO(b'x' * extra.size))
        return path

    def test_valid_bundle_is_extracted_with_readable_permissions(self):
        stage = self.root / 'stage'
        metadata = auto.extract_bundle(self.bundle(), stage, '1.24.2')
        self.assertEqual(metadata['commit'], 'a' * 40)
        self.assertEqual((stage / 'repository/server/app.py').stat().st_mode & 0o777, 0o644)

    def test_traversal_links_duplicates_and_wrong_version_are_rejected(self):
        for index, name in enumerate(['../escape', '/tmp/escape', 'deployment/../escape', 'release.json']):
            member = tarfile.TarInfo(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                auto.extract_bundle(self.bundle(member), self.root / str(index), '1.24.2')
        link = tarfile.TarInfo('deployment/link')
        link.type = tarfile.SYMTYPE
        link.linkname = '/etc'
        with self.assertRaises(ValueError):
            auto.extract_bundle(self.bundle(link), self.root / 'link', '1.24.2')
        with self.assertRaises(ValueError):
            auto.extract_bundle(self.bundle(version='1.24.1'), self.root / 'wrong', '1.24.2')

    def test_extraction_budget_is_enforced(self):
        with patch.object(auto, 'MAX_EXPANDED', 1), self.assertRaises(ValueError):
            auto.extract_bundle(self.bundle(), self.root / 'big', '1.24.2')

    def test_current_or_older_release_never_downloads_or_restarts(self):
        for version in ['1.23.0', '1.9.9']:
            self.release['tag_name'] = 'v' + version
            with patch.object(auto, 'read_json', return_value=self.release), \
                    patch.object(auto, 'select_asset', return_value=(version, {})), \
                    patch.object(auto, 'download') as download, patch.object(auto, 'run') as run:
                auto.publish(self.root, self.state)
            download.assert_not_called()
            run.assert_not_called()

    def test_check_mode_and_failed_download_preserve_current_and_success_receipt(self):
        with patch.object(auto, 'read_json', return_value=self.release), patch.object(auto, 'download') as download:
            auto.publish(self.root, self.state, check_only=True)
        download.assert_not_called()
        with patch.object(auto, 'read_json', return_value=self.release), \
                patch.object(auto, 'download', side_effect=ValueError('bad checksum')), self.assertRaises(ValueError):
            auto.publish(self.root, self.state)
        self.assertEqual(self.current.resolve(), self.old)
        self.assertFalse((self.state / 'last-success.json').exists())
        self.assertEqual(list((self.root / 'releases').iterdir()), [self.old])

    def test_full_publication_keeps_old_downloads_and_records_success_only_after_activation(self):
        archive = self.bundle()
        retained = self.old / 'downloads/old-mod.zip'
        retained.write_bytes(b'immutable release')

        def download(asset, target):
            target.write_bytes(archive.read_bytes())

        def prepare(*command):
            if '--local-directory' in command:
                downloads = Path(command[-1])
                temporary = downloads / 'new-feed'
                temporary.write_text('{"release":"1.24.2"}')
                temporary.replace(downloads / 'loader-latest.json')

        with patch.object(auto, 'read_json', return_value=self.release), patch.object(auto, 'download', side_effect=download), \
                patch.object(auto, 'run', side_effect=prepare), \
                patch.object(auto, 'activate', side_effect=lambda stage, current: auto.switch_link(current, stage)):
            auto.publish(self.root, self.state)
        self.assertEqual(json.loads((self.current / 'downloads/loader-latest.json').read_text())['release'], '1.24.2')
        self.assertEqual(json.loads((self.old / 'downloads/loader-latest.json').read_text())['release'], '1.23.0')
        self.assertEqual((self.current / 'downloads/old-mod.zip').stat().st_ino, retained.stat().st_ino)
        self.assertEqual(json.loads((self.state / 'last-success.json').read_text())['commit'], 'a' * 40)

    def activation(self, failure):
        stage = self.root / 'releases/new'
        stage.mkdir()
        auto.extract_bundle(self.bundle(), stage, '1.24.2')
        service, nginx = self.root / 'service', self.root / 'nginx'
        service.write_bytes(b'old service')
        nginx.write_bytes(b'old nginx')
        calls = []

        def run(*command):
            calls.append(command)
            if failure == 'restart' and command == ('systemctl', 'restart', 'custom-map.service') and calls.count(command) == 1:
                raise subprocess.CalledProcessError(1, command)

        with patch.object(auto, 'run', side_effect=run), \
                patch.object(auto, 'verify_publication', side_effect=ValueError('unhealthy') if failure == 'health' else None):
            if failure:
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    auto.activate(stage, self.current, service=service, nginx=nginx)
            else:
                auto.activate(stage, self.current, service=service, nginx=nginx)
        if failure:
            self.assertEqual(self.current.resolve(), self.old)
            self.assertEqual(service.read_bytes(), b'old service')
            self.assertEqual(nginx.read_bytes(), b'old nginx')
        else:
            self.assertEqual(self.current.resolve(), stage)
            self.assertEqual(service.read_bytes(), b'fixture')

    def test_successful_activation_switches_code_service_and_site(self):
        self.activation(None)

    def test_failed_health_check_rolls_back_code_service_and_site(self):
        self.activation('health')

    def test_failed_service_restart_also_rolls_back(self):
        self.activation('restart')

    def test_local_publication_uses_the_same_validated_payload_and_receiver_as_ssh(self):
        class Args:
            directory = Path('/release')
            local_directory = Path('/downloads')
        with patch.object(publisher, 'publication_payload', return_value=b'checked payload'), \
                patch.object(publisher.subprocess, 'run') as run:
            publisher.publish(Args())
        self.assertEqual(run.call_args.args[0][1:], ['-c', publisher.REMOTE, '/downloads'])
        self.assertEqual(run.call_args.kwargs['input'], b'checked payload')


class GithubReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'tools').mkdir()
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "1.24.2"\n')
        (self.root / 'tools/skieo_loader.py').write_text("VERSION = '1.24.2'\n")
        (self.root / 'CHANGELOG.md').write_text('## [1.24.2]\n\n- Release.\n')
        patcher = patch.object(github, 'ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_version_selection_ignores_drafts_and_prereleases_and_compares_numerically(self):
        for existing, expected in [('1.9.9', True), ('1.24.2', False), ('1.25.0', False)]:
            releases = [[{'tag_name': 'v' + existing, 'draft': False, 'prerelease': False},
                         {'tag_name': 'v9.0.0', 'draft': True, 'prerelease': False},
                         {'tag_name': 'v9.0.0-rc.1', 'draft': False, 'prerelease': True}]]
            output = self.root / 'output'
            output.unlink(missing_ok=True)
            with patch.object(github, 'gh', return_value=json.dumps(releases)), \
                    patch.dict(github.os.environ, {'GITHUB_OUTPUT': str(output)}):
                github.select()
            self.assertIn('publish=' + str(expected).lower(), output.read_text())

    def test_inconsistent_versions_are_rejected_before_publication(self):
        (self.root / 'tools/skieo_loader.py').write_text("VERSION = '1.24.1'\n")
        with self.assertRaises(ValueError):
            github.source_version()

    def test_new_pinned_dependency_can_bootstrap_an_empty_mirror(self):
        data = b'pinned UE4SS build'
        with patch.object(github, 'urlopen', side_effect=[
                HTTPError(github.UE4SS_URL, 404, 'not mirrored yet', {}, None), io.BytesIO(data)]) as fetch, \
                patch.object(skieo_install, 'UE4SS_SHA256', hashlib.sha256(data).hexdigest()):
            github.dependency()
        self.assertEqual(fetch.call_args_list[0].args[0], github.UE4SS_URL)
        self.assertEqual(fetch.call_args_list[1].args[0], github.UE4SS_UPSTREAM_URL)
        self.assertEqual((self.root / 'build/custom-map-downloads' / github.UE4SS_ARCHIVE).read_bytes(), data)

    def test_dependency_fallback_still_rejects_wrong_bytes_and_server_errors(self):
        with patch.object(github, 'urlopen', side_effect=[
                HTTPError(github.UE4SS_URL, 410, 'gone', {}, None), io.BytesIO(b'wrong build')]), \
                self.assertRaises(skieo_install.ManifestError):
            github.dependency()
        with patch.object(github, 'urlopen', side_effect=HTTPError(github.UE4SS_URL, 500, 'server failure', {}, None)) as fetch, \
                self.assertRaises(HTTPError):
            github.dependency()
        self.assertEqual(fetch.call_count, 1)

    def test_already_published_version_never_uploads_or_replaces_assets(self):
        (self.root / 'build/release-1.24.2').mkdir(parents=True)
        with patch.object(github, 'gh', return_value='[[{"tag_name":"v1.24.2","draft":false}]]') as gh, \
                patch.object(github.subprocess, 'check_output', return_value='a' * 40), self.assertRaises(ValueError):
            github.publish()
        self.assertEqual(gh.call_count, 1)


if __name__ == '__main__':
    unittest.main()
