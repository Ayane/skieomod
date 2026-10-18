# Publication copy — Custom Maps 1.9.1 / Veymont 0.6.1

## Short announcement

**SkiEO Custom Maps — now with maps beyond 8 km**

Create, test and share custom Ski-E-O! maps and Lua mods with `skieomod`.
Projects include commented scripts and their own documentation. Rectangular
maps are supported; choose dimensions and source resolution when creating one.
New maps include an editable JSON forest: enter tree positions in metres and
the loader places them on the terrain without a binary conversion tool.

The Featured Veymont map by **Albatar (Élie Millon)** now covers
**8.064 × 12.096 km**, including Gresse-en-Vercors, the Grand Veymont and
**Mont Aiguille**. Its terrain comes from IGN LiDAR HD, with OpenStreetMap
forest areas, 20 trails and nine real lift alignments. Existing resort
placements and the old terrain are preserved. Veymont 0.6.1 corrects four
source terrain tiles near Les Deux using reclassified IGN elevation data.
Custom Maps 1.9 supports the latest tested game build, returns to the menu
when loading fails, and shows the game logo on the loading screen.
Version 1.9.1 fixes fresh setup by retaining the tested UE4SS build on the
project server, so upstream experimental asset rotation cannot break installation.

Install the latest version with Python 3.10+ and pipx, then close the game:

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
skieomod setup
```

Start the game through Steam and select
**New Game → Custom Map → Veymont [Featured] → Play**. The game checks the latest
version and downloads the map if missing or outdated; current copies work offline. For an existing installation, update the
CLI with the same pipx command, then run `skieomod update`.

Create a 16 × 12 km map project:

```sh
skieomod create map --output my-map --size 16000 12000 --spacing 8
skieomod build my-map
skieomod run my-map
```

The native snow grid remains 2017 × 2017 and is resampled over the full
extent; larger maps trade native snow resolution for area. Visible terrain
and physical collision use the portable source. Game compatibility and
performance on the expanded map still need feedback from testers.

Steam Workshop integration is planned for the game's release. Until then,
`skieomod update` downloads verified releases from the project server.
This is a prerelease project; some lifts use the demo's substitute chairlift.

## Stable article links

- [Install and get started (English)](https://skieomod.emillon.fr/downloads/getting-started.md)
- [Latest tools](https://skieomod.emillon.fr/downloads/CustomMap-Tools.zip)
- [Latest mod, including Veymont](https://skieomod.emillon.fr/downloads/CustomMap-Mod.zip)

Author: **Albatar (Élie Millon)**. Terrain: IGN LiDAR HD Isère 2021–2022,
Aerodata / CRAIG / CD 38 / DDT 38, Open Licence v2.0. Layout and forest areas:
© OpenStreetMap contributors, ODbL 1.0.
