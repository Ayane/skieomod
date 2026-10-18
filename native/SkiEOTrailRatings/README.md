# Map-scoped trail ratings

`trail_ratings.c` exposes a bounded Lua file callback for palette and slope
classification changes. The native palette uses the game's transient effective
style cache; it never changes `GameUserSettings` or writes preferences.
Optional per-grade opaque `#RRGGBB` colors are decoded as sRGB and converted
to native linear RGBA. A second detour changes `GetDifficultyColor`, including
its C++ callers. Unspecified grades and special native values use its retained
original trampoline; symbols keep the selected style.
The classifier detour changes the real native function, including its C++ callers,
rather than only the reflected Blueprint wrapper. Existing player-assigned trail
ratings and physical snow/obstacle checks remain native.

The reviewed code shapes come from demo build **25996759**. The portable
`rating_resolver.h` scans readable executable sections for unique, aligned
functions. Only address operands are masked. It validates the classifier's
three finite, ordered native angle literals, the palette's three references to
one writable style byte, and the color getter's direct call, image base, seven
jump-table targets and native white fallback. Functions, constants, the table
and cache can move independently. Padding and unrelated functions are ignored.
Unknown shapes, ambiguous candidates and inconsistent references are refused.
Slope and palette capabilities resolve independently; colors require the checked
palette they call. The read-only Python counterpart in
`tools/trail_rating_profile.py` uses the same fixtures as the production C
resolver. The compatibility contract fingerprints both implementations.

Resolved code, table entries and constants are captured and checked again before
updates, excluding only this helper's owned detour bytes. Optional read-only
export `skieo_trail_ratings_capabilities` writes a bounded JSON report and never
creates a hook or changes game settings. A successfully resolved shape is not
full qualification of a game build.

Enable/disable uses the vendored [MinHook 1.3.4](https://github.com/TsudaKageyu/minhook/releases/tag/v1.3.4),
which suspends peer threads and relocates their instruction pointers when
switching the hook. Configuration reads and updates use an SRW lock. The detour
and policy memory remain valid for calls already running during map cleanup.
Only the classifier and color getter entry points are redirected; shared `.rdata` constants stay
unchanged. Cleanup restores the original native implementation and palette.

The bounded job ABI is version 2 (52 bytes): the version 1 fields followed by a
four-bit color override mask and four packed `0xRRGGBB` values. The native helper
independently validates the mask, unused fields, thresholds and disabled jobs.
Old/mismatched Lua/helper ABI pairs are rejected before any game mutation.

```sh
sh native/SkiEOTrailRatings/build.sh
```

MinHook sources are retained verbatim from tag `v1.3.4`; the unused 32-bit decoder
is omitted. Its upstream BSD license is included in `vendor/minhook/LICENSE.txt`
and shipped with the loader as `LICENSE-MINHOOK.md`.
