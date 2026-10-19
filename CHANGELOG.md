# SkiEO Custom Maps changelog

Release notes for the skieomod tools and Custom Map game loader. Maps and mapmods
have their own package versions. Download the
[latest tools](https://skieomod.emillon.fr/downloads/CustomMap-Tools.zip) and
[latest loader](https://skieomod.emillon.fr/downloads/CustomMap-Mod.zip).

## [Unreleased]

- Add the editor map tutorial to the workshop's Help menu and packaged guides.
- Include this changelog in the tools and publish a versioned copy with each release.
- Prepare optional Discord release announcements after HTTPS publication checks,
  with a preview mode and receipts for confirmed messages.

## [1.24.5] - 2026-10-19

- Adapt the reviewed native profiles to demo build 26056171, including the
  changed hub batching counter and navigation layout. Keep previous profiles.
- Add native Options to Custom Map: sandbox, day length and days per month.
  Capture settings before downloads and preserve sandbox mode in native saves.
  Sandbox disables scripted scenario objectives and charges as well as native costs.
- Refresh web catalogues automatically on opening the browser and every five
  minutes while browsing. Keep cached maps available offline; remove Refresh maps.
- Keep downloaded web and Featured maps in Web, with an installed check mark;
  reserve Local for local projects and manually installed maps.
- Keep Custom Map and the shared tabs below the native Options modal. Pad
  preview captions, anchor row icons within their cards and show the author
  directly below the map title.
- Credit ReymanHG in the documentation, CLI help and website for the 1.24.4 fixes.

## [1.24.4] - 2026-10-19

- Keep baked ground-cover albedo visible when `terrain.runtime.material_color`
  is set: tint the dynamic instance that carries the terrain textures instead
  of parenting a second instance to it. Maps built with the ground-cover bake
  (which writes a white tint) showed only the material's default speckle.
- Keep nights dark in the independent world: lower the environment controller's
  night sky-light intensity from its stock 9 to 0.5. The stock value offsets a
  captured night sky on cooked maps; with the static daylight cubemap it made
  nights brighter than noon.

## [1.24.3] - 2026-10-19

- Adapt the guarded native bridges to demo build 26040817: hubs, staff,
  skiability, geographic names, CPU snow and building terrain pads. Keep the
  previous reviewed profiles and exact terrain-pad code fingerprints.
- Resolve legacy trail-marker variants against the native variants available
  on each build. Preserve Beginner/Intermediate/Expert maps and old native
  saves after the game's rename to GreenCircle/BlueSquare/BlackDiamond.
- Cover migration of retained community and featured catalogue URLs from
  skieomap.emillon.fr to skieomod.emillon.fr. This fixes catalogue refresh for
  installations still running 1.23.0 when they update the loader.

## [1.24.2] - 2026-10-18

- Re-register native terrain pads after source terrain and saved placeables
  reach their final transforms. Prevent restored pads from pushing the snow
  surface over buildings while preserving the saved snowpack and native
  sculpt layers. Refresh pads after correcting a player-built building too.
- Run the matching native cleanup before reconstruction so temporary terrain
  pads and placement blockers stay stable across repeated calls.
- Guard pad registration with reflected placement fields and exact native
  code fingerprints for builds 25996759 and 26019240.
- Refresh the native skiability memo across terrain/snow readbacks so restored
  pad work does not leave lifts reporting an obsolete lack of snow.
- Count live world actors in compatibility snapshots, excluding destroyed
  UObject shells without relaxing object identity or position checks.
- Detect an already running Steam client even when its startup marker has
  scrolled beyond the last 64 KiB of its log.
- Correct the earlier interpretation of black hub outlines: a native color
  diagnostic identifies them as hub rings, rather than broken snow materials.
- Qualify demo build 26019240 with 45 passing checks, both strict native save
  roundtrips, active rendering, snow-depth cycles and repeated pad rebuilding.

## [1.24.1] - 2026-10-18

- Add reviewed native profiles for Steam demo build 26019240, retaining the
  previous signatures and structure guards for older builds.
- Preserve empty furniture labels and saved lift origins when restoring a
  custom map. Keep grounded lift components at their world transforms.
- Record the updated asset inventory and initial compatibility results.
  Qualification failed on the restored snow surface and a destroyed-actor
  counting artifact; the black hub outlines were subsequently identified
  as native colors (see 1.24.2).

## [1.24.0] - 2026-10-18

- Publish the project source on GitHub under BSD-3-Clause, with separate third-party notices.
- Use skieomod.emillon.fr by default and prepare permanent redirects from skieomap.emillon.fr.
- Replace the browser workshop catalogue with the mod presentation, installation guide and tutorials.
- Restore web publication as the default `skieomod publish` destination; retain explicit Steam preparation/publication options.
- Browse every published web map in the game, alongside Featured and local maps, with source filters and text search.
- Preserve offline playback, separate package versions, optional updates and cached catalogues.

## [1.23.0] - 2026-10-17

- Resolve native trail rating functions by unique code shapes and checked
  cross-references, allowing code, constants, jump tables and the transient
  style cache to move independently. Reject ambiguity, changed instructions,
  invalid targets and invalid native default thresholds. Check hook ownership
  and referenced memory again before each configuration update.
- Resolve slope, style and custom-color capabilities independently. Add
  `game:get_trail_rating_capabilities` for map authors to choose a fallback.
- Check reflected terrain, Landscape, placement and save-session anchors
  before private access and before clearing pending requests or world travel.
  Check height-function parameter types and order before installing hooks.
- Isolate optional startup/hook failures, retain callbacks, and report feature
  availability with UE4SS command `custommap_compatibility`.
- Exercise independently relocated executables, changed/ambiguous native
  profiles, reflected layout drift and optional-hook failures in regression.

## [1.22.0] - 2026-10-17

- Add optional per-difficulty `colors` to `game:set_trail_rating_system`:
  opaque sRGB `#RRGGBB` values for beginner, intermediate, expert and extreme.
  Partial palettes fall back to the selected native style; symbols and slope
  thresholds remain independent. Reset and map shutdown restore native colors.
- Apply custom colors through the guarded native color getter, including C++
  callers; reject invalid palettes and mismatched helper job versions.

## [1.21.0] - 2026-10-17

- Add map API `game:set_trail_rating_system` and `get_trail_rating_system`.
  Maps can choose the European, North American or Japanese native palette and
  two or three slope thresholds, in degrees or percent grade.
- Apply custom thresholds to the native classifier, including C++ callers.
  Preserve assigned trail ratings and native snow/obstacle effects. Restore
  the original classifier and palette at map shutdown without changing player
  preferences. Reject unmatched native signatures before modifying the game.
- Accept `trail_rating_system` in Lua scenario configuration;
  ship the native helper and MinHook license in loader and tool distributions.

## [1.20.14] - 2026-10-17

- Add an Editor button in New Game > Custom Map to open the desktop map editor
  using its normal startup preference, including on Linux/Proton.
- Register the editor-only skieomod://editor link during setup and updates.
  Opening the editor never installs a package or starts a map.
- Include the game build 25996759 loading fixes prepared in 1.20.13 below.
- Known qualification limits on build 25996759: black hub outlines, native
  furniture labels filled in after reload, and lift actor-origin Z changes below
  40 cm. Native save/reload preserves calendar, finances, scenario and snow.

## [1.20.13] - 2026-10-17

- Restore game build 25996759 support for resort hub registration and rebuilds,
  geographic hub names, the hiring pool and the relocated skiability memo.
  Preserve inspected older profiles and reject unmatched native signatures.
- Read the current CPU snow cache using its 56-byte tile entries and moved
  readiness flag; retain the earlier cache layout for supported executables.
- Remove the deleted String Lights class from both placeable catalogues.
- Re-register restored hub sources after aligning saved buildings and lifts,
  and hold the native time multiplier during saved-world reconstruction.
- Add a reproducible game compatibility protocol with PE/native guards, cooked
  asset deltas, UE4SS reflection/map/GC checks and native save/reload evidence.
  Proton tests use a dedicated prefix and verify a unique marker in the game's
  actual save directory, which ignores Unreal's UserDir option.

## [1.20.12] - 2026-10-16

- Restore custom map loading on game build 25970577: update the terrain renderer,
  navigation, resort hubs, geographic names, hiring pool and skiability profiles.
  Retain previously verified layouts and native signature and ownership checks.
- Retain cooked classes and their default objects during UE4SS catalogue export
  to prevent the native crash reproduced during repeated content inspection.
- Refresh the placeable catalogue and support native decoration variants in
  scenes and object overrides, including the unified trail marker class.
- Ground small decorations against the visible terrain and snow shell so
  decimated slopes do not bury benches and tables below the rendered surface.
- Update Veymont to 0.7.7 with 54 furnishings and Super Saint-Bernard to 0.2.4
  with 14 furnishings. New games receive difficulty markers, ski racks, benches
  and tables around existing anchors; Veymont also receives two planters.
  Preserve saved layouts and exclude decoration from scenario installation wear.
- Known issue on build 25970577: some trail ribbons render black on snow.
  Map loading and the new furnishings were validated with UE4SS.

## [1.20.11] - 2026-10-14

- Rename `skieomod uninstall` to `skieomod uninstall-self` to distinguish
  removal of Custom Map and its tools from Workshop item installation.
  The previous `uninstall` command is no longer accepted.

## Documentation updates on 13 October 2026

- Publish the [graphical map tutorial](https://skieomod.emillon.fr/tutorials/editor/):
  start from the base terrain or import a heightmap, sculpt, add trees, place a
  resort, then Build, Test and Play. Includes six real editor captures and an
  editable Alpine Valley source project.

## [1.20.10] - 2026-10-14

- Add command **skieomod uninstall** to remove the mod and command.

## [1.20.9] - 2026-10-13

- Keep Featured map cards usable when location metadata contains only a place
  label. Show a world-map marker only for valid coordinates or normalized UVs.

## [1.20.8]

- Add Help → Mapmod tutorial to the editor, linking the illustrated guide and
  downloadable practice projects.

## [1.20.7]

- Add the illustrated mapmod tutorial and offline guide, with a reusable Lua
  exercise, the animated fox example and separate versioned dependencies.
- Link the guide from newly created mapmod projects.
- Correct loading-screen thumbnail sizing.

## [1.20.6]

- Consume F7, click and Escape input through a retained game-thread dispatcher,
  avoiding callback registry changes while animated map entities are running.
- Preserve map-owned input cleanup and save-state synchronization.

## [1.20.5]

- Start fully installed Featured maps and dependencies offline, including during
  catalogue refresh. Refreshes and updates are explicit menu actions.
- Download and verify missing dependencies inside the loading screen.
- Add mesh-based entity selection and a small inspection card, with F7 camera focus.
- Extend animated snow textures, native weather sampling and the fox example.

## [1.20.4]

- Crossfade animated clips, including interrupted transitions, eye groups,
  ground-rig anchors and snow coats.
- Support a simulation-owned transition clock and configurable blend duration.

## [1.20.3]

- Sample nearby guests, workers and operating lifts for mapmod disturbance reactions.
- Refine animated ground adaptation and preserve full floating-point precision
  in saved JSON state.

## [1.20.2]

- Add ground rigs, leg adaptation, model-shaped paw contacts and native snow
  crunch audio for portable animated entities.
- Expose fresh and packed snow depths, and silence contact audio during pause.

## [1.20.1]

- Add map-owned frame callbacks, loading readiness and real elapsed seconds.
- Extend animated placement, pitch/roll, snow coats and textured footprints.
- Respect time, menu and world pause in the animated fox example.

## [1.20.0]

- Introduce portable animated map entities and the reusable Forest foxes mapmod.
- Resolve versioned Featured dependencies separately from their maps.
- Extend visual trigger authoring and scenario documentation.

## [1.19.3]

- Refine starting resort staff restoration and the scenario interface.
- Include the visual scripts tutorial and first-season practice scenario.

## [1.19.2]

- Extend scenario testing and runtime integration, including scenario QA helpers.

## [1.19.1]

- Refine scenario presentation and custom terrain/scenery integration.

## [1.19.0]

- Add map-defined resort properties, operating commands and scenario integration.
- Support shared Lua modules for resort rules, staff and saved scenario state.

## [1.18.0]

- Expand Featured catalogue presentation and versioned release publication.
- Keep map downloads separate from the tools and loader distributions.

## [1.17.2]

- Start Steam before an editor test when needed and wait for its initialization.
- Clean up failed editor test processes and pending launch requests.

## [1.17.1]

- Automate release preparation, isolated distribution checks, SSH publication
  and public HTTPS verification.

## [1.17.0]

- Use the installed Proton compatibility tool for Linux editor tests.
- Record tested Steam game revisions and check for loader updates in the background.

## Earlier milestones

- **1.14–1.16:** introduce and expand the native Qt/OpenGL workshop, including
  terrain editing, resources, object defaults, placement and per-instance properties.
- **1.12:** infer square raw heightmap dimensions and offer a relative test altitude range.
- **1.11:** build forests from editable JSON and bake erosion and vegetation.
- **1.10:** build directly from R16/RAW or 16-bit grayscale PNG sources.
- **1.9.1:** retain the tested UE4SS archive on the project server for reliable setup.
- **1.9:** support the tested game update and improve failed-load recovery.
- **1.3:** align project metadata and the in-game catalogue with the Workshop contract.
- **1.2:** add source project templates and the local build/run workflow.
- **1.1:** rename the CLI to skieomod and add automatic setup and play links.
- **1.0:** introduce the Custom Map repository, CLI and Steam community integration.
