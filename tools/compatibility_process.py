"""Confine Linux game qualification to its own, bounded cgroup.

Never fall back to an unbounded launch. This is for isolated qualification
prefixes, not the user's ordinary Steam game or the editor's Play command.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

GIB = 1024 ** 3
LIMIT = 12 * GIB
RESERVE = 8 * GIB
UNIT = 'skieo-compatibility-test.scope'


def available_memory(path=Path('/proc/meminfo')):
    for line in path.read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise RuntimeError('Cannot determine available memory; game test was not started')


def prefix_pids(prefix, proc=Path('/proc')):
    """Wine calls its executable GameThread; process names are not identities."""
    marker = ('STEAM_COMPAT_DATA_PATH=' + str(prefix)).encode()
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if marker in (entry / 'environ').read_bytes().split(b'\0'):
                found.append(int(entry.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return found


class Limits:
    def __init__(self, output, *, limit=LIMIT, reserve=RESERVE):
        if not isinstance(limit, int) or not 2 * GIB <= limit <= LIMIT:
            raise ValueError('Test memory limit must be between 2 and 12 GiB')
        self.limit = limit
        if not isinstance(reserve, int) or not 4 * GIB <= reserve <= RESERVE:
            raise ValueError('Startup reserve must be between 4 and 8 GiB')
        self.reserve = reserve
        self.high = limit - GIB
        self.output = Path(output).resolve()
        self.record = self.output / 'memory-limit.json'
        self.trace = self.output / 'memory-usage.jsonl'
        self.last_sample = 0
        self.reason = None

    def prepare(self, arguments, environment):
        prefix = self.output / 'compatdata'
        if Path(environment.get('STEAM_COMPAT_DATA_PATH', '')).resolve() != prefix:
            raise RuntimeError('Memory-limited tests require their own output/compatdata prefix')
        remaining = prefix_pids(prefix)
        if remaining:
            raise RuntimeError('This test prefix is still running (PIDs ' + ', '.join(map(str, remaining)) + ')')
        available = available_memory()
        if available < self.limit + self.reserve:
            raise RuntimeError(f'Game test needs {self.limit / GIB:g} GiB plus {self.reserve / GIB:g} GiB free headroom; no process was started')
        (self.output / 'memory-startup.json').write_text(json.dumps({
            'available': available, 'hard_limit': self.limit, 'preventive_stop': self.high,
            'startup_reserve': self.reserve, 'runtime_minimum_available': 4 * GIB}) + '\n')
        self.record.unlink(missing_ok=True)
        self.trace.write_text('')
        return ['systemd-run', '--user', '--scope', '--quiet', '--unit=' + UNIT,
                '--property=MemoryMax=' + str(self.limit), '--property=MemoryHigh=' + str(self.high),
                '--property=MemorySwapMax=0', '--property=OOMPolicy=kill',
                sys.executable, str(Path(__file__).resolve()), '--verify-and-exec',
                str(self.record), str(self.limit), *arguments]

    def sample(self):
        now = time.monotonic()
        if now - self.last_sample < 1 or not self.record.exists():
            return self.reason
        self.last_sample = now
        metadata = json.loads(self.record.read_text())
        group = Path(metadata['cgroup'])
        try:
            current = int((group / 'memory.current').read_text())
            peak = int((group / 'memory.peak').read_text())
            processes = []
            for pid in (group / 'cgroup.procs').read_text().split():
                try:
                    status = Path('/proc', pid, 'status').read_text().splitlines()
                    fields = {s.split(':', 1)[0]: s.split(':', 1)[1].strip() for s in status}
                    processes.append({'pid': int(pid), 'name': fields['Name'], 'rss': fields.get('VmRSS')})
                except (FileNotFoundError, ProcessLookupError):
                    continue
        except FileNotFoundError:
            return self.reason
        available = available_memory()
        row = dict(time=time.time(), current=current, peak=peak, available=available,
                   processes=processes, events=(group / 'memory.events').read_text())
        with self.trace.open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        if current > self.high or available < 4 * GIB:
            self.reason = 'Isolated game exceeded its memory budget; stopped before host exhaustion'
            self.stop()
        return self.reason

    def stop(self):
        subprocess.run(['systemctl', '--user', 'stop', '--no-block', UNIT], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        # Wine may keep a fatal-error dialog open after SIGTERM. Do not wait for
        # systemd's default 90-second stop timeout, or leave a second game alive.
        subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=all', '--signal=KILL', UNIT],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)


def verify_and_exec(record, limit, arguments):
    # This runs inside systemd's new group, before Proton or Wine starts.
    relative = Path('/proc/self/cgroup').read_text().strip().split(':', 2)[2].lstrip('/')
    group = Path('/sys/fs/cgroup') / relative
    expected = {'memory.max': str(limit), 'memory.swap.max': '0', 'memory.oom.group': '1'}
    if group.name != UNIT or any((group / key).read_text().strip() != value for key, value in expected.items()):
        raise RuntimeError('Kernel memory confinement is missing; game test refused')
    temporary = Path(record).with_suffix('.tmp')
    temporary.write_text(json.dumps({'cgroup': str(group), 'limit': limit, 'swap': 0,
                                    'unit': UNIT, 'time': time.time()}) + '\n')
    temporary.replace(record)
    print(f'[Compatibility] isolated memory limit verified: {limit / GIB:g} GiB, no swap', flush=True)
    os.execvpe(arguments[0], arguments, os.environ)


if __name__ == '__main__':
    if len(sys.argv) < 5 or sys.argv[1] != '--verify-and-exec':
        raise SystemExit('Internal compatibility launcher; use check_game_compatibility.py')
    verify_and_exec(sys.argv[2], int(sys.argv[3]), sys.argv[4:])
