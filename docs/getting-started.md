# SkiEO Custom Maps

By **Albatar (Élie Millon)**.

Contributions by **[ReymanHG](https://github.com/ReymanHG)**: fixes for ground-cover
textures and night lighting, released in 1.24.4. See the
[project credits](https://github.com/Ayane/skieomod#credits).

Custom Maps adds playable custom maps and Lua mods to **Ski-E-O!**. The
`skieomod` command-line tool installs the loader, keeps it updated before Steam
Workshop becomes available, and helps you create, test and publish your own projects.
The default website is https://skieomod.emillon.fr; the old skieomap hostname redirects there.
Browse published maps directly in **New Game → Custom Map**, using the
**All / Local / Web / Steam** filters and search.
**Local** contains local projects and manually installed maps. Downloaded web
maps stay in **Web**, with a check mark. The catalogue refreshes automatically
on opening and every five minutes while browsing; cached maps remain available
when the server cannot be reached.

Open **Options** before **Play** to select sandbox, day length and days per month.
Sandbox removes native costs, unlocks everything and disables achievements;
custom scenario objectives and scripted charges are disabled too. The mode is
retained in native saves. Custom terrain keeps the dimensions authored by its creator.
Web publication uses `skieomod publish PROJECT` and a token from
https://skieomod.emillon.fr/account; see the [publication guide](custom-map-repository.md).

**Veymont**, also by Albatar (Élie Millon), appears as a **Featured** map. It is downloaded
from the project server when you press **Play**, then cached for later sessions. Explore Gresse-en-Vercors, the Grand Veymont and Mont Aiguille on an
8.064 × 12.096 km map with real terrain,
snow, forests, 20 trails and nine lift alignments to see a complete example scene
before making your own map.

## Install and play

For Windows or Linux, use the [downloadable installers](https://skieomod.emillon.fr/install/).
Windows: double-click the `.cmd`. Linux: download the `.sh`, allow executing
it as a program in its properties, then choose **Run in Terminal**. If it opens
as text, open a terminal in the download folder and run
`bash Install-SkiEO-Linux.sh`.
They check Python and pipx, install missing components and run setup. Close
the game first and launch it through Steam once before installing the mod.
The current DLL-based game loader does not support the native macOS game.

For manual installation, use the commands below.

You need **Python 3.10 or later**, **pipx** on your PATH, and the Windows edition
of Ski-E-O! or its demo installed through Steam. Linux with Proton is supported.
Launch the game once, then close it before installation.

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
skieomod setup
```

From Custom Map 1.24.7, an unsupported-game warning also checks for newer mod
versions automatically while at the main menu. It downloads and verifies a newer official release in the background.
**Restart game** applies it after the game closes and relaunches the same game.
Closing normally applies the prepared update without relaunching. Maps, settings
and saves are preserved. Install 1.24.7 normally once to enable this feature.

The installation command always selects the latest published version. `setup`
finds your Steam installation, installs UE4SS and Custom Maps, configures Proton
when needed. Maps are downloaded separately when you play. If detection fails, use
`skieomod setup --game-dir "PATH TO GAME"`.

UE4SS comes from the project's retained, tested build. Its versioned archive
and checksum stay fixed when upstream publishes a new experimental build.

Start the game through Steam and select **New Game → Custom Map → Veymont**.
Press **Play** to check the current version and download Veymont if it is missing
or outdated. A current downloaded copy remains playable offline. No Workshop
subscription is required. Maps are kept out of the CLI and loader distributions.

If `skieomod setup` reports an HTTPS certificate error, check your computer's
date and time and install operating system updates. Update the tools using the
installation command above, then retry setup. Windows downloads use the native
Windows certificate validator. If the error persists, include the complete
message and your Windows and Python versions in your report.

## Stay updated

skieomod checks release metadata in the background at most once a day. A new
installed Steam revision triggers a fresh check immediately. The editor also
checks while it remains open and shows notices in its status bar; use **Game →
Check for updates** to check manually. Offline checks leave your work available
and retry after an hour. Updates are installed only when you request them.

Each loader release records the Steam revisions tested with it. A different
game revision is reported as unverified, so you can check for a compatible
release before testing a map. `skieomod update --check` downloads only the small
release manifest, without downloading the loader ZIP.

Custom Map also shows a warning above the browser when the running executable
does not match a qualified build, or its version cannot be verified. This check
works offline and lists the supported Steam build. After a game update, check
for a new mod release before starting a custom map.

If you installed CLI 1.6 or earlier, repeat the installation command once: the
expanded example needs CLI 1.7 or later. Close the game, then run:

```sh
skieomod update --check
skieomod update
```

Updates come from the project server, verify their checksums, back up replaced
loader files and preserve existing maps and settings. Repeat the installation
command above when you need to update the CLI itself.

## Uninstall

Close the game and editor, then run:

```sh
skieomod uninstall-self --check
skieomod uninstall-self
```

`--check` previews removal without changing files. By default, `uninstall-self`
removes Custom Map from the configured game, then removes the CLI with pipx
or the current Python environment's pip. Use `--mod-only` to keep the CLI,
or `--cli-only` to keep the mod. `--game-dir "PATH TO GAME"` selects another
installation; `--ue4ss-mods "PATH TO MODS"` limits removal to that Mods folder.

The mod folder, including scripts, settings and backups, is moved beside its
old location into `.skieomod-backups/uninstall-TIMESTAMP/`. Custom Map entries
are removed from `mods.txt`. Downloaded maps, source projects, other mods,
UE4SS and CLI configuration are preserved. Legacy `skieomod://` registrations
pointing to this CLI are removed when uninstalling the command.

## Create your first map

Prefer a graphical interface? With CLI **1.15 or later**, run:

```sh
skieomod editor
```

The workshop reopens your last map by default. **Preferences → Settings…**
can instead start with a new map or no map. **File → Recent maps** and the
welcome panel list your recently opened source projects. Click **New** to
create an empty map immediately. Sculpt, place objects or import
your own heightmap. First Save asks only for a folder; then Build, Test and Play.
Play starts its own test instance and reloads it on subsequent runs.
Open an existing source project with `skieomod editor my-map`. The
**Editor** button in **New Game → Custom Map** also opens the desktop editor,
using your startup preference. Upgrade the skieomod tools as well as the loader;
`skieomod setup` and `skieomod update` register the editor link on Windows and Linux.
The native editor uses Qt and an OpenGL 3D viewport; its dependencies are installed with
the package. Its toolbar opens visual triggers, resources and object properties.
Follow the [illustrated editor tutorial](https://skieomod.emillon.fr/tutorials/editor/)
to create a first map using the graphical controls, with terrain, trees,
buildings, a lift and a downloadable practice source. An
[offline copy](editor-tutorial.md) is available here; the
[editor reference](https://skieomod.emillon.fr/docs/editor.md) covers advanced features.

To add gameplay rules, follow the [scripts and scenarios tutorial](https://skieomod.emillon.fr/tutorials/scripts/).
It recommends visual graphs for beginners, with actual Super Saint-Bernard
captures, optional Lua equivalents and a downloadable first-season project.
The tools also include an [offline scripting guide](scripts-and-scenarios.md).

Already have a heightmap? The [illustrated English tutorial](https://skieomod.emillon.fr/tutorials/heightmap/)
walks through creation and testing without a graphical editor. CLI 1.10 builds
from headerless R16LE/R16BE or non-interlaced 16-bit grayscale PNG without a
separate conversion tool. Put the source file inside the project and add `build.heightmap`
to `custom-map.json`:

```json
"build": {
  "heightmap": {
    "file": "Terrain/source-heightmap.png",
    "spacing_meters": 8,
    "elevation_meters": [800, 2200]
  }
}
```

Run `skieomod build my-map`, then `skieomod run my-map`. Build reads PNG
dimensions and calculates the extent, elevation encoding, centred origin and
preview. It writes the derived terrain metadata and portable R16 after validation,
with backups in `.heightmap-backups/`, while retaining the original input.
Square raw R16 can infer dimensions. For a rectangle, supply `vertices:
[width, height]` or one side with `null` for the other; use `format: "r16be"`
for a big-endian export. Omit elevation settings for a relative 0–1,000 m test. Supply your actual elevation endpoints, or the exporter's
`height_scale_meters` and `height_offset_meters` instead of `elevation_meters`.

```sh
skieomod help
skieomod create map --output my-map --name "My resort" --author "Your name"
skieomod build my-map
skieomod run my-map
```

Maps can exceed 8 km and use rectangular extents. For a 16 × 12 km starter:

```sh
skieomod create map --output large-map --size 16000 12000 --spacing 8
```

Both lengths are in metres and must be multiples of the source spacing.
The generated terrain guide explains resolution and rendering detail.
CLI map templates also include `Vegetation/forest.json` (editor New maps are empty): edit its `x` and `y`
positions in metres. The build compiles it to SKXY; only binary trees enter the game.

To bake erosion, green ground cover and automatic trees from the heightmap,
set `build.heightmap.processing` and `build.vegetation` in the same JSON.
The [vegetation guide](https://skieomod.emillon.fr/tutorials/heightmap/#bake)
includes a complete preset. Every build starts from your original source;
generated terrain and trees are reproducible.

Open `my-map/README.md` and `my-map/docs/` for the commented scripts and next
steps. `create mod` and `create mapmod` provide other templates;
`skieomod help COMMAND` explains each command.

To share behaviour and assets between maps, follow the
[mapmod tutorial](https://skieomod.emillon.fr/tutorials/mapmods/).
It includes a small practice project, the fox example, local dependency testing
and separate versioned distribution. An [offline copy](mapmod-tutorial.md)
ships with the tools; [mapmods.md](mapmods.md) documents the runtime API.

This is a prerelease project: game updates can affect compatibility. Veymont
credits IGN LiDAR HD (Open Licence v2.0) and OpenStreetMap contributors
(ODbL 1.0); some demo lifts use substitute chairlift models.
