import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import compatibility_process as launch


class MemoryTests(unittest.TestCase):
    def test_detached_wine_is_found_without_executable_name(self):
        with tempfile.TemporaryDirectory() as directory:
            proc=Path(directory)
            for pid,prefix in [('12','/isolated'),('13','/player-game')]:
                p=proc/pid;p.mkdir()
                (p/'environ').write_bytes(('STEAM_COMPAT_DATA_PATH='+prefix+'\0').encode())
                (p/'comm').write_text('GameThread')
            self.assertEqual(launch.prefix_pids('/isolated',proc),[12])

    def test_refuses_existing_prefix_shared_prefix_and_low_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            limits=launch.Limits(directory)
            env={'STEAM_COMPAT_DATA_PATH':str(Path(directory)/'compatdata')}
            with patch.object(launch,'prefix_pids',return_value=[99]):
                with self.assertRaisesRegex(RuntimeError,'still running'):limits.prepare(['game'],env)
            with self.assertRaisesRegex(RuntimeError,'own output'):limits.prepare(['game'],{})
            with patch.object(launch,'prefix_pids',return_value=[]),patch.object(launch,'available_memory',return_value=19*launch.GIB):
                with self.assertRaisesRegex(RuntimeError,'headroom'):limits.prepare(['game'],env)

    def test_launch_has_kernel_limits_and_verifies_before_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            limits=launch.Limits(directory)
            with patch.object(launch,'prefix_pids',return_value=[]),patch.object(launch,'available_memory',return_value=24*launch.GIB):
                args=limits.prepare(['game','argument with spaces'],{'STEAM_COMPAT_DATA_PATH':str(Path(directory)/'compatdata')})
            self.assertIn('--property=MemoryMax='+str(12*launch.GIB),args)
            self.assertIn('--property=OOMPolicy=kill',args)
            self.assertIn('--verify-and-exec',args)
            self.assertEqual(args[-2:],['game','argument with spaces'])

    def test_sampling_stops_only_test_group_before_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);group=root/'group';group.mkdir()
            for key,value in {'memory.current':str(11*launch.GIB+1),'memory.peak':str(12*launch.GIB),
                              'cgroup.procs':'','memory.events':'oom 0\n'}.items():
                (group/key).write_text(value)
            limits=launch.Limits(root);limits.record.write_text(json.dumps({'cgroup':str(group)}))
            with patch.object(launch,'available_memory',return_value=9*launch.GIB),patch.object(limits,'stop') as stop:
                self.assertIsNotNone(limits.sample());stop.assert_called_once()
            self.assertEqual(json.loads(limits.trace.read_text())['peak'],12*launch.GIB)

    def test_smaller_budget_keeps_reserve_and_lowers_early_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);group=root/'group';group.mkdir()
            limits=launch.Limits(root,limit=8*launch.GIB)
            env={'STEAM_COMPAT_DATA_PATH':str(root/'compatdata')}
            with patch.object(launch,'prefix_pids',return_value=[]),patch.object(launch,'available_memory',return_value=18*launch.GIB):
                args=limits.prepare(['game'],env)
                self.assertIn('--property=MemoryMax='+str(8*launch.GIB),args)
                self.assertIn('--property=MemoryHigh='+str(7*launch.GIB),args)
            with patch.object(launch,'prefix_pids',return_value=[]),patch.object(launch,'available_memory',return_value=15*launch.GIB):
                with self.assertRaisesRegex(RuntimeError,'headroom'):limits.prepare(['game'],env)
            for key,value in {'memory.current':str(7*launch.GIB+1),'memory.peak':str(7*launch.GIB+1),
                              'cgroup.procs':'','memory.events':'oom 0\n'}.items():
                (group/key).write_text(value)
            limits.record.write_text(json.dumps({'cgroup':str(group)}))
            with patch.object(launch,'available_memory',return_value=10*launch.GIB),patch.object(limits,'stop') as stop:
                self.assertIsNotNone(limits.sample());stop.assert_called_once()

    def test_budget_cannot_disable_kernel_ceiling(self):
        for value in (0,launch.GIB,13*launch.GIB,float('inf')):
            with self.assertRaises(ValueError):launch.Limits('/tmp/unused',limit=value)

    def test_explicit_startup_reserve_keeps_runtime_stop_and_records_it(self):
        with tempfile.TemporaryDirectory() as directory:
            limits=launch.Limits(directory,limit=8*launch.GIB,reserve=6*launch.GIB)
            env={'STEAM_COMPAT_DATA_PATH':str(Path(directory)/'compatdata')}
            with patch.object(launch,'prefix_pids',return_value=[]),patch.object(launch,'available_memory',return_value=14*launch.GIB):
                args=limits.prepare(['game'],env)
            record=json.loads((Path(directory)/'memory-startup.json').read_text())
            self.assertEqual(record['startup_reserve'],6*launch.GIB)
            self.assertEqual(record['runtime_minimum_available'],4*launch.GIB)
            self.assertIn('--property=MemoryMax='+str(8*launch.GIB),args)
            self.assertEqual(limits.high,7*launch.GIB)
        for reserve in (0,3*launch.GIB,9*launch.GIB):
            with self.assertRaises(ValueError):launch.Limits('/tmp/unused',reserve=reserve)


if __name__=='__main__':unittest.main()
