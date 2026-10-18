# Third-party code and data

SkiEO Mod's original code is licensed under BSD-3-Clause; see [LICENSE](LICENSE).
The following components and data retain their own licenses:

| Component | License / attribution |
| --- | --- |
| miniz, used by the native repository helper | MIT; [full notice](native/SkiEORepository/LICENSE), also shipped as `LICENSE-miniz.txt` |
| MinHook, used by native terrain and trail ratings | BSD-2-Clause; [full notice](mod/SkiEO-CustomMaps/LICENSE-MINHOOK.md) |
| UAssetAPI (optional asset research tools) | MIT; upstream license and notices in the submodule |
| IGN / LiDAR HD terrain for Veymont | Licence Ouverte 2.0; see [map provenance](maps/veymont/map.json) |
| OpenStreetMap tracks, lifts and places | © OpenStreetMap contributors, ODbL; see map manifests |
| Fox example code | MIT; see `mod/SkiEO-Foxes/CREDITS.txt` |
| Tutorial models and fox artwork | Licenses and credits next to the relevant assets and in each map/mod manifest |

Python and JavaScript dependencies keep their upstream licenses. UE4SS is
downloaded separately by `skieomod setup`. Ski-E-O! and Unreal Engine assets
are supplied by the installed game and are not covered by this repository's
BSD license. Historical game exports and build outputs are excluded from the
public source repository.
