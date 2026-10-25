@echo off
setlocal
set "SKIEO_INSTALLER_PATH=%~f0"
powershell.exe -NoLogo -NoProfile -Command "$text=[IO.File]::ReadAllText($env:SKIEO_INSTALLER_PATH); $body=($text -split '(?m)^# POWERSHELL SCRIPT\r?$',2)[1]; & ([scriptblock]::Create($body))"
set "SKIEO_INSTALL_RESULT=%ERRORLEVEL%"
echo.
if not defined SKIEO_INSTALLER_NO_PAUSE pause
exit /b %SKIEO_INSTALL_RESULT%
# POWERSHELL SCRIPT
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$temporary = $null
try {
    Write-Host 'SkiEO Mod installer - close Ski-E-O! before continuing.'
    if (-not [Environment]::Is64BitOperatingSystem -or "$env:PROCESSOR_ARCHITECTURE $env:PROCESSOR_ARCHITEW6432" -match 'ARM') {
        throw 'The game mod needs x64 Windows. Windows on ARM and 32-bit Windows are not supported.'
    }
    function Find-SkiEOPython {
        $candidates = @()
        foreach ($name in @('python3', 'python')) {
            $command = Get-Command $name -ErrorAction SilentlyContinue
            if ($command -and $command.Source -notmatch '\\WindowsApps\\') { $candidates += $command.Source }
        }
        $candidates += "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
            try {
                & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) and sys.maxsize > 2**32 else 1)' 2>$null
                if ($LASTEXITCODE -eq 0) { return $candidate }
            } catch { }
        }
        $candidates = @()
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) {
            # Listing registered runtimes cannot trigger an automatic download.
            try { $listed = (& $launcher.Source -0p 2>$null) -join "`n" } catch { $listed = '' }
            foreach ($match in [regex]::Matches($listed, '(?im)([a-z]:\\[^\r\n]*python\.exe)\s*$')) {
                $candidates += $match.Groups[1].Value
            }
        }
        foreach ($candidate in $candidates) {
            if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
            try {
                & $candidate -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) and sys.maxsize > 2**32 else 1)' 2>$null
                if ($LASTEXITCODE -eq 0) { return $candidate }
            } catch { }
        }
        return $null
    }
    $temporary = Join-Path ([IO.Path]::GetTempPath()) ('skieomod-install-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    $python = Find-SkiEOPython
    if (-not $python) {
        Write-Host 'Installing Python 3.13 for the current user...'
        $installer = Join-Path $temporary 'python.exe'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe' -OutFile $installer
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne '5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190') {
            throw 'Python installer checksum mismatch. Nothing was executed.'
        }
        if ((Get-AuthenticodeSignature -LiteralPath $installer).Status -ne 'Valid') {
            throw 'The Python installer signature could not be verified.'
        }
        $target = "$env:LOCALAPPDATA\Programs\Python\Python313"
        $process = Start-Process -FilePath $installer -ArgumentList @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0', 'Include_test=0', 'Shortcuts=0', "TargetDir=`"$target`"") -Wait -PassThru
        if ($process.ExitCode -notin @(0,3010)) { throw "Python installation failed ($($process.ExitCode))." }
        $python = Find-SkiEOPython
        if (-not $python) { throw 'Python was installed but could not be started. Restart Windows and retry.' }
    }
    $bootstrap = Join-Path $temporary 'bootstrap.py'
    $source = @'
"""Shared, embedded installer. Run only from the downloaded platform launcher."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

INDEX = 'https://skieomod.emillon.fr/downloads/pypi/'


def run(command, *, capture=False):
    print('> ' + subprocess.list2cmdline([str(value) for value in command]), flush=True)
    environment = dict(os.environ, PYTHONUTF8='1')
    return subprocess.run(command, check=True, text=True, encoding='utf-8', env=environment,
                          stdout=subprocess.PIPE if capture else None).stdout


def usable_pipx(command):
    try:
        probe = subprocess.run([*command, '--version'], text=True, encoding='utf-8',
                               env=dict(os.environ, PYTHONUTF8='1'), stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    except OSError:
        return False
    version = re.match(r'(\d+)\.(\d+)', probe.stdout.strip())
    return probe.returncode == 0 and version is not None and tuple(map(int, version.groups())) >= (1, 7)


def pipx_command():
    existing = shutil.which('pipx')
    if existing and usable_pipx([existing]):
        return [existing]
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
        environment = base / 'SkiEO/installer/pipx'
        python = environment / 'Scripts/python.exe'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
        environment = base / 'skieomod-installer/pipx'
        python = environment / 'bin/python'
    # Reuse our own bootstrap environment; never install into system Python.
    if not python.is_file():
        run([sys.executable, '-m', 'venv', str(environment)])
    command = [str(python), '-m', 'pipx']
    if not usable_pipx(command):
        run([str(python), '-m', 'pip', 'install', '--upgrade', 'pip', 'pipx'])
    directory = Path(run([*command, 'environment', '--value', 'PIPX_BIN_DIR'], capture=True).strip()).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    name = 'pipx.exe' if sys.platform == 'win32' else 'pipx'
    target = directory / name
    if not target.exists() and not target.is_symlink():
        entry = python.parent / name
        if sys.platform == 'win32':
            shutil.copy2(entry, target)
        else:
            target.symlink_to(entry)
    return command


def install(*, tools_only=False):
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required.')
    print('Installing SkiEO Mod tools for your user account.', flush=True)
    pipx = pipx_command()
    run([*pipx, 'ensurepath'])
    run([*pipx, 'install', '--force', '--python', sys.executable,
         '--index-url', INDEX, 'skieo-custom-map'])
    directory = Path(run([*pipx, 'environment', '--value', 'PIPX_BIN_DIR'], capture=True).strip()).expanduser()
    executable = directory / ('skieomod.exe' if sys.platform == 'win32' else 'skieomod')
    if not executable.is_file():
        raise RuntimeError('pipx did not expose skieomod in ' + str(directory))
    run([str(executable), '--version'])
    if tools_only:
        print('\nTools and editor installed. Game setup was skipped for this test run.')
        print('Open the editor with: ' + subprocess.list2cmdline([str(executable), 'editor']))
    else:
        # Use the absolute entry point: ensurepath applies to the next terminal.
        run([str(executable), 'setup'])
        print('\nInstallation complete. Start Ski-E-O! through Steam, then choose')
        print('New Game > Custom Map. Maps download when you select Play.')
    return executable


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        install(tools_only=args.tools_only or os.environ.get('SKIEO_INSTALLER_TOOLS_ONLY') == '1')
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('\nInstallation stopped: ' + str(error), file=sys.stderr)
        print('Close the game and check the error above. If Steam cannot be found, install', file=sys.stderr)
        print('the game through Steam and launch it once, then run this installer again.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
'@
    [IO.File]::WriteAllText($bootstrap, $source, (New-Object Text.UTF8Encoding($false)))
    # pipx progress uses stderr; the Python process exit code determines success.
    $ErrorActionPreference = 'Continue'
    & $python $bootstrap
    $result = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
} catch {
    Write-Host ("Installation stopped: " + $_.Exception.Message) -ForegroundColor Red
    $result = 1
} finally {
    if ($temporary -and (Test-Path -LiteralPath $temporary)) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
exit $result
