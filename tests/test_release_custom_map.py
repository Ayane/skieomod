"""Release orchestration: checked artifacts, failure handling and server publication."""
from contextlib import redirect_stderr, redirect_stdout
import ast
import io
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from deployment import release_custom_map as release
from tools import skieo_loader as loader


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        for relative in ('tools/skieo_loader.py','tools/build_custom_map_release.py',
                         'deployment/publish_loader_updates.py','tests/check_skieomod_distribution.py'):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
        (self.root/'pyproject.toml').write_text('version = "1.17.0"\nother = "untouched"\n')
        (self.root/'tools/skieo_loader.py').write_text("VERSION = '1.17.0'\nMINIMUM_UPDATE_CLI = '1.17.0'\n")
        (self.root/'CHANGELOG.md').write_text('# Changes\n\n## [1.17.1]\n\n- Release fixture.\n')
        environment=patch.dict(release.os.environ,{release.discord.WEBHOOK_ENV:''});environment.start();self.addCleanup(environment.stop)
        patcher=patch.object(release,'ROOT',self.root);patcher.start();self.addCleanup(patcher.stop)
        self.folder=self.root/'build/release-1.17.1'
        self.feed={'release':'1.17.1'}

    def invoke(self,arguments):
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            return release.main(arguments)

    def test_versions_update_together_without_changing_minimum_cli(self):
        changes=release.version_changes('1.17.1');release.write_versions(changes)
        self.assertEqual((self.root/'pyproject.toml').read_text(),'version = "1.17.1"\nother = "untouched"\n')
        self.assertEqual((self.root/'tools/skieo_loader.py').read_text(),"VERSION = '1.17.1'\nMINIMUM_UPDATE_CLI = '1.17.0'\n")

    def test_invalid_or_older_version_never_changes_sources(self):
        for version in ('1.16.0','1.17.1/../other','1.2','latest','1.18.0-rc.1'):
            with self.subTest(version=version):
                self.assertEqual(self.invoke([version,'--prepare-only']),1)
                self.assertIn('1.17.0',(self.root/'pyproject.toml').read_text())

    def test_both_sources_are_validated_before_writing_and_concurrent_edits_are_preserved(self):
        (self.root/'tools/skieo_loader.py').write_text('broken')
        with self.assertRaises(ValueError):release.version_changes('1.17.1')
        self.assertIn('1.17.0',(self.root/'pyproject.toml').read_text())
        (self.root/'tools/skieo_loader.py').write_text("VERSION = '1.17.0'\n")
        changes=release.version_changes('1.17.1')
        (self.root/'tools/skieo_loader.py').write_text('concurrent edit')
        with self.assertRaises(ValueError):release.write_versions(changes)
        self.assertIn('1.17.0',(self.root/'pyproject.toml').read_text())
        self.assertEqual((self.root/'tools/skieo_loader.py').read_text(),'concurrent edit')

    def test_prepare_only_checks_packages_and_never_contacts_server(self):
        with patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
             patch.object(release,'preflight') as ssh,patch.object(release,'run') as commands, \
             patch.object(release,'verify_publication') as verify:
            self.assertEqual(self.invoke(['1.17.1','--prepare-only','--no-build-isolation']),0)
        ssh.assert_not_called();verify.assert_not_called()
        self.assertEqual(commands.call_count,2)
        build=commands.call_args_list[0].args[0]
        self.assertIn('--no-build-isolation',build);self.assertIn(self.folder,build)
        self.assertIn('--loader-archive',commands.call_args_list[1].args[0])

    def test_normal_release_publishes_only_after_checks_and_verifies_https(self):
        calls=[]
        with patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
             patch.object(release,'preflight',side_effect=lambda args:calls.append('ssh')), \
             patch.object(release,'run',side_effect=lambda args,title:calls.append(Path(args[1]).name)), \
             patch.object(release,'verify_publication',side_effect=lambda url,feed:calls.append('https')):
            self.assertEqual(self.invoke(['1.17.1']),0)
        self.assertEqual(calls,['ssh','build_custom_map_release.py','check_skieomod_distribution.py','publish_loader_updates.py','https'])

    def test_failed_checks_never_publish(self):
        def run(arguments,title):
            if Path(arguments[1]).name=='check_skieomod_distribution.py':
                raise subprocess.CalledProcessError(1,arguments)
        with patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
             patch.object(release,'preflight'),patch.object(release,'run',side_effect=run) as commands, \
             patch.object(release,'verify_publication') as verify:
            self.assertEqual(self.invoke(['1.17.1']),1)
        self.assertEqual(commands.call_count,2);verify.assert_not_called()

    def test_missing_notes_stop_before_changing_versions_or_contacting_server(self):
        (self.root/'CHANGELOG.md').write_text('## [Unreleased]\n\n- Pending.\n')
        with patch.object(release,'preflight') as ssh,patch.object(release,'run') as commands:
            self.assertEqual(self.invoke(['1.17.1']),1)
        ssh.assert_not_called();commands.assert_not_called()
        self.assertIn('1.17.0',(self.root/'pyproject.toml').read_text())

    def test_discord_runs_only_after_publication_and_https_verification(self):
        calls=[]
        with patch.dict(release.os.environ,{release.discord.WEBHOOK_ENV:'configured'}), \
             patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
             patch.object(release,'preflight'),patch.object(release,'run',side_effect=lambda args,title:calls.append(Path(args[1]).name)), \
             patch.object(release,'verify_publication',side_effect=lambda *args:calls.append('https')), \
             patch.object(release.discord,'announce',side_effect=lambda *args:(calls.append('discord') or {'message_id':'123'})):
            self.assertEqual(self.invoke(['1.17.1']),0)
        self.assertEqual(calls[-3:],['publish_loader_updates.py','https','discord'])

    def test_prepare_and_skip_modes_never_announce_even_when_configured(self):
        for mode in ('--prepare-only','--skip-discord'):
            with patch.dict(release.os.environ,{release.discord.WEBHOOK_ENV:'configured'}), \
                 patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
                 patch.object(release,'preflight'),patch.object(release,'run'),patch.object(release,'verify_publication'), \
                 patch.object(release.discord,'announce') as announce:
                self.assertEqual(self.invoke(['1.17.1',mode]),0)
            announce.assert_not_called()

    def test_failed_https_check_never_announces(self):
        with patch.dict(release.os.environ,{release.discord.WEBHOOK_ENV:'configured'}), \
             patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
             patch.object(release,'preflight'),patch.object(release,'run'), \
             patch.object(release,'verify_publication',side_effect=RuntimeError('Verification failed')), \
             patch.object(release.discord,'announce') as announce:
            self.assertEqual(self.invoke(['1.17.1']),1)
        announce.assert_not_called()

    def test_discord_failure_reports_that_release_is_already_published(self):
        with patch.dict(release.os.environ,{release.discord.WEBHOOK_ENV:'configured'}), \
             patch.object(release,'read_ue4ss_archive'),patch.object(release,'check_artifacts',return_value=self.feed), \
             patch.object(release,'preflight'),patch.object(release,'run'),patch.object(release,'verify_publication'), \
             patch.object(release.discord,'announce',side_effect=release.discord.NotificationError('Unavailable')), \
             redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(release.main(['1.17.1']),1)
        self.assertIn('already published and verified',errors.getvalue())

    def test_ssh_failure_precedes_source_changes_and_build(self):
        with patch.object(release,'read_ue4ss_archive'), \
             patch.object(release,'preflight',side_effect=subprocess.CalledProcessError(255,['ssh'])), \
             patch.object(release,'run') as commands:
            self.assertEqual(self.invoke(['1.17.1']),1)
        commands.assert_not_called();self.assertIn('1.17.0',(self.root/'pyproject.toml').read_text())

    def test_publish_only_rechecks_existing_packages_and_preserves_sources(self):
        with patch.object(release,'check_artifacts',return_value=self.feed),patch.object(release,'preflight'), \
             patch.object(release,'run') as commands,patch.object(release,'verify_publication') as verify:
            self.assertEqual(self.invoke(['1.17.1','--publish-only','--ssh-config','/tmp/config','--known-hosts','/tmp/hosts']),0)
        self.assertEqual(commands.call_count,2)
        self.assertEqual(Path(commands.call_args_list[0].args[0][1]).name,'check_skieomod_distribution.py')
        publish=commands.call_args_list[1].args[0]
        self.assertIn('root@skieomod.emillon.fr',publish);self.assertIn('--ssh-config',publish);self.assertIn('--known-hosts',publish)
        verify.assert_called_once_with(release.PUBLIC_FEED,self.feed)
        self.assertIn('1.17.0',(self.root/'pyproject.toml').read_text())

    def test_publish_only_uses_frozen_notes_even_when_source_changelog_changes(self):
        self.folder.mkdir(parents=True)
        (self.folder/'Changelog-1.17.1.md').write_text('## [1.17.1]\n\n- Frozen notes.\n')
        (self.root/'CHANGELOG.md').write_text('## [Unreleased]\n\n- Later edits.\n')
        with patch.object(release,'check_artifacts',return_value=self.feed),patch.object(release,'preflight'), \
             patch.object(release,'run'),patch.object(release,'verify_publication'):
            self.assertEqual(self.invoke(['1.17.1','--publish-only']),0)
        preview=json.loads((self.folder/'discord-announcement-preview.json').read_text())
        self.assertIn('Frozen notes.',preview['content']);self.assertNotIn('Later edits.',preview['content'])

    def artifacts(self):
        self.folder.mkdir(parents=True)
        files={name:b'release fixture' for name in loader.REQUIRED}
        record=loader.manifest(files,'1.17.1')
        archive=self.folder/'CustomMap-Mod-1.17.1.zip'
        with zipfile.ZipFile(archive,'w') as output:
            output.writestr(loader.NAME+'/'+loader.RECORD,json.dumps(record))
            for name,data in files.items():output.writestr(loader.NAME+'/'+name,data)
        feed=loader.update_feed(archive,record)
        (self.folder/'loader-latest.json').write_text(json.dumps(feed))
        for name in ('skieo_custom_map-1.17.1-py3-none-any.whl','CustomMap-Tools.zip','Getting-Started-1.17.1.md'):
            (self.folder/name).write_bytes(b'fixture')
        return feed

    def test_artifacts_must_match_version_archive_hash_and_required_files(self):
        feed=self.artifacts()
        with patch.object(release,'read_ue4ss_archive'):
            self.assertEqual(release.check_artifacts(self.folder,'1.17.1'),feed)
            with self.assertRaisesRegex(ValueError,'requested version'):release.check_artifacts(self.folder,'1.17.2')
            altered=dict(feed,sha256='0'*64)
            (self.folder/'loader-latest.json').write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'differs'):release.check_artifacts(self.folder,'1.17.1')
            (self.folder/'loader-latest.json').write_text(json.dumps(feed))
            (self.folder/'CustomMap-Tools.zip').unlink()
            with self.assertRaisesRegex(ValueError,'Missing release artifact'):release.check_artifacts(self.folder,'1.17.1')

    def test_bad_artifacts_prevent_publish_only_from_contacting_server(self):
        feed=self.artifacts();feed['sha256']='0'*64
        (self.folder/'loader-latest.json').write_text(json.dumps(feed))
        with patch.object(release,'preflight') as ssh,patch.object(release,'run') as commands:
            self.assertEqual(self.invoke(['1.17.1','--publish-only']),1)
        ssh.assert_not_called();commands.assert_not_called()

    def test_preflight_refuses_downgrading_server_and_keeps_host_verification(self):
        args=release.parser().parse_args(['1.17.1','--ssh-config','/tmp/config','--known-hosts','/tmp/hosts'])
        response=subprocess.CompletedProcess([],0,stdout='{"release":"1.18.0"}')
        with patch.object(release.subprocess,'run',return_value=response) as run,redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):release.preflight(args)
        command=run.call_args.args[0]
        self.assertIn('root@skieomod.emillon.fr',command)
        self.assertIn('UserKnownHostsFile=/tmp/hosts',command)
        self.assertNotIn('StrictHostKeyChecking=no',command)

    def test_public_feed_verification_retries_stale_responses(self):
        responses=[io.BytesIO(b'{"release":"1.17.0"}'),io.BytesIO(json.dumps(self.feed).encode())]
        with patch.object(release,'urlopen',side_effect=responses) as fetch,patch.object(release.time,'sleep'),redirect_stdout(io.StringIO()):
            release.verify_publication(release.PUBLIC_FEED,self.feed)
        self.assertEqual(fetch.call_count,2)

    def test_public_feed_verification_failure_reports_publication_already_completed(self):
        with patch.object(release,'urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(b'{}')), \
             patch.object(release.time,'sleep'),redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError,'Publication completed'):
                release.verify_publication(release.PUBLIC_FEED,self.feed)


class ReleasePackagingTests(unittest.TestCase):
    def test_all_declared_modules_reach_the_wheel_build_and_tools_archive(self):
        root = Path(__file__).resolve().parents[1]
        project = (root / 'pyproject.toml').read_text(encoding='utf-8')
        modules = ast.literal_eval(re.search(r'(?ms)^py-modules\s*=\s*(\[.*?\])', project)[1])
        version = re.search(r'(?m)^version = "([^"]+)"$', project)[1]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'release'
            ue4ss = Path(temporary) / release.UE4SS_ARCHIVE
            ue4ss.write_bytes(b'UE4SS fixture')

            def build_wheel(arguments, *, check):
                self.assertTrue(check)
                self.assertIn('wheel', arguments)
                stage = Path(arguments[-1])
                for module in modules:
                    with self.subTest(stage=module):
                        path = stage / 'tools' / (module + '.py')
                        self.assertTrue(path.is_file(), 'Missing staged module: ' + module)
                        self.assertEqual(path.read_bytes(), (root / 'tools' / path.name).read_bytes())
                (output / ('skieo_custom_map-' + version + '-py3-none-any.whl')).write_bytes(b'wheel fixture')

            arguments = [str(root / 'tools/build_custom_map_release.py'),
                         '--output-dir', str(output), '--ue4ss-archive', str(ue4ss),
                         '--tools-only', '--no-build-isolation']
            with patch.object(sys, 'argv', arguments), patch.object(sys, 'path', sys.path.copy()), \
                 patch('tools.skieo_install.read_ue4ss_archive', return_value=ue4ss.read_bytes()), \
                 patch.object(subprocess, 'run', side_effect=build_wheel) as build, \
                 redirect_stdout(io.StringIO()):
                runpy.run_path(arguments[0], run_name='__main__')
            build.assert_called_once()
            with zipfile.ZipFile(output / 'CustomMap-Tools.zip') as archive:
                for module in modules:
                    with self.subTest(archive=module):
                        name = 'tools/' + module + '.py'
                        self.assertEqual(archive.read(name), (root / name).read_bytes())


if __name__=='__main__':unittest.main()
