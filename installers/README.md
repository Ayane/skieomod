# SkiEO Mod installers

Close Ski-E-O!, install the game or demo through Steam and launch it once.
An internet connection is needed. Maps download later when you select Play.

Windows: double-click `Install-SkiEO-Windows.cmd`. It reuses 64-bit Python
3.10+ or installs the signed Python 3.13.17 x64 package for your user after
checking its SHA-256. It installs pipx if missing, installs the current tools
from the official index and runs `skieomod setup`. Windows may ask you to
confirm that you want to run a downloaded script.

Linux: download `Install-SkiEO-Linux.sh`. In its properties, allow executing
the file as a program, then open it with “Run in Terminal”. If your file manager
opens it as text, open a terminal in its download folder and run
`bash Install-SkiEO-Linux.sh`. Python/venv packages, if missing, use apt, dnf, pacman
or zypper and may ask for your sudo password. pipx and the mod run as your
normal user, outside system Python. Steam must have created the Proton prefix
by launching the game once. Sandboxed desktops can require choosing the game
folder when automatic Steam detection is unavailable.

The installer keeps the terminal open with the result. If you have both the
demo and full game installed, choose the intended installation when asked.
Existing maps, settings and saves are preserved by the loader installer.
Running the installer again updates the tools and loader.

These scripts install the mod in the Windows game, directly or under
Linux/Proton. The native macOS game is not supported by this DLL-based loader.

Sources: https://github.com/Ayane/skieomod/tree/main/installers
Python package: https://www.python.org/downloads/release/python-31317/
Regenerate the standalone launchers with
`python3 tools/build_installers.py`.
