# SkiEO Custom Maps changelog

Release notes for the skieomod tools and Custom Map game loader. Maps and mapmods
have their own package versions. Download the
[latest tools](https://skieomod.emillon.fr/downloads/CustomMap-Tools.zip) and
[latest loader](https://skieomod.emillon.fr/downloads/CustomMap-Mod.zip).

## [Unreleased]

## [1.28.0] - 2026-10-25

- Narrow Veymont's surface-lift service corridors to 5 metres and move them
  clear of the pylons; bound the snow-clearing blade to the corridor.
- Release surface-lift passengers when a line stops and send them downhill
  on native service routes, with optional shorter authored emergency exits.
- Hold native snowcats and new grooming requests until evacuated skiers clear
  the corridor, including jobs already in progress; preserve evacuation in saves.
- Add groomed emergency exits at both Pré Levé bends (P6 to Les Bouquetins,
  P9 to Les Tétras) and from Pierre Blanche to Marmottes.
- Restore detachable hanger positions when changed snow alters the station rail
  length, including saves made before this update.
- Document service geometry and emergency-route configuration in the tutorial.

## [1.27.0] - 2026-10-25

- Let maps override surface-lift models and palettes per installation and per
  numbered pylon, using their own declared assets and the original shared mapmod.
- Cache model variants and palettes before attaching lifts, validate overrides,
  and retain the shared 128-carrier rendering pool across different appearances.
- Finish native terrain alignment before adapting a lift so deferred grounding
  cannot rebuild its chairlift geometry over the towing route.
- Update the tutorial with the new configuration and a two-lift practice map
  demonstrating custom stations, poles, pylons and pulleys without a mapmod fork.

## [1.26.2] - 2026-10-25

- Extend the Surface lift tutorial with custom model authoring: Blender export,
  asset declarations, model slots, fork configuration and publication.

## [1.26.1] - 2026-10-25

- Distribute the Linux installer directly as a standalone shell script instead
  of a ZIP with a desktop launcher. Update download links and launch instructions.

## [1.26.0] - 2026-10-25

- Add the Surface lift tutorial to the editor Help menu and website, with
  an editable practice map, separate mapmod sources, route examples and save checks.
- Publish standalone Windows and Linux installers that reuse or install
  Python and pipx, install the current tools and run game setup. Include a
  Linux desktop launcher and preserve executable permissions in its ZIP.
- Test installer isolation, error handling and source downloads, and exercise
  the standalone launchers on Windows and Linux before automatic publication.

## [1.25.1] - 2026-10-25

- Use native Windows certificate validation for setup, updates and web
  publication, and explain certificate failures with actionable diagnostics.
- Clear portable forest instances when native construction and clearing tools
  record cleared zones. Restore existing clearings from native saves and bound
  spatial queries and render updates across frames.

## [1.25.0] - 2026-10-25

- Apply Veymont's green, blue, red and black trail colors through the map API;
  distinguish intermediate OSM pistes from easy runs and face the resort with
  the native camera component when starting a new game.
- Keep surface-lift hangers in front of their passengers after camera cuts and
  delayed boarding discovery; retain the same guest/carrier association.
- Reduce surface-lift frame work with cached rider discovery, exact sparse
  route projection, incremental snow profiles, nearby poses/wheels/stocks and
  one small, rate-limited snow contact view. Use an English mapmod display name.
- Stop surface lifts for excess snow as well as bare sections, preserve manual speed intent, and register ascent maintenance corridors for native snowcats. Only actual blade passages remove surplus snow; complete-route measurements control reopening.
- Keep ordinary Poma guide pulleys vertical, refine the snowboard towing grip, and render moving cables without snow accumulation or broken seams.

- Add the portable Surface Lifts mapmod with original Blender models, native
  standing passengers, terrain/snow-following transport, queues and save identities.
- Model Veymont's eight platter lifts, including Pré Levé's covered station and
  route bends; use the two-seat native chairlift for Blanchon in new games.
- Guard the surface-lift cable caches against the exact reviewed game build
  26143813 and 26178224, reflected layout changes and inconsistent native boarding markers.
- Add native equipped towing poses, ski imprints, circulating TKD stocks,
  spatial motor/impact sounds and full-route snow closure with manual speed intent.
- Plant each native ski on the rendered snow using leg IK and bounded depth
  readbacks; place the disc behind the thighs and the bent shaft below the crotch.
- Separate sliding TKD parts with spring return from rigid TKF poles; preserve
  sleeve, clamp and disc dimensions while the rider follows the terrain.
- Give the return cable its own elevated supports and route over low pylons;
  connect grooved, inclined drive wheels with tangent entry and exit sheaves.
- Keep unloaded poles upright, discs perpendicular to their shafts, and fit
  snowboard towing poses to the native rigid board and its two bindings.
- Update UE4SS to 1181 to fix the retained Lua output tables that caused memory
  growth during transform queries; back up the known affected 1152 DLL on setup.
- Confine Linux compatibility runs to a separate cgroup capped at 12 GiB or less; refuse reused
  Proton prefixes and record process memory before a runaway test can exhaust the host.

- Mirror paired platter lifts, declare each line’s ascent side, and keep Blanchon’s uphill chairs on the right.
- Separate rotating pulley rims from static bearings and motors; align tower rollers with a smooth cable tangent and keep station frames outside the wheel sweep.
- Put the TKD spring casing below its slim sliding rod and retain each hanger through the guide and FIFO stock; dispatch only on boarding with minimum cable separation.

- Add the editor map tutorial to the workshop's Help menu and packaged guides.
- Include this changelog in the tools and publish a versioned copy with each release.
- Prepare optional Discord release announcements after HTTPS publication checks,
  with a preview mode and receipts for confirmed messages.

## [1.24.11] - 2026-10-22

- Support Steam demo build 26143813, including the native layout changes
  introduced in 26141846: building/lift registration, expanded hub member
  records, staff RNG and navigation state.
- Select hub diagnostic layouts by their reviewed profile: the new build keeps
  the same batching counter while growing its member records again.
- Retain strict native fingerprints, automatic relocation for unchanged code
  and all existing terrain, snow and save compatibility checks. The subsequent
  26143813 update relocates these bridges automatically without another DLL change.

## [1.24.10] - 2026-10-22

- Support Steam demo build 26119568. Adapt the revised hub member layout and
  batching counter, larger staff candidate records and navigation state.
- Review the recompiled building/lift registration and skiability code; retain
  strict native fingerprints and automatic relocation for unchanged layouts.
- Keep native hub diagnostics aligned with the compact member records and
  pair the new navigation counter with its matching terrain-change handler.

## [1.24.9] - 2026-10-21

- Support Steam demo build 26111862 after reviewing the native bridges and
  their private layouts against build 26097896.
- Find relocated native functions automatically when their reviewed code is
  unchanged apart from address operands. Require a unique executable match,
  preserve instruction and field-offset checks, and verify the deferred hub
  wrapper's destination. Address-only game updates no longer require new
  hard-coded addresses for these bridges.
- Share the relocation fingerprints between the Windows helper and the
  compatibility preflight. Keep the warning for game builds that have not
  completed qualification, and refuse changed or ambiguous native layouts.

## [1.24.8] - 2026-10-21

- Use the rendered terrain surface for native height, snow and brush caches,
  as well as height queries and trail geometry. Previously, omitted source
  details could leave guests below the visible snow or above the ground on
  custom maps. Keep the original map data and the existing rendering density.
- Match refined cliffs and stitched section edges in native sampling; validate
  the complete terrain job before changing the live cache.
- Refine the snow mesh around buildings and lift stations so native terrain
  pads no longer stretch across large triangles and bury nearby furniture or
  visitors. Preserve the original base surface and bound the added geometry.

## [1.24.7] - 2026-10-21

- Support Steam demo build 26097896, including the revised lift registration,
  hub batching counter and larger native staff candidate records. Retain strict
  entry-point guards and complete terrain-pad fingerprints.
- Automatically check for newer official mod releases from the unsupported-game
  warning while at the main menu. Download and verify the
  release automatically, then offer **Restart game** to install and relaunch.
  Normal exit installs without relaunching; files remain untouched while playing.
- Back up changed code, preserve maps/settings/saves, reject altered downloads
  and recover an interrupted installation before gameplay hooks are loaded.
- Avoid polling warning widgets before the Custom Map browser is constructed.
  Populate progress text and layout before showing the warning or restart button.

## [1.24.6] - 2026-10-20

- Support Steam demo build 26071000 after reviewing the relocated native
  bridges for hubs, staff, skiability, geographic names, snow and terrain pads.
  Retain earlier profiles and exact code guards.
- Show a warning above Custom Map when the running executable does not match
  a qualified build. Check its SHA-256 once in the background, including offline;
  an unavailable check remains explicitly unverified.
- Keep the warning hidden during construction and prepare its text and layout
  before showing it, avoiding a briefly empty panel above the browser.

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
