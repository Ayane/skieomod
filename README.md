# SkiEO Mod

Community maps, scenarios and modding tools for **Ski-E-O!** by
**Albatar (Élie Millon / Ayane)**. Original code is licensed under
[BSD 3-Clause](LICENSE); dependencies and map data retain their
[own licenses](THIRD_PARTY_NOTICES.md).

**[Website & installation](https://skieomod.emillon.fr)** ·
**[Tutorials](https://skieomod.emillon.fr/#tutoriels)** ·
**[Getting started](docs/getting-started.md)** · **[Changelog](CHANGELOG.md)**

## Install and play

Install Ski-E-O! through Steam, Python 3.10+ and
[pipx](https://pipx.pypa.io/stable/installation/), then close the game:

```sh
pipx ensurepath
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
skieomod setup
```

Reopen the terminal after `pipx ensurepath` if needed. On Linux / Proton,
launch the game once from Steam before setup. Setup detects the game and
installs UE4SS and the Custom Map loader.

Open **New Game → Custom Map** to browse and search maps in the game:

- **All** combines the available sources.
- **Local** shows local projects and manually installed maps.
- **Web** shows published community maps and Featured maps, including downloaded
  maps marked with a check.
- **Steam** is reserved for the Workshop adapter and installed Steam content.

Select a map and press **Play** to download missing content and required
mapmods. Downloads are checked against the catalogue's SHA-256 and manifest.
Downloaded maps remain playable offline. The catalogue is checked automatically
when the browser opens and refreshed while browsing.
Map updates remain optional; locally authored files are preserved.

Use **Options** before **Play** to choose sandbox, day length and days per month.
Sandbox removes costs and unlocks everything, disables achievements and skips
scripted scenario objectives and charges. Native saves retain the selected mode.
Portable maps keep their authored terrain dimensions.

Try [Veymont](mod/SkiEO-Veymont/README.md), based on real Vercors terrain, or
[Super Saint-Bernard](mod/SkiEO-SuperSaintBernard/README.md), a historical
resort scenario. Game updates can require compatibility fixes; see the
[compatibility protocol](docs/game-compatibility-testing.md).
The [snow correction report](docs/flying-snow-1.24.8.md) explains the terrain
and furniture fixes in 1.24.8.
The [26111862 report](docs/game-update-26111862.md) records the current demo
qualification and guarded automatic relocation of native functions. The
[26097896 report](docs/game-update-26097896.md) describes automatic mod updates
from the version warning.

## Create and publish

```sh
skieomod create map --output my-map --name "My resort" --author "Your name"
skieomod editor my-map
skieomod build my-map
skieomod test my-map --check-scripts
skieomod run my-map
skieomod publish my-map
```

Web publication uses `CUSTOM_MAP_TOKEN`, created from your
[Steam creator account](https://skieomod.emillon.fr/account). It accepts a
project, manifest or `.skieomap` / `.skieomod` archive. Published versions
are immutable: increment `metadata.version` to release an update. Maps appear
in the in-game web catalogue. See the [publication guide](docs/custom-map-repository.md)
for authentication and repository configuration.

Steam Workshop integration is in preparation. `skieomod publish --prepare`
stages unpacked Workshop content offline. `publish --steam` requires a
separately supplied native Steamworks client; one is not included here.

Follow the [editor tutorial](https://skieomod.emillon.fr/tutorials/editor/),
[heightmap tutorial](https://skieomod.emillon.fr/tutorials/heightmap/),
[scenario tutorial](https://skieomod.emillon.fr/tutorials/scripts/) or
[mapmod tutorial](https://skieomod.emillon.fr/tutorials/mapmods/).
The [CLI guide](docs/custom-map-cli.md), [map format](docs/custom-map-format.md)
and [Steam contract](docs/steam-workshop.md) cover the interfaces.

## Develop

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
python tests/run_custom_map_checks.py
```

Checks require Lua 5.4 (`lua` and `luac` on `PATH`), or `CUSTOM_MAP_LUA` for
the interpreter. Native C fixture tests use a C compiler. Qt tests run when
the desktop dependencies are installed. No game installation is needed for
the automated suite; actual terrain, rendering and save behavior must also
be tested in the game.

The Windows native helpers and build instructions live under `native/`.
The optional [asset research tools](third_party/README.md) use a pinned
UAssetAPI submodule with an explicit .NET 8 compatibility patch.

```sh
cd repository/web
npm ci
npm run build
```

The Angular site introduces the mod and hosts tutorials. The WSGI API retains
Steam authentication, publication, dependency resolution and the in-game
registry. [Deployment instructions](deployment/README.md) describe the
canonical domain and the `skieomap.emillon.fr` redirect.

Generated releases, game exports, personal test projects and credentials do
not belong in the public source tree. The loader's small native DLLs are
included for installation; their source is in `native/`. Map source data and
tutorial exercise assets are included under the licenses documented alongside them.

## Credits

- [Albatar (Élie Millon / Ayane)](https://github.com/Ayane): project creator and
  maintainer; Custom Maps, `skieomod` and Veymont.
- [ReymanHG](https://github.com/ReymanHG): fixes for baked ground-cover textures
  ([#1](https://github.com/Ayane/skieomod/pull/1)) and night lighting
  ([#2](https://github.com/Ayane/skieomod/pull/2)), released in 1.24.4.

Dependencies and map data are credited in [third-party notices](THIRD_PARTY_NOTICES.md)
and in the licenses and credits shipped with each map or mapmod.
