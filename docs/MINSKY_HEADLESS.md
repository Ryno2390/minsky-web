# Driving Minsky headlessly — what the engine actually exposes

Scoping investigation, 2026-08-14, for the modern-front-end project. Every claim below was
executed, not read off documentation.

## The headline: this is "modern UI over a complete engine", not "UI plus an authoring layer"

The engine can be fully driven with no GUI: construct models from nothing, wire them, build
Godley tables, configure the solver, simulate, read values, save and reload. Scope for the
front-end project is therefore favourable — we are replacing a shell, not reimplementing
stock-flow consistency.

## `minsky-RESTService` is NOT an HTTP server

Despite the name, it is a **stdin/stdout line-oriented REPL** (`RESTService/RESTService.cc`,
`main` reads `getline(cin)`). Commands are REST-*shaped* paths over a command registry:

    /minsky/canvas/addVariable ["y","flow"]
    /minsky/canvas/addVariable=>null

There is no network layer, no HTTP, no sockets. A web front end must supply its own server.
`-batch` disables readline for piped input.

## Two routes, and Python is the better one

`pyminsky` binds the **same registry** in-process, with Pythonic access. Prefer it — no
subprocess, no JSON-over-pipe parsing, no output-format scraping.

    from pyminsky import minsky
    minsky.load('examples/GoodwinLinear02.mky')
    minsky.epsRel(1e-8); minsky.implicit(True); minsky.order(4)
    minsky.reset()
    minsky.variableValues[':K'].value()      # 300.0
    minsky.step()

## Registry surface

`/list` reports **682 endpoints**, but the registry is **reflective and `/list` is
incomplete** — `/minsky/model/items/@elem/0/classType` resolves fine while never appearing
in the listing. Do not treat `/list` as the API contract.

    canvas 281 | databaseIngestor 61 | variablePane 55 | equationDisplay 40
    phillipsDiagram 39 | fontSampler 35

**Authoring:** addVariable, addOperation, addGodley, addPlot, addRavel, addGroup, addLock,
addSwitch, addNote, copyItem, deleteItem, renameItem, deleteWire.
**Solver:** epsAbs, epsRel, implicit, order, nSteps, stepMin, stepMax, t0, tmax, reset,
step, running, simulationDelay.
**IO:** load, save, exportSchema, importVensim, exportAllPlotsAsCSV, databaseIngestor/*.

Note the solver knobs are all exposed, so a front end can **fix the original instability
complaint by shipping sane defaults** — Minsky's own default `epsRel` is 1e-2.

## Godley tables construct headlessly

    minsky.canvas.addGodley()
    t = minsky.canvas.itemFocus.table
    t.resize(3,3)
    t.setCell(0,1,'Assets:Reserves'); t.setCell(0,2,'Liabilities:Deposits')
    t.setCell(1,0,'Lend'); t.setCell(1,1,'loan'); t.setCell(1,2,'loan')
    t.assetClass(1)   # 'asset'   -- inferred from the "Assets:" prefix
    t.assetClass(2)   # 'liability'

Survives a save/load round-trip with cells and classes intact.

## THREE GOTCHAS, each of which silently produces a wrong result

### 1. Port coordinates are stale until `updateBoundingBox()`

The single most expensive trap found. Straight after `moveTo(100,100)`, `portX(0)` returns
**100.0** — the item centre, not the port. Wiring at that coordinate **silently does
nothing**: no exception, no wire, `len(model.wires)` stays 0.

    for i in range(len(items)): items[i].updateBoundingBox()
    items[0].portX(0)      # now 112.0, the actual port

`canvas.requestRedraw()` and `renderCanvasToSVG()` also trigger it. The REPL path hides the
bug entirely because rendering item icons updates the boxes as a side effect — which is why
the same script works over the pipe and fails from Python.

### 2. Wiring is GEOMETRIC, not logical

There is no usable `wire(fromItem, fromPort, toItem, toPort)`. `Group::addWire` exists in
`model/group.h` but `/minsky/model/addWire` accepts JSON, returns `{}`, and creates nothing.
The only working route is synthesising canvas mouse events at port pixel coordinates:

    minsky.canvas.mouseDown(items[0].portX(0), items[0].portY(0))
    minsky.canvas.mouseUp(items[1].portX(1), items[1].portY(1))

**This is the main piece of glue the project needs**: a logical wiring API over the
geometric one, or an upstream patch exposing `addWire` properly. It is also a design
constraint — layout and connectivity are coupled in the engine.

### 3. Container returns are C++ wrappers, not Python lists

`table.getData()` returns a `CppWrapperType`, not a list — subscripting it as a list raises
`TypeError: 'NoneType' object is not subscriptable` in some paths. `dir()` on these objects
reports only `contains/erase/insert/keys` regardless of the real methods, which resolve
dynamically at call time. Use `len(x)`, `x[i]`, and typed accessors (`getCell(r,c)`).

## Smaller notes

- Headless runs emit `librsvg-CRITICAL ... is_rsvg_handle(handle) failed` on stderr. Cosmetic
  (icon rendering without a surface); filter it, do not chase it.
- A failed `reset()` does **not** reliably prevent `step()`. A model with a valid wired
  subgraph plus one broken item threw on reset but stepped anyway with `t` advancing. A
  genuinely unwired model does refuse to step. **A front end must check reset succeeded
  before enabling run**, rather than trusting that step will fail.
- `variableValues` keys are `:name` for globals and `<id>:name` for scoped ones.

## Build location

The build now lives at **`~/minsky`** (1.4G, includes the 192M of object files needed for
incremental rebuilds -- keep them, we will likely want to patch `addWire` upstream).
`minskyweb/session.py` probes `MINSKY_HOME`, then `~/minsky`, then the Ravel app bundle.

The scratchpad path was **removed from the probe order**, not just demoted: it still
contains a `pyminsky.so`, so leaving it ahead of `~/minsky` meant a stale ephemeral copy
silently shadowed the real build. `load_minsky()` now resolves to `~/minsky`.

## `minskyweb/headless.py` -- the logical layer over all of the above

Wraps the three traps so they cannot bite:

    from minskyweb.headless import Model
    m = Model()
    r   = m.parameter('r', 0.10)
    mul = m.operation('multiply')
    itg = m.operation('integrate')
    m.wire(r, mul, 1); m.wire(mul, itg, 1); m.wire(itg, mul, 2)   # feedback loop
    m.set_init('int1', 1.0)
    m.configure()      # epsRel 1e-8, implicit, order 4 -- not Minsky's 1e-2
    m.run(steps=200)

- **Every wire is verified** against the wire count and raises `WiringError` naming the
  likely cause. Silent no-ops are the failure mode this module exists to remove.
- `updateBoundingBox()` is called before any port coordinate is read, always.
- Items auto-place on a grid, because overlapping items mis-wire silently via hit-testing.
- `_adopt` **verifies the classType** of the item it takes ownership of. `addOperation`
  can create more than one item -- `integrate` creates a `Variable:integral` *and* an
  `IntOp` -- and the correct one to wire is the last, but that is checked rather than
  assumed.
- `reset()` re-raises with a warning that a failed reset does not stop `step()`.

`test_headless.py` covers it: exponential growth with a feedback loop and a 2-input
operation (2.9e-11 against the analytic solution), a linear ramp, all three wiring-error
paths, an out-of-band move that would leave port coordinates stale, and a save/load
round-trip that still integrates correctly (1.2e-11).

## `minskyweb/server.py` — the HTTP/WebSocket layer

    python3 -m minskyweb.server            # 127.0.0.1:8765
    python3 -c "from minskyweb.server import serve; serve(port=8791)"

    GET  /api/state     items + ports (with roles) + wires + values + solver
    POST /api/clear /api/item /api/wire /api/init /api/solver /api/reset
    POST /api/load /api/save
    WS   /ws/sim        {"cmd":"run","steps":N,"tmax":T} -> one frame per solver step
                        {"cmd":"stop"} to interrupt

### Three decisions, and why

**One engine per process.** `pyminsky` is a C++ singleton, so a second `Model()` silently
wipes the first — verified: creating `b` left `a` with zero items. `Model.__init__` now
raises unless `takeover=True`, and `Model.current()` returns the owner. **Multiple
documents need multiple PROCESSES**, a router in front, one per session. The server is
deliberately single-document rather than pretending otherwise.

**Every engine call is serialised behind an `RLock`,** and runs via `run_in_threadpool`.
FastAPI serves on a thread pool; two threads inside a stateful C++ singleton corrupts it.
The calls are also blocking, so they must not sit on the event loop.

**Simulation streams over a WebSocket, not polling.** Minsky chooses dt adaptively —
`step()` returns `[t, dt]` and dt moves with stiffness — so a polling client cannot know
when to ask. Streaming also gives a stop signal for a run that is diverging, which matters
when exploring unstable models is the point. Mutating endpoints return **409** while a run
streams.

### The non-finite trap

`json.dumps` raises `ValueError` on `inf`/`NaN`, and this engine produces both routinely:
**`tmax` is `Infinity` by default**, so `GET /api/state` 500'd on a *freshly cleared model*
before this was handled. A diverging model fills every variable with `inf` — meaning the
server would have failed exactly when the model did the interesting thing.

`jsonable()` maps non-finite to `null`; `nonfinite()` reports which keys went bad; the
snapshot carries a `diverged` list and the stream sends `{"done":true,"reason":"diverged"}`
and stops, because every frame after the first `inf` is noise.

### Engine behaviour worth knowing, both directions

- **A failed `reset()` does not reliably stop `step()`** — a model with a valid wired
  subgraph plus one broken item threw on reset and still advanced `t`.
- **A successful `reset()` does not mean `step()` works** — an unwired integral resets
  cleanly and then fails with `integral not wired` on the first step.

So neither call can be trusted as a validity check for the other. The stream reports step
failures per-frame rather than assuming a clean reset means a runnable model.

### Tests

`test_server.py` — 11 checks, all green. The model is built **entirely over HTTP** and
verified against `exp(rt)` (2.9e-11), so a server that wires the wrong ports fails loudly
instead of streaming plausible numbers. Also covers stop-mid-run, the three error paths,
and the 409 guard. `test_headless.py` — 12 checks covering the layer underneath.

Real-uvicorn smoke test confirmed separately: `dS/dt = c` built over curl, streamed over a
real WebSocket, `err = 2.7e-14`.

> Port 8765 was occupied by an unrelated Python process during testing, and uvicorn's bind
> failure surfaced as **404s from whatever else was listening** rather than as an obvious
> startup error. If routes 404, check `lsof -nP -iTCP:<port> -sTCP:LISTEN` before debugging
> the app.

## `minskyweb/ui/` — the browser front end

    python3 -m minskyweb.server        # then open http://127.0.0.1:8765

Single file, no build step, served by the same process. Palette on the left, SVG canvas
in the middle, simulation and solver on the right. Drag a node to move it, drag from a
blue output port to a grey input port to wire, Delete to remove, Run to stream.

Verified end-to-end in the browser: `dS/dt = rS` with `r = 0.35` built over the API,
run from the UI, reaching `int1 = 33.4441` at `t = 10.028` against
`exp(0.35 × 10.028) = 33.444`.

### Wire geometry has to be tracked, not read

`wire.coords()` returns a 4-element wrapper whose elements all read `None` from Python,
while the **same call over the JSON registry returns `[112,100,286.5,100]`**. `wire.from()`
and `.to()` expose no `x()`/`y()` either. So the binding cannot report where a wire is.

The server therefore records `(src_item, src_port, dst_item, dst_port)` as wires are made
and recomputes geometry from live port positions on every snapshot. That is better than
reading coordinates anyway — **coordinates go stale the moment an item is dragged**, port
positions do not. Wires follow dragged items for free.

Topology is maintained across delete (drop affected wires, shift higher indices) and clear.
For a file opened from disk there is no record, so `_recover_topology_from_file` reads the
coordinates once via the REST binary — the only route that marshals them — and matches them
against port positions to recover which ports each wire joins. If the record and the engine
ever disagree, the snapshot emits a `desync` entry rather than drawing a wrong picture.

### Node geometry: three attempts, and why the first two were wrong

Engine items are **small** — half-widths of 12 to 24px — and ports sit at engine
coordinates. Naively:

1. **Box sized to the label** puts the output port *inside the text*: "multiply" needs
   ~60px of box, the engine's item is 24px wide, so the port lands mid-word.
2. **Box sized to the ports** lets one item swallow another: the IntOp's output port sits
   **78px** to its right, so its box grew over the neighbouring variable.
3. **What works:** draw the node at the engine's own extent (capped at 30px half-width),
   put the label *beneath* it, and join any port outside the box with a short stub. Ports
   can never collide with text, and no item can balloon over another.

### Non-finite values, again

The plot skips `null` points rather than breaking, and the run stops on the first
non-finite frame with a `diverged` badge. Both rely on the server mapping `inf`/`NaN`
to `null` — without that the WebSocket frame itself fails to serialise.

### Not yet built

Godley table editing (the block can be created but not filled from the UI), zoom/pan,
undo, multi-select, renaming an existing item, and loading a file from a picker rather
than a path. Godley editing is the significant one — it is the feature that makes Minsky
worth keeping, and the engine already supports it headlessly (`resize`, `setCell`,
`getCell`, `assetClass`).

## Godley tables — semantics, measured

The double-entry block, and the reason Minsky is worth keeping. Everything below was
established against a shipped model (`examples/LoanableFunds.mky`) rather than guessed,
because four plausible-looking constructions all failed identically before the real
requirement surfaced.

    row 0     column headers. cell(0,0) is a label; cells 1.. are STOCK names, plain.
    row 1     initial conditions (`initialConditionRow(r)` reports which row).
    rows 2..  flows. Column 0 is the flow label; cells 1.. name flow VARIABLES.

**`assetClass(col, "asset"|"liability"|"equity")` is a SETTER, and the only thing that
sets the class.** An `Assets:` prefix on the header is inert text. An early test seemed
to show the prefix working — it did not; the columns simply happened to be in the order
the classes default to, and adding a third column exposed it.

**`rowSum(r)` returns a SYMBOLIC STRING** — `'0'` balanced, `'2Lend'` not — and raises on
row 0. The sum is assets − liabilities − equity, so a transfer between an asset and a
liability carries the **same** sign on both sides, while two liabilities carry opposite
signs. An unbalanced initial-conditions row usually means a missing equity column: the
shipped model's IC row sums to `'0'` only because `B_E` is there to absorb it.

### The trap: `icon.update()`

**After editing a table you must call the GodleyIcon's own `update()`**, or `reset()`
dies with `Invalid valueId: :<stock>` and the stock variables are never created.
`editor.update()` does not work — only `icon.update()`. This cost four failed
constructions that were each individually reasonable, and the error message points at
the stock name rather than at the missing call. `minskyweb.headless.Godley` calls it after
every mutation so it cannot be forgotten.

### A number in a flow cell balances but drives nothing

`5` in a flow cell parses, and the row sums to zero, and the model resets and runs — and
the stock never moves off its initial condition. Flow cells name flow *variables* whose
values come from the canvas. Verified: `rate=5` wired into flow variable `Lend` moves
Reserves 100 → 120.1 and Deposits 60 → 80.1 over t = 4.02, both exact to 1e-6.

### API

    GET  /api/godley/{i}                  cells, classes, rowSums, icRow, title
    POST /api/godley/{i}/cell             {row, col, value}
    POST /api/godley/{i}/class            {col, cls}
    POST /api/godley/{i}/resize           {rows, cols}
    POST /api/godley/{i}/row/{insert|delete}   {at}
    POST /api/godley/{i}/col/{insert|delete}   {at}

Double-click a Godley node on the canvas to open the editor. Columns carry an asset-class
selector with a colour-coded rule; the initial-conditions row is tinted; every row shows
its symbolic sum live, and the header badge reports how many rows are unbalanced. Row 0
and column 0 are protected — they hold the stock names and flow labels.

`test_server.py` section 7 covers it: build over HTTP, verify all rows balance, break a
row and confirm the imbalance surfaces as `'2Lend'`, check the four guard rails, then
drive the flow from the canvas and confirm both stocks integrate exactly.

## Opening files

    Open…  →  browse the model directories, filter, or upload a file from anywhere

    GET  /api/files          models under the allowed roots
    POST /api/load?path=…    load one of them
    POST /api/upload         multipart .mky, saved to the upload dir and loaded

**Wire topology is parsed from the .mky file, not read from the engine.** The binding
cannot report wire geometry, and a loaded file carries no record of how it was built.

Two approaches were tried. The first shelled out to the REST binary for wire COORDINATES
and matched them against port positions; it lost **14 of 83 wires on LoanableFunds**,
because coordinate matching needs a tolerance and ports sit close together. The second
matched items by `(type, x, y)` — and lost **48 of 131 items on EndogenousMoney**, because
**the engine nudges positions on load**, by up to 22px.

What works is order. The file's `<items>` is flat and lists every item including group
members; the engine hoists group members to the end, exactly as `_iter_items` yields them.
Applying the same reordering aligns the two exactly — verified 131/131 on EndogenousMoney
and 26/26 on GoodwinLinear02. Port ids in `<Wire><from>/<to>` then give exact topology with
no tolerance at all.

**All 37 shipped examples now load with exact topology**, asserted in `test_server.py`
section 8. Anything less shows as a `desync` entry and a warning toast rather than a
silently incomplete canvas.

### Groups

Group members live at `groups[g].items[i]`, not `model.items`, so a model with a group
renders incomplete unless they are walked — GoodwinLinear02 showed 18 of its 26 items.
They carry ABSOLUTE coordinates, so no transform is needed. They are addressed as
`g0:5` and marked `readOnly`: `Item` addresses `model.items[i]`, so moving or deleting a
group member needs a different path. Rendering them correctly matters more than editing
them, and nested groups are not walked recursively.

### Path handling

The server listens on localhost with no auth and any browser page can POST to it, so an
unconstrained `path` would be an arbitrary-file read. Loads are confined to the model
roots (`~/minsky/examples`, `~/minsky-models`, `./models`, the upload dir) and to `.mky`.
Anything else is a file picker away — upload it.

### Display

`fitView()` sets a viewBox after loading, since real models use the whole canvas. That
changes the coordinate mapping, so pointer maths goes through the SVG's inverse CTM
rather than `getBoundingClientRect`, keeping drag and wiring correct at any zoom.

Names are shown through `pretty()`: Minsky round-trips `C_D` as `C<sub>D</sub>` and
prefixes scoped variables with a numeric id (`50191504896:w`). The raw key stays the
identity used against the API and appears on hover.

## Saving

    Save        write back to the file the model came from (⌘S)
    Save As…    write to a name or path inside a writable directory (⇧⌘S)
    ↓           download a copy through the browser

    POST /api/save     {name}  -- omit `name` to save back to the current file
    GET  /api/download          -- the model as a .mky attachment

### Readable and writable roots are deliberately different sets

Loading may read `~/minsky/examples`. Saving may **not** write there. A save is one
mis-click from overwriting a shipped reference model, and nothing would restore it.
Writable roots are `~/minsky-models` (created on demand), `./models`, and the upload dir;
a bare name resolves into `~/minsky-models`. Anything else is refused with the list of
allowed directories and a pointer to Download, which keeps a copy anywhere without giving
the server a write path outside its own directories.

The pre-existing `/api/save?path=…` took an unvalidated path — an unguarded write
primitive on a server with no auth that any browser page can POST to. That is now gone.

### Dirty tracking

`snapshot()` carries `currentFile`, `currentPath` and `dirty`. Every mutating endpoint
marks the model dirty; load, clear and save clear it. The filename in the toolbar shows
`•` in amber while unsaved, Save is disabled when there is nothing to write, and Clear,
Open and page-unload all confirm before discarding unsaved work.

### Round-trip fidelity

An engine-saved file re-parses to **identical** wire topology — verified by loading
GoodwinLinear02, saving it, and comparing the parsed topology of both (27 wires, equal).
`test_server.py` section 9 goes further: build a model, Save As, clear, reopen from disk,
confirm the topology is exact, and confirm it still integrates correctly
(`int1 = 14.6` at `t = 3.04` against `7.0 + 2.5t`).

## Zoom and pan

    wheel / two-finger scroll   pan
    pinch (wheel + ctrl/meta)   zoom about the cursor
    drag empty canvas           pan
    ⌘0 fit · ⌘+ in · ⌘− out · click the percentage for 100%

**The viewBox is the single source of truth.** Everything on the canvas is already in
model coordinates -- item positions and port positions both come from the engine -- so
scaling the viewBox scales the whole picture and no per-item transform exists. Pointer
maths goes through the SVG's inverse CTM, so drag and wiring need no special case at any
zoom. Verified: dragging at 50% lands within **1e-5 model units** of the drop point, and
wiring works at 0.894.

**Fit never zooms in.** Fitting means "zoom out until everything is visible"; a model
with a single small item otherwise fit at 597%, which reads as broken rather than close.

Two counter-scales keep it usable when zoomed out. Strokes carry
`vector-effect: non-scaling-stroke`, and port radius is divided by the zoom so ports stay
clickable rather than shrinking to a pixel. Text is deliberately **not** counter-scaled:
letting labels shrink is what makes zooming out declutter a dense model.

`render()` rebuilds the DOM, so `applyView()` runs afterwards to restore port radii.

**Pan versus deselect.** Dragging empty canvas pans; clicking empty canvas deselects.
Both start the same way, so deselect fires on pointer-up only if the pointer never moved
more than a pixel — otherwise every pan would clear the selection.

Names also resolve LaTeX macros now (`\lambda` → λ), since Minsky stores them raw and
economic models are full of them.

## Undo and redo

    ⌘Z undo · ⇧⌘Z redo · maxHistory 100

### Three traps, in the order they bit

**1. Nothing pushes history from pyminsky.** Three edits then `undo(1)` changed nothing.
The REPL gets history free because `RESTService.cc` calls `commandHook` after every
command; direct method calls do not. Without an explicit `pushHistory()`, undo is silently
a no-op — the same shape as the Godley `icon.update()` trap.

**2. `pushHistory()` REORDERS `model.items`.** It round-trips the model, and Godley-owned
variables are regenerated at the end of the list. Pushing *after* a mutation therefore
invalidates the index that mutation just returned: `/api/item` reported index 5, the push
moved that item to 1, and the next `/api/wire` against index 5 hit a different item
entirely. So checkpoints are taken **before** each mutation, which is also the more correct
semantics — undo wants the pre-state. `pushHistory()` returns True only when the state
actually changed, so back-to-back checkpoints do not pile up duplicates.

**3. `undo(0)` is NOT a getter.** It restores the state at the current pointer, discarding
anything not yet pushed. Using it to read the pointer for `canUndo`/`canRedo` meant that
merely *reading* state reverted the model: add an item, `GET /api/state`, item gone. The
pointer is now tracked in Python and the engine is never asked. An isolated probe made
`undo(0)` look harmless, because it only destroys when the live state differs from the tip.

### Wire topology has to travel with the history

`_WIRES` is the only record of which ports each wire joins, and undo rewrites engine state
without telling the server — so undoing would leave the canvas drawing wires that no longer
exist. `_WHIST` snapshots `_WIRES` at exactly the points history is pushed, keyed by the
same pointer, so the two timelines cannot drift. A new edit after an undo prunes the redo
tail from both. Any residual mismatch still surfaces through the existing `desync` guard.

### Coverage, measured

Covered: add / delete / move item, wire, Godley cell, Godley asset class, Godley
insert-and-delete **row**, parameter and initial values.

Partial: Godley **column** operations. Undo removes the column's name and its stock
variable but does not shrink the column count, leaving an empty trailing column. Verified
cosmetic — a table with one still resets, runs and integrates correctly.

Not covered: solver settings (`epsRel` and friends), which are not model structure.

Undoing back to the state a file was saved at still reports the model as dirty; the flag
is set on any undo rather than compared against the saved point.

`test_server.py` section 10 covers it, including that a model still **integrates
correctly** after undo→redo — a wire record disagreeing with the engine would otherwise
draw right and compute wrong.

## Findings from actually using it

Four defects that only appear when a person builds a model by hand. None were caught by
the API-driven tests, because those never render.

**Ports had no radius on a fresh model, so nothing could be wired.** Adding zoom moved
port radius out of CSS into `applyView()`, which early-returns when no view exists — and
a view was only established by *opening a file*. Starting from an empty canvas therefore
gave every port `r=0`: invisible, and a drop landed on the node body instead. The CSS now
carries a radius as the floor and a view is established before the first paint.

**Clicking an item to select it dirtied the document.** Pointer-down began a move and
pointer-up POSTed it regardless of distance, so selecting something marked the file
unsaved, added an undo checkpoint, and made "discard unsaved changes?" appear after the
user had only looked. A move under half a model unit is now treated as a selection —
the same distinction already used to separate a pan from a deselect.

**A saved model containing a Godley table reopened with no wires.** A Godley table's stock
and flow variables are regenerated on load rather than stored, so the file listed 5 items
where the engine materialised 8. The trace required equal counts and bailed out entirely.
The file's items in fact align with a *prefix* of the engine's, with the generated ones
appended, so the alignment now maps the prefix and verifies types rather than demanding
equality. All 37 shipped examples still load exactly.

**A new Godley table had no flow row.** The engine creates one with two rows — stock
headers and initial conditions — so there was nowhere to enter a flow, while every
description of the thing, including the editor's own hint, talks about flow rows.
`Model.godley()` now seeds one (`flow_rows=1`, overridable). A blank flow row sums to `0`
and drives nothing, so an unused one costs nothing; verified a seeded table fills in and
integrates correctly with no extra rows added.

Each cell also carries a placeholder naming what belongs in it — `stock name`,
`initial value`, `flow label`, `flow variable`, and `flows ↓ stocks →` in the corner —
because the three row kinds mean different things and nothing on screen distinguished
them. A table with no flow rows at all now says so instead of showing a bare grid.

**Adding a variable fired two chained native `prompt()` dialogs** — now an inline form in
the palette. The prompts blocked the page, could not validate before a round trip, and
could not be answered independently at all (an automated client gives both the same
answer). Validation is now local and reported in place rather than as a toast: a missing
name, a name starting with a digit, and an unparseable value each say so against the
offending field, and the form stays open with the input preserved.

The server's message was wrong too. "parameter needs name and value" appeared when a name
*had* been given and only the value failed to parse, which sends people looking in the
wrong place; it now says "a parameter needs a numeric value". A stock may also carry an
optional initial value, a flow takes none (it is driven by whatever is wired in), and a
parameter requires one.

Worth knowing: **the same name twice is legitimate.** Minsky treats it as one variable
with two icons, so the form does not reject it — verified that two `alpha` icons yield a
single `:alpha` value.
