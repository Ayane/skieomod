#!/usr/bin/env python3
"""Run package, repository, editor and Lua regression checks."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
from make_zip_fixtures import create

ROOT = Path(__file__).resolve().parents[1]
lua = os.environ.get('CUSTOM_MAP_LUA') or shutil.which('lua5.4') or shutil.which('lua')
if not lua or 'Lua 5.4' not in subprocess.check_output([lua, '-v'], text=True, stderr=subprocess.STDOUT):
    raise SystemExit('Install Lua 5.4 or set CUSTOM_MAP_LUA to its executable.')
for pattern in ['test_custom_maps.py', 'test_repository.py', 'test_skieomod.py', 'test_skieomod_cli.py', 'test_skieomod_uninstall.py', 'test_skieomod_projects.py', 'test_workshop.py', 'test_mapmod_downloads.py', 'test_web_publication.py']:
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', pattern], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_supported_game_builds', 'tests.test_skieo_http', 'tests.test_installers', 'tests.test_surface_lift_tutorial'], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_release_custom_map', 'tests.test_publish_loader_updates', 'tests.test_skieomod_publish', 'tests.test_github_autopublish', 'tests.test_compatibility_process', 'tests.test_surface_lift_grade', 'tests.test_surface_lift_tracks'], cwd=ROOT, check=True)
subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_authoring_build', 'tests.test_scripting_tutorial', 'tests.test_editor_play', 'tests.test_skieomod_editor', 'tests.test_editor_preferences', 'tests.test_editor_gui', 'tests.test_native_render_mapping', 'tests.test_native_navigation', 'tests.test_native_skiability', 'tests.test_native_snow', 'tests.test_native_trail_ratings', 'tests.test_native_rating_resolver', 'tests.test_skieomod_updates', 'tests.test_update_checks', 'tests.test_scenario_checkpoints', 'tests.test_game_compatibility'], cwd=ROOT, check=True)
with tempfile.TemporaryDirectory(prefix='custom-map-zip-tests-') as directory:
    create(directory)
    subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_native_terrain_pads', 'tests.test_native_game_options', 'tests.test_native_surface', 'tests.test_native_layouts'], cwd=ROOT, check=True)
    for path in sorted((ROOT / 'tests').glob('test_*.lua')):
        arguments = [lua, str(path)]
        if path.name in {'test_zip.lua', 'test_registry.lua', 'test_featured.lua', 'test_launch.lua'}:
            arguments.append(directory)
        subprocess.run(arguments, cwd=ROOT, check=True)
print('All Custom Map checks passed.')
