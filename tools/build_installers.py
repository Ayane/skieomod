#!/usr/bin/env python3
"""Embed the shared Python installer in standalone platform launchers."""
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.custom_maps import write_zip_member


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
    with zipfile.ZipFile(output / 'Install-SkiEO-Linux.zip', 'w') as archive:
        for name, data, mode in [
            ('Install-SkiEO-Linux.sh', linux.encode(), 0o100755),
            ('Install-SkiEO.desktop', (source / 'Install-SkiEO.desktop').read_bytes(), 0o100755),
            ('README.txt', (source / 'README.md').read_bytes(), 0o100644),
        ]:
            write_zip_member(archive, name, data)
            info=archive.getinfo(name)
            info.create_system=3
            info.external_attr=mode << 16
    return output


if __name__ == '__main__':
    print(build())
