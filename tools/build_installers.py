#!/usr/bin/env python3
"""Embed the shared Python installer in standalone platform launchers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output=None):
    source = ROOT / 'installers'
    output = Path(output or ROOT / 'repository/web/public/install')
    output.mkdir(parents=True, exist_ok=True)
    bootstrap = (source / 'bootstrap.py').read_text().rstrip()
    assert "\n'@" not in bootstrap and '\nSKIEO_BOOTSTRAP_PY' not in bootstrap
    windows = (source / 'windows.cmd.in').read_text().replace('@@BOOTSTRAP@@', bootstrap)
    linux = (source / 'linux.sh.in').read_text().replace('@@BOOTSTRAP@@', bootstrap)
    (output / 'Install-SkiEO-Windows.cmd').write_bytes(windows.replace('\n', '\r\n').encode())
    shell = output / 'Install-SkiEO-Linux.sh'
    shell.write_bytes(linux.encode())
    shell.chmod(0o755)
    return output


if __name__ == '__main__':
    print(build())
