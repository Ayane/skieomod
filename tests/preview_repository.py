"""Temporary local browser fixture, never deployed to the public service."""
import io
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
from wsgiref.simple_server import make_server
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repository.server.app import Repository
from test_repository import archive_bytes, mod_manifest, map_manifest, STEAM_ID

ROOT = Path(__file__).resolve().parents[1]
# Exercise the exact production CSP, including on generated Angular HTML.
CONTENT_SECURITY_POLICY = re.search(
    r'add_header Content-Security-Policy "([^"]+)"',
    (ROOT / 'deployment/nginx.conf').read_text(),
).group(1)
temporary = tempfile.TemporaryDirectory(prefix='custom-map-browser-')
repo = Repository(temporary.name, 'http://127.0.0.1:8091')
repo.steam_profile = lambda identifier: {'name': 'Snow Rider', 'avatar_url': 'https://avatars.fastly.steamstatic.com/test_medium.jpg'}
with repo.db() as db:
    db.execute('INSERT INTO users VALUES (?,?)', (STEAM_ID, int(time.time())))
    db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (repo.hash('browser-test-session'), STEAM_ID, 'browser-test-csrf', int(time.time()) + 3600))
repo.refresh_profile(STEAM_ID)
for manifest in [mod_manifest(), map_manifest()]:
    if manifest['format']['name'] == 'skieo-map':
        manifest['dependencies'] = [{'id': 'test.snow-tools', 'version': '^1.0.0'}]
    data = archive_bytes(manifest)
    kind = 'map' if manifest['format']['name'] == 'skieo-map' else 'mod'
    repo.publish({'CONTENT_LENGTH': str(len(data)), 'wsgi.input': io.BytesIO(data)}, kind, owner=STEAM_ID)
(Path(temporary.name) / 'upload.zip').write_bytes(archive_bytes(mod_manifest('test.browser-upload')))
print(json.dumps({'upload': str(Path(temporary.name) / 'upload.zip')}), flush=True)

def application(env, start):
    path = env['PATH_INFO']
    if path.startswith(('/api/', '/auth/')):
        return repo(env, start)
    static = ROOT / ('docs' if path.startswith('/docs/') else 'repository/web/dist/browser')
    relative = path.removeprefix('/docs/') if path.startswith('/docs/') else path.lstrip('/')
    target = (static / relative).resolve()
    if target.is_dir():
        target = target / 'index.html'
    if not target.is_relative_to(static.resolve()) or not target.is_file():
        target = static / 'index.html'
    import mimetypes
    start('200 OK', [
        ('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream'),
        ('Content-Security-Policy', CONTENT_SECURITY_POLICY),
    ])
    return [target.read_bytes()]

with make_server('127.0.0.1', 8091, application) as server:
    server.serve_forever()
