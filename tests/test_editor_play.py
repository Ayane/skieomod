"""Editor-owned game handoff and reuse, without launching a real process."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from tools import skieo_install as d

class EditorPlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.token='a'*32;self.scripts=self.root/'mods/SkiEO-CustomMaps/Scripts';self.scripts.mkdir(parents=True)
        self.maps=self.root/'maps';self.maps.mkdir();(self.maps/'test.alpine-1.0.0.skieomap').write_bytes(b'zip fixture')
        self.config={'app_id':'5012760','maps_dir':str(self.maps),'ue4ss_mods':str(self.root/'mods')}
        self.release={'kind':'map','id':'test.alpine','version':'1.0.0'}
        self.addCleanup(patch.stopall)
        patch.object(d,'config_directory',return_value=self.root/'config').start()
    def test_launch_then_reload_targets_only_this_editor_session(self):
        generic=self.scripts/'launch-request.json';generic.write_bytes(b'ordinary game request')
        writer=d.atomic_json
        def acknowledge(path,data):
            writer(path,data)
            if path.name.startswith('launch-request'):
                writer(path.with_name(path.name.replace('request','result')),{'request_id':data['request_id'],'status':'started'})
        with patch.object(d,'editor_launch_plan',return_value=(['game.exe'],{'SKIEOMOD_EDITOR_SESSION':self.token},self.root)),patch.object(d,'ensure_editor_steam') as steam,patch.object(d,'atomic_json',side_effect=acknowledge),patch.object(d.subprocess,'Popen') as process,contextlib.redirect_stdout(io.StringIO()):
            d.request_play(self.config,self.release,editor_session=self.token);self.assertEqual(process.call_count,1)
            writer(self.scripts/('editor-session-'+self.token+'.json'),{'session':self.token,'updated':int(time.time()),'state':'ready'})
            d.request_play(self.config,self.release,editor_session=self.token);self.assertEqual(process.call_count,1)
            steam.assert_called_once()
        request=json.loads((self.scripts/('launch-request-'+self.token+'.json')).read_text())
        self.assertEqual(request['editor_session'],self.token);self.assertEqual(generic.read_bytes(),b'ordinary game request')
    def test_loading_and_stale_sessions_are_not_reused(self):
        heartbeat=self.scripts/('editor-session-'+self.token+'.json')
        d.atomic_json(heartbeat,{'session':self.token,'updated':int(time.time())-10,'state':'ready'});self.assertIsNone(d.editor_session_state(self.config,self.token))
        d.atomic_json(heartbeat,{'session':self.token,'updated':int(time.time()),'state':'loading'})
        with patch.object(d,'editor_launch_plan',return_value=([],{},self.root)),patch.object(d.subprocess,'Popen') as process:
            with self.assertRaisesRegex(d.ManifestError,'still loading'):d.request_play(self.config,self.release,editor_session=self.token)
            process.assert_not_called()
        self.assertFalse((self.scripts/('launch-request-'+self.token+'.json')).exists())
    def test_proton_initializes_renderer_and_passes_session_to_game(self):
        steam=self.root/'steam';common=steam/'steamapps/common';tool=common/'Proton 9.0';tool.mkdir(parents=True);(tool/'proton').write_text('script')
        library=self.root/'library/steamapps';prefix=library/'compatdata/5012760';(prefix/'pfx').mkdir(parents=True);(prefix/'config_info').write_text(str(tool)+'/files/share/fonts/\n')
        (steam/'config').mkdir();binary=self.root/'game/Binaries/Win64';binary.mkdir(parents=True);(binary/'skieogame.exe').write_bytes(b'exe')
        config={**self.config,'steamapps_dir':str(library),'binary_dir':str(binary)}
        with patch.object(d.sys,'platform','linux'),patch.object(d,'steam_roots',return_value=[steam]):
            arguments,environment,directory=d.editor_launch_plan(config,self.token)
        self.assertEqual(arguments[:2],[str(tool/'proton'),'run']);self.assertEqual(directory,binary)
        self.assertEqual(environment['SKIEOMOD_EDITOR_SESSION'],self.token);self.assertIn('-SkiEOEditorSession='+self.token,arguments)
        self.assertEqual(environment['STEAM_COMPAT_DATA_PATH'],str(prefix))
    def test_windows_starts_executable_directly(self):
        binary=self.root/'Win64';binary.mkdir();(binary/'skieogame.exe').write_bytes(b'exe')
        with patch.object(d.sys,'platform','win32'):
            arguments,environment,_=d.editor_launch_plan({**self.config,'binary_dir':str(binary)},self.token)
        self.assertEqual(arguments[0],str(binary/'skieogame.exe'));self.assertEqual(environment['SteamAppId'],'5012760')

    def test_closed_steam_starts_cleanly_before_any_test_process(self):
        steam=self.root/'steam';steam.mkdir();(steam/'steam.sh').write_text('launcher')
        dirty={'SteamAppId':'5012760','SteamGameId':'5012760','SKIEOMOD_EDITOR_SESSION':self.token,
               'STEAM_COMPAT_DATA_PATH':'prefix','PROTON_LOG':'1','WINEPREFIX':'prefix',
               'WINEDLLOVERRIDES':'dwmapi=n,b','DISPLAY':':0','PATH':'/usr/bin'}
        with patch.object(d.sys,'platform','linux'),patch.dict(d.os.environ,dirty,clear=True),patch.object(d.shutil,'which',return_value=None),patch.object(d,'steam_client_ready',side_effect=[False,False,True]) as ready,patch.object(d.time,'sleep'),patch.object(d.subprocess,'Popen') as process:
            d.ensure_editor_steam({'STEAM_COMPAT_CLIENT_INSTALL_PATH':str(steam)})
        self.assertEqual(ready.call_count,3)
        self.assertEqual(process.call_args.args[0],[str(steam/'steam.sh'),'-silent'])
        self.assertEqual(process.call_args.kwargs['env'],{'DISPLAY':':0','PATH':'/usr/bin'})
        self.assertTrue(process.call_args.kwargs['start_new_session'])

    def test_running_steam_is_not_started_again(self):
        with patch.object(d.sys,'platform','linux'),patch.object(d,'steam_client_ready',return_value=True),patch.object(d.subprocess,'Popen') as process:
            d.ensure_editor_steam({'STEAM_COMPAT_CLIENT_INSTALL_PATH':str(self.root)})
        process.assert_not_called()

    def test_steam_timeout_does_not_write_request_or_start_game(self):
        with patch.object(d,'editor_launch_plan',return_value=([],{},self.root)),patch.object(d,'ensure_editor_steam',side_effect=d.ManifestError('Steam did not finish initialization')),patch.object(d.subprocess,'Popen') as process:
            with self.assertRaisesRegex(d.ManifestError,'Steam did not finish'):
                d.request_play(self.config,self.release,editor_session=self.token)
        process.assert_not_called()
        self.assertFalse((self.scripts/('launch-request-'+self.token+'.json')).exists())

    def test_steam_readiness_ignores_old_startups_and_dead_pids(self):
        client=self.root/'steam';(client/'logs').mkdir(parents=True)
        marker=self.root/'.steam/steam.pid';marker.parent.mkdir();marker.write_text('12345')
        console=client/'logs/console_log.txt'
        now=time.time();os.utime(marker,(now,now))
        stamp=lambda timestamp:time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(timestamp))
        original=Path.read_text
        def read(path,*args,**kwargs):
            if str(path)=='/proc/12345/comm':return 'steam\n'
            return original(path,*args,**kwargs)
        with patch.object(d.Path,'home',return_value=self.root),patch.object(Path,'read_text',read):
            console.write_text('['+stamp(now-60)+'] System startup time: 8.0 seconds\n')
            self.assertFalse(d.steam_client_ready(client))
            console.write_text('['+stamp(now)+'] System startup time: 8.0 seconds\n')
            self.assertTrue(d.steam_client_ready(client))
            with console.open('a') as stream:
                stream.write('ordinary client output\n' * 5000)
            self.assertTrue(d.steam_client_ready(client), 'live Steam startup fell outside a tail window')
            with console.open('a') as stream:
                stream.write('['+stamp(now-60)+'] System startup time: 8.0 seconds\n')
            self.assertFalse(d.steam_client_ready(client), 'a previous startup hid a newer stale marker')
            marker.write_text('12346')
            self.assertFalse(d.steam_client_ready(client))

    def test_early_exit_is_reported_and_pending_request_removed(self):
        process=Mock(returncode=42);process.poll.return_value=42
        with patch.object(d,'editor_launch_plan',return_value=(['game'],{},self.root)),patch.object(d,'ensure_editor_steam'),patch.object(d.subprocess,'Popen',return_value=process),patch.object(d,'stop_editor_launch') as stop:
            with self.assertRaisesRegex(d.ManifestError,'exit code 42'):
                d.request_play(self.config,self.release,editor_session=self.token)
        stop.assert_called_once_with(process,token=self.token,binary=self.root/'skieogame.exe')
        self.assertFalse((self.scripts/('launch-request-'+self.token+'.json')).exists())
        self.assertTrue((self.root/'config/logs'/('editor-'+self.token+'.log')).is_file())

    def test_game_timeout_stops_only_new_instance(self):
        process=Mock();process.poll.return_value=None
        with patch.object(d,'editor_launch_plan',return_value=(['game'],{},self.root)),patch.object(d,'ensure_editor_steam'),patch.object(d.subprocess,'Popen',return_value=process),patch.object(d,'stop_editor_launch') as stop,patch.object(d,'EDITOR_LAUNCH_TIMEOUT',0):
            with self.assertRaisesRegex(d.ManifestError,'did not respond'):
                d.request_play(self.config,self.release,editor_session=self.token)
            stop.assert_called_once_with(process,token=self.token,binary=self.root/'skieogame.exe')
            stop.reset_mock();process.reset_mock()
            d.atomic_json(self.scripts/('editor-session-'+self.token+'.json'),{'session':self.token,'updated':int(time.time()),'state':'ready'})
            with self.assertRaisesRegex(d.ManifestError,'did not respond'):
                d.request_play(self.config,self.release,editor_session=self.token)
            stop.assert_not_called()
        self.assertFalse((self.scripts/('launch-request-'+self.token+'.json')).exists())

    def test_failed_spawn_removes_request(self):
        with patch.object(d,'editor_launch_plan',return_value=(['game'],{},self.root)),patch.object(d,'ensure_editor_steam'),patch.object(d.subprocess,'Popen',side_effect=OSError('not executable')),patch.object(d,'stop_editor_launch') as stop:
            with self.assertRaisesRegex(d.ManifestError,'Could not start the editor test'):
                d.request_play(self.config,self.release,editor_session=self.token)
        stop.assert_not_called()
        self.assertFalse((self.scripts/('launch-request-'+self.token+'.json')).exists())

    def test_cleanup_targets_owned_group_and_escalates_if_needed(self):
        process=Mock(pid=12345)
        process.wait.side_effect=[d.subprocess.TimeoutExpired('game',3),0]
        with patch.object(d.sys,'platform','linux'),patch.object(d.os,'killpg') as kill:
            d.stop_editor_launch(process)
        self.assertEqual(kill.call_args_list,[unittest.mock.call(12345,d.signal.SIGTERM),unittest.mock.call(12345,d.signal.SIGKILL)])

    def test_real_failed_child_is_reaped_and_output_preserved(self):
        arguments=[d.sys.executable,'-c','import sys; print("Steam API initialization failed", flush=True); sys.exit(7)']
        with patch.object(d,'editor_launch_plan',return_value=(arguments,dict(os.environ),self.root)),patch.object(d,'ensure_editor_steam'):
            with self.assertRaisesRegex(d.ManifestError,'exit code 7'):
                d.request_play(self.config,self.release,editor_session=self.token)
        log=self.root/'config/logs'/('editor-'+self.token+'.log')
        self.assertIn('Steam API initialization failed',log.read_text())

    def test_detached_wine_game_is_identified_without_shared_steam_or_wine_helpers(self):
        proc=self.root/'proc';proc.mkdir();binary=self.root/'game/skieogame.exe'
        def add(pid,executable,session,argument):
            entry=proc/str(pid);entry.mkdir()
            (entry/'environ').write_bytes(('SKIEOMOD_EDITOR_SESSION='+session+'\0').encode())
            (entry/'cmdline').write_bytes((executable+'\0'+argument+'\0').encode())
        argument='-SkiEOEditorSession='+self.token
        add(10,'Z:'+str(binary).replace('/','\\'),self.token,argument)
        add(11,'/usr/bin/steam',self.token,argument)
        add(12,'/proton/files/bin/wineserver',self.token,argument)
        add(13,str(binary),'b'*32,'-SkiEOEditorSession='+'b'*32)
        add(14,str(binary),self.token,'')
        add(15,str(binary),self.token,'-SkiEOEditorSession='+'b'*32)
        self.assertEqual(d.editor_game_pids(self.token,binary,proc=proc),[10])

    def test_cleanup_also_stops_detached_game_with_matching_session(self):
        process=Mock(pid=12345)
        with patch.object(d.sys,'platform','linux'),patch.object(d,'editor_game_pids',side_effect=[[45678],[]]) as games,patch.object(d.os,'kill') as kill,patch.object(d.os,'killpg') as group:
            d.stop_editor_launch(process,token=self.token,binary=self.root/'game.exe')
        self.assertEqual(games.call_count,2)
        kill.assert_called_once_with(45678,d.signal.SIGTERM)
        group.assert_called_once_with(12345,d.signal.SIGTERM)
