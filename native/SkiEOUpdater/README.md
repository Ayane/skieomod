# In-game updater (ABI 1)

`sh native/SkiEOUpdater/build.sh` cross-compiles the Windows/Proton worker and
bootstrap DLL with MinGW. The installer and ZIP ship both; no Python/CLI is
required by the running game. `main.lua` recovers before requiring `entry.lua`.

The Lua scheduler only checks the canonical HTTPS release feed while the
unsupported-game warning is visible at the main menu, at most every ten minutes.
It shares the serialized native HTTP queue, validates immutable URLs, sizes,
SHA-256 and the exact ZIP manifest, and writes a flat bounded bundle, yielding
between files. The worker independently validates paths, hashes and duplicates.

The bootstrap records PID, creation time, exact executable/command line and
working directory; it copies the worker outside the managed files before launch.
The worker stages bytes, waits for that exact process to exit, then checks that
another installer has not changed the release record. Changed code is backed up
and a flushed journal precedes the first replacement. The release record is
committed last. Failure rolls back; startup recovery handles an interrupted
transaction before loading native gameplay DLLs. Modified obsolete files stay.
Reparse points below the mod root and paths outside the managed allowlist fail.

A restart requires an explicit request bound to the transaction nonce. It starts
the same executable and command line in the inherited environment; under Proton
this retains the isolated prefix. A normal exit installs without restarting.
The worker never terminates a game. The UI requests the normal Unreal QuitGame.

`main.lua` and `skieo_update_bootstrap.dll` are immutable ABI 1. Automatic updates
must contain identical hashes for both. A change to recovery requires the normal
installer; all gameplay modules, other native bridges and the worker can change.
The build removes timestamps so identical bootstrap source/toolchain produces
identical bytes. Keep recovery dependencies in this small DLL stable.

Run `tests/test_loader_update.lua` for feed/scheduler/bundle checks. `python3 tests/run_native_updater_checks.py --output build/updater-test` uses a disposable Proton prefix and a tiny Windows harness:
ready while originals stay loaded, restart with a new PID, normal exit, rollback,
simulated power interruption, staged-file tampering, traversal and bad digests.
The fault-injection macro is present only in the test worker, never the release.
