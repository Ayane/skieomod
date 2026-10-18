# Scripts and scenarios with skieomod

Start with **Visual graph** in the workshop's **Triggers** window. The
[illustrated tutorial](https://skieomod.emillon.fr/tutorials/scripts/) includes
actual Qt captures, optional Lua equivalents and a downloadable first-season
source project. This guide also ships with the tools for offline reference.

The graph configuration action described here requires the workshop build
containing **Configure scenario** and **Register before project script**.
The game's scenario APIs require Custom Map 1.19.3 or newer.

## Open the source

```sh
skieomod editor my-mountain
```

Open a folder containing `custom-map.json`, rather than a Featured installation's
playable `.skieomap`. In this repository, Super Saint-Bernard's source is
`mod/SkiEO-SuperSaintBernard`. Copy it before experimenting. You can also create
your own source with **New**, import/sculpt terrain, then **Save**.

The practice project is available from the tutorial, or at
`repository/web/public/tutorials/scripts/files/first-season-project.zip` in a
checkout. Extract it and open the `first-season` folder. It contains generated
terrain, starting-economy and April-reminder graphs, and a complete objective
evaluator in `Scripts/main.lua`.

## A first trigger

1. Click **Triggers → New trigger**. Set a name, keep **Enabled** checked and
   choose `map.ready` and **Visual graph**.
2. The default graph connects **Event.then → Print message.in** and
   **Text.value → Print message.message**.
3. Select Text and edit its **Value** in the inspector.
4. **Apply to project → Close → Save → Build → Test → Play**.

Print message writes to the UE4SS log. White connections execute actions;
coloured connections supply numbers, text, booleans or event data. Data alone
does not execute an action. Add nodes with **Add node…** or right-click, and
connect outputs to compatible inputs. Every data input needs a connection.
Constants have their own values; action inputs do not have inline defaults.

For the equivalent **Lua** trigger, keep event `map.ready` and enter only:

```lua
api:log('My first scenario is ready.')
```

The trigger editor creates the event callback. Do not nest an `api:on` wrapper
inside a Lua trigger. Project initialization, in contrast, edits the entire
original script and its registration function.

## The actual Super Saint-Bernard graph

![Super Saint-Bernard's starting economy in the Qt Trigger Editor](https://skieomod.emillon.fr/tutorials/scripts/images/starting-economy.png)

Select **Starting economy · 2003**. Its event is `map.ready` and it connects:

| Output | Input | Value |
| --- | --- | --- |
| Event.then | Configure scenario.in | Execution |
| Text.value | Configure scenario.currency | `CHF` |
| Number.value | Configure scenario.start_year | `2003` |
| Number.value | Configure scenario.starting_balance | `250000` |
| Number.value | Configure scenario.ticket_price | `38` |

**Register before project script** registers this handler before the original
script registers its own handlers. It still waits for its selected event.
This gives the original resort creation and first calendar snapshot the correct
configuration. Other triggers retain their usual registration order by default.

Select the action to inspect **Rules module**. Super Saint-Bernard uses
`economy`, backed by `Scripts/economy.lua`, which retains its construction costs,
loans and lift tracking. Leave this field empty for a basic new scenario.
A module name is a local Lua file basename without `.lua`; declare the file
and its dependencies in `content.assets` and use script API `1.1`.

Changing the 250000 Number to 300000 gives a fresh test more starting cash.
Configuration occurs once per session. Remove an older handwritten
`api.game:configure` call when moving it into the graph.

Starting cash and ticket price are applied only on a new game; loading a save
preserves its current economy. The historical `start_year` is used by
`api.game:snapshot()`. The native date and money symbol stay visible. In Super
Saint-Bernard, native Year 1 represents the 2003–2004 season.

The equivalent Lua trigger is retained in the actual JSON source:

```lua
local rules = require('economy')
api.game:configure({
    currency = 'CHF', start_year = 2003,
    starting_balance = 250000, ticket_price = 38,
    costs = rules.costs, class_costs = rules.class_costs,
    loans = rules.loans, track_lift_rides = rules.track_lift_rides
})
```

Only the selected mode is compiled. Graph and Lua sources are retained
separately; editing one does not translate or update the other.

## A seasonal condition

Choose `calendar.month_changed`. Connect Event.then to Branch.in. Add Event
value with Key `month` and Fallback `0`, Number `4`, and Compare with Operator
`==`. Connect the two values to Compare.a and Compare.b, then Compare.value to
Branch.condition. Connect Branch.true to Print message.in, with a Text supplying
its message. Leave Branch.false unconnected.

![An April reminder with a comparison and branch](https://skieomod.emillon.fr/tutorials/scripts/images/april-condition.png)

Months run from January = 1 to December = 12. This reminder goes to the log;
it is an exercise, separate from the actual scenario's financial rules.
Its Lua trigger body is:

```lua
if (event.month or 0) == 4 then
    api:log('April: check your cash reserve.')
end
```

`calendar.year_changed` supplies a native year counter. For historical years,
use `api.game:snapshot()` in Lua. Delay receives seconds, not calendar months.
Add funds changes cash without recording scenario revenue. A one-time payment
needs saved state to prevent duplicate awards after loading a save or in another
year; Super Saint-Bernard keeps that grant evaluator in Lua.

## Briefing, objectives and an ending

The practice project demonstrates a complete simple scenario: reach April 2004
with at least 100000 CHF left; a negative balance fails immediately. Use the
graph for its starting settings and simple event actions. The native objective
panel, persistent state and victory/failure evaluator currently use Lua, supplied
by the starter so beginners can reuse them.

**Project initialization • Lua** exposes the full source script. Edit its title,
briefing, deadline, minimum reserve and labels together. Keep the graph's year at
2003 until you also adjust the evaluator's April 2004 deadline. On a blank map,
you can paste the complete `first-season.lua` from the tutorial into project
initialization and recreate the starting-economy graph. Merge registrations when
the existing script already has terrain, forest or other handlers.

The initializer returns a function receiving `api`. `api:state(defaults)` gives
it a restored, JSON-compatible state table. `api:scenario` registers the title,
briefing, goal, deadline, one to four objectives and a status callback. Objective
progress returns `{value = 'display text', fraction = 0..1}`. Status returns
`active`, `completed` or `failed`.

The complete starter checks `api.game:snapshot()` on `map.ready` and every
1000 ms, updates its saved balance/calendar and determines the outcome. Terminal
results remain terminal. Native manual saves and autosaves retain the state for
a declared scenario. Keep state under 32 KiB and store no functions or Unreal
objects in it; panel callbacks are reconstructed by the script.

For a larger example, Super Saint-Bernard retains detailed maintenance,
concessions, weather, grants and outcomes in `Scripts/main.lua` and
`Scripts/survival.lua`. Its starting economy is now compiled from the graph.

## Build and verify

```sh
skieomod build my-mountain
skieomod test my-mountain --check-scripts
skieomod run my-mountain
```

Build compiles the enabled triggers and validates typed links, required inputs
and cycles. `--check-scripts` requires Lua 5.4 / `luac`; omit the option if the
compiler is unavailable. It checks syntax, not scenario behaviour. Test a fresh start, both outcomes, pause/calendar behaviour,
and a save/reload after spending money and after reaching a terminal result.

The source manifest keeps its original script entry. Merge this setting into
its existing `build` object:

```json
"triggers": {"file": "Triggers/triggers.json"}
```

Build writes `Scripts/skieomod-generated-authoring.lua` in the package and uses
it as the packaged entry. The source manifest keeps `Scripts/main.lua`. Edit the
original source files and rebuild. Use `build`, rather than raw `pack`, to compile
the graph before producing a playable archive.

See also the [editor guide](editor.md) and [API specification](custom-map-format.md).
