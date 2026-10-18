"""Exercise the actual SSH receiver locally, including large tools archives."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from deployment import publish_loader_updates as publisher


class PublicationTests(unittest.TestCase):
    def setUp(self):
        workspace=tempfile.TemporaryDirectory();self.addCleanup(workspace.cleanup)
        self.root=Path(workspace.name);self.source=self.root/'source';self.source.mkdir()
        self.destination=self.root/'downloads';self.destination.mkdir()
        self.version='1.17.1';self.tar=self.root/'upload.tar'
        self.previous=b'{"release":"1.17.0"}\n'
        (self.destination/'loader-latest.json').write_bytes(self.previous)

    def fixture(self,tools_size=10):
        mod=self.source/('CustomMap-Mod-'+self.version+'.zip');mod.write_bytes(b'mod fixture')
        ue4ss=self.source/publisher.UE4SS_ARCHIVE;ue4ss.write_bytes(b'UE4SS fixture')
        self.feed={'release':self.version,'url':'https://skieomod.emillon.fr/downloads/'+mod.name,
                   'sha256':hashlib.sha256(mod.read_bytes()).hexdigest(),'size':mod.stat().st_size}
        (self.source/'loader-latest.json').write_text(json.dumps(self.feed))
        (self.source/'skieo_custom_map-1.17.1-py3-none-any.whl').write_bytes(b'wheel fixture')
        (self.source/'Getting-Started-1.17.1.md').write_bytes(b'guide fixture')
        with (self.source/'CustomMap-Tools.zip').open('wb') as tools:tools.truncate(tools_size)
        record={'name':ue4ss.name,'sha256':hashlib.sha256(ue4ss.read_bytes()).hexdigest(),'size':ue4ss.stat().st_size}
        (self.source/'ue4ss-release.json').write_text(json.dumps(record))
        files=publisher.publication_files(self.source,self.version)
        publisher.validate_publication_files(files)
        with tarfile.open(self.tar,'w') as archive:
            for path,name in [*files,(ue4ss,ue4ss.name),(self.source/'ue4ss-release.json','ue4ss-release.json')]:
                archive.add(path,arcname=name,recursive=False)

    def receive(self):
        with self.tar.open('rb') as stream:
            return subprocess.run([sys.executable,'-c',publisher.REMOTE,str(self.destination)],stdin=stream,
                                  capture_output=True,text=True)

    def declared_member(self,name,size):
        member=tarfile.TarInfo(name);member.size=size
        self.tar.write_bytes(member.tobuf())

    def assert_unpublished(self):
        self.assertEqual((self.destination/'loader-latest.json').read_bytes(),self.previous)
        self.assertEqual(list(self.destination.iterdir()),[self.destination/'loader-latest.json'])

    def test_tools_above_64_mib_are_published_with_aliases_feed_history_and_index(self):
        size=publisher.MAX_MEMBER_BYTES+1;self.fixture(size)
        result=self.receive();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.destination/'CustomMap-Tools-1.17.1.zip').stat().st_size,size)
        for alias,target in [('CustomMap-Tools.zip','CustomMap-Tools-1.17.1.zip'),
                             ('CustomMap-Mod.zip','CustomMap-Mod-1.17.1.zip'),
                             ('getting-started.md','Getting-Started-1.17.1.md')]:
            self.assertTrue((self.destination/alias).is_symlink())
            self.assertEqual((self.destination/alias).resolve(),self.destination/target)
        self.assertEqual(json.loads((self.destination/'loader-latest.json').read_text()),self.feed)
        self.assertEqual((self.destination/'loader-latest.previous.json').read_bytes(),self.previous)
        self.assertIn('skieo_custom_map-1.17.1-py3-none-any.whl',(self.destination/'pypi/skieo-custom-map/index.html').read_text())
        self.assertFalse(list(self.destination.glob('.skieomod-upload-*')))

    def test_tools_above_128_mib_are_rejected_locally_and_remotely_with_size_details(self):
        size=publisher.MAX_TOOLS_BYTES+1;name='CustomMap-Tools-1.17.1.zip'
        path=self.source/'CustomMap-Tools.zip'
        with path.open('wb') as stream:stream.truncate(size)
        with self.assertRaisesRegex(ValueError,name):publisher.validate_publication_files([(path,name)])
        self.declared_member(name,size)
        result=self.receive();self.assertNotEqual(result.returncode,0)
        self.assertIn(name,result.stderr);self.assertIn(str(size),result.stderr);self.assertIn(str(publisher.MAX_TOOLS_BYTES),result.stderr)
        self.assert_unpublished()

    def test_loader_keeps_64_mib_limit_and_rejection_does_not_publish(self):
        name='CustomMap-Mod-1.17.1.zip';size=publisher.MAX_MEMBER_BYTES+1
        path=self.source/name
        with path.open('wb') as stream:stream.truncate(size)
        with self.assertRaisesRegex(ValueError,name):publisher.validate_publication_files([(path,name)])
        self.declared_member(name,size)
        result=self.receive();self.assertNotEqual(result.returncode,0)
        self.assertIn(name,result.stderr);self.assertIn(str(publisher.MAX_MEMBER_BYTES),result.stderr)
        self.assert_unpublished()

    def test_unsafe_archive_member_remains_rejected(self):
        self.declared_member('../escape.zip',0)
        result=self.receive();self.assertNotEqual(result.returncode,0)
        self.assertIn('Invalid publication member',result.stderr);self.assertFalse((self.root/'escape.zip').exists())
        self.assert_unpublished()

    def test_changelog_is_published_with_a_stable_alias_and_is_immutable(self):
        changelog=self.source/'Changelog-1.17.1.md';changelog.write_bytes(b'## [1.17.1]\n\n- A release.\n')
        self.fixture()
        result=self.receive();self.assertEqual(result.returncode,0,result.stderr)
        published=self.destination/changelog.name
        self.assertEqual(published.read_bytes(),changelog.read_bytes())
        self.assertEqual((self.destination/'changelog.md').resolve(),published)
        changelog.write_bytes(b'changed history')
        self.fixture();result=self.receive();self.assertNotEqual(result.returncode,0)
        self.assertIn('Versioned artifact already exists with different bytes',result.stderr)
        self.assertEqual(published.read_bytes(),b'## [1.17.1]\n\n- A release.\n')

    def test_changed_versioned_artifact_is_never_overwritten(self):
        self.fixture()
        target=self.destination/'CustomMap-Tools-1.17.1.zip';target.write_bytes(b'existing release')
        result=self.receive();self.assertNotEqual(result.returncode,0)
        self.assertIn('Versioned artifact already exists with different bytes',result.stderr)
        self.assertEqual(target.read_bytes(),b'existing release')
        self.assertEqual((self.destination/'loader-latest.json').read_bytes(),self.previous)
        self.assertFalse((self.destination/'CustomMap-Mod.zip').exists())


if __name__=='__main__':unittest.main()
