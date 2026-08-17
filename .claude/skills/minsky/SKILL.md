---
name: minsky
version: 1.0.0
description: |
  Drive the Minsky economic modelling engine through this repo's HTTP API or headless
  Python: build stock-flow-consistent models, wire equations, edit Godley tables, run
  simulations and read results. Use when asked to build, run, modify, debug or measure a
  Minsky model, to work with .mky files, or when a task involves pyminsky, Godley tables,
  or the minsky-web server. Contains engine behaviour that is not discoverable from the
  outside and that has cost real hours to find.
---

# Working with Minsky

Minsky is a system-dynamics engine for economics whose distinguishing feature is the
**Godley table**: a double-entry balance sheet whose rows must sum to zero. This repo wraps
it in an HTTP server (`minskyweb/server.py`) and a Python layer (`minskyweb/headless.py`),
with a model-building helper at `models/build.py` and a headless runner at
`models/runner.py`.

Read this whole file before building anything non-trivial. Most of what follows was found
by failing first.

---

## 0. The one thing that will bite you

**The engine fails silently.** It will accept a malformed model, run it, and hand back
plausible numbers that are wrong. It will accept an expression, echo it back verbatim, and
evaluate it as zero. It will report "done" on a run that stopped a tenth of the way.

Therefore: **never verify against your own record of what you did. Verify against ground
truth the engine wrote.** Read the state back. Check an identity you did not impose. Compare
against a closed form. If you cannot check it, you do not know it.

Two corollaries that have both burned this project:

- A test that greps source text for a substring proves nothing about behaviour.
- After a C++ rebuild, check object file **timestamps**, not build log text. Classdesc
  regeneration cuts the first `make` pass short, so run `make` until it says up to date.

---

## 1. pyminsky is a singleton

One process holds exactly one model. `H.Model()` twice in a process raises a guard error.

To compare two models, load them alternately in one process:

```python
from models.runner import Run
R = Run("~/minsky-models/A.mky")
qa = R.go(60.0, ["r", "g"], samples=200)
qb = R.use("~/minsky-models/B.mky").go(60.0, ["r", "g"], samples=200)
```

`Run.go()` **reloads** rather than resets, deliberately: an override left from the previous
experiment would otherwise contaminate the next one and nothing would say so.

The HTTP server holds the singleton for its whole life. So **while the server is running,
nothing else in the machine can open a model**. If you need to build models while a server
is up, go through the server's API, not through a second Python process.

---

## 2. Process handling — do this exactly

The server is long-lived and usually belongs to the user, not to you.

```bash
# default port is 8765, and this form takes NO arguments
python3 -m minskyweb.server

# any other port must come from Python -- serve() is the only way to set it
python3 -c "from minskyweb.server import serve; serve(port=8800)"

# is it up?
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8800/api/state

# stop ONLY a server you started, and only by explicit port
pgrep -f "port=8800" | xargs -r kill
```

**Never kill a process you did not start.** Never `pkill -f minsky`, never kill by name.
Assume a server already listening on 8765 is the user's and is not yours to touch.

Two things follow from `serve()` being the only way to set the port, and they matter:

- The port appears in the process **command line** as `port=8800`, which is what makes
  `pgrep -f "port=8800"` work at all.
- `pgrep -f "serve(port=8800)"` **silently matches nothing** — the parentheses are regex
  groups. It exits non-zero and looks like "no such process" rather than like a bad pattern.
  Match on `port=8800` alone.

`MINSKYWEB_SAVE_DIR` sets where models are saved, and it is read by the **server** process,
not by your shell — so `POST /api/save` writes wherever the running server was configured,
which is often not where you think.

```bash
export MINSKYWEB_SAVE_DIR="$CLAUDE_JOB_DIR/tmp/models_test"
python3 test_server.py && python3 test_headless.py     # both must print ALL PASS
```

Setting it for the suites is good hygiene but is no longer load-bearing: the suites clean up
after themselves, and a final sweep diffs against a snapshot taken at import, deletes
anything new, and **fails the run** reporting what it had to clean. Two consecutive runs
leave the model directory byte-identical. If a suite reports that it cleaned something up,
that is a real failure — a test leaked a file — not a warning to ignore.

---

## 3. Two ways in, and when to use which

| | use it for | entry point |
|---|---|---|
| **HTTP API** | building and editing a model, anything a user watches | `POST /api/...` on 8800 |
| **headless** | running and measuring, batch experiments | `models/runner.py` |

Use `runner.py` to *measure* a model and the socket to *watch* one — but the reason is no
longer cost. Streaming used to run about 55 ms a step against the engine's own 1.5 ms;
that was a defect, not a property, and it was fixed. `live_value_ids()` was being called
once per value key from inside a comprehension, and value objects are now bound once per
run. The socket also takes `every` (report one step in N) and `maxFps` options.

`runner.py` is still the right tool for batch experiments — it reloads between runs so a
leftover override cannot contaminate the next one — but do not avoid the socket on
performance grounds. **If you find `models/runner.py`'s docstring or any doc quoting the
55 ms figure, it is stale.**

---

## 4. Building a model

`models/build.py` compiles Python expression strings into Minsky operation blocks and
wires. Use it rather than hand-posting items.

```python
import sys; sys.path.insert(0, "models")   # build.py lives in models/, not the repo root
from build import Builder, api
api("/api/clear")
b = Builder()
b.param("kappa", 1.2)
b.param("m", 0.03, slider=(-0.02, 0.06))
iK = b.stock("K", 100.0)                 # returns the IntOp; wire the derivative INTO it
for name, expr in [("r", "(1 - omega) * u / v"),
                   ("g", "kappa * r"),
                   ("dK", "g * K")]:
    b.eq(name, expr)
b.wire(b.ref["dK"], iK, 1)               # derivative -> integral, port 1
b.plot("Rates", ["r", "g"], at=[1500, 300])
api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 60.0})
api("/api/layout")                       # Tidy; call once at the end
api("/api/save", {"name": "MyModel"})
```

Expression support is deliberately small: `+ - * / **`, unary minus, and the calls
`min max exp ln log sqrt abs`. Anything else raises rather than being silently dropped.

`b.ref[name]` maps a name to the item whose **output** carries it. `b.stock()` returns the
IntOp (what a derivative is wired into) but registers a *different* item for reading — see
§5.

**Always call `/api/layout` at the end.** Tidy has laid out 226 items and 230 wires without
overlaps on a model an order of magnitude larger than any bundled example.

---

## 5. Wiring — where the engine says no

A wire is made by **simulating a canvas drag**: `mouseDown` on the source's output port,
`mouseUp` on the destination's input port. Almost every wiring surprise follows from that.

- **Port 0 is the OUTPUT of an operation or a variable**, at any rotation — a mirrored
  multiply still has its output at port 0. Inputs start at 1, and asking for port 0 as a
  destination is an error. A stock or parameter variable has no input port at all.

  But **plots, Godley icons and Sheets are sink-only**: they have no output, and *every*
  port on them is an input, port 0 included. Never try to wire out of one. A plot's ports
  0–5 are its axis bounds and its **series start at port 6**, which is why `build.py` wires
  the *k*-th series at `6 + k`.

- **An integral shares its output port with its IntOp.** Both report port 0 at the same
  pixel, so a `mouseDown` there can land on the operation body and **drag it** instead of
  starting a wire. The symptoms are maddening: `addWire` is refused with a generic message
  about ports and overlap, moving the destination hundreds of pixels away changes nothing
  (the fault is at the *source* end), and the only trace is that the IntOp has quietly moved
  to wherever the drag dropped it. Whether it happens depends on which icon the canvas picks
  at that pixel, so the same expression builds in one model and fails in the next.

  **Fix, and it is Minsky's own idiom:** read a stock through an ordinary copy. `build.py`
  now does this for you in `stock()`. If doing it by hand, the copy must declare
  `var_type: "integral"` — the type the name is already registered under — or the engine
  refuses to create it.

- **A wire INTO a Godley-attached variable is answered by cloning it.** A table draws an
  icon for every stock and every flow. Dropping a wire on one creates a *second* variable of
  the same name at the same point and attaches the wire to that, so the model silently gains
  an item, the table's own variable stays unconnected, and your record names the original
  while the engine holds the copy. The only visible signal is that the item count grew;
  `headless.py` detects exactly that and refuses with 409.

  Wiring *out* of one is also said to be refused, but that half is asserted only in prose
  and has no test behind it — treat it as unverified. Either way the remedy is the same and
  is Minsky's own idiom: place ordinary copies elsewhere and wire those. `LoanableFunds`
  does exactly this.

- **Several wires may go into ONE input port, and they are combined by that PORT'S ROLE —
  not by the operation's name.** Measured, `a = 6` and `b = 3` both wired into **port 1**:

  | op | result | |
  |---|---|---|
  | `add` | 9 | additive port → sums |
  | `subtract` | **9** | port 1 is the *positive* side → sums |
  | `multiply` | 18 | multiplicative port → multiplies |
  | `divide` | **18** | port 1 is the *numerator* → multiplies |
  | `min` / `max` | 3 / 6 | reduces |

  So "they sum their inputs" is wrong for four of the six. Two wires into a `multiply`'s
  port 1 give `a*b`, not `a+b`, and nothing warns you. Do not assume one wire per input, and
  do not assume the combination is addition.

- **A second variable with the same name must match the existing `var_type`**, or creation
  is refused outright.

- **`~Port()` calls `deleteWires()`.** Rebuilding an item's ports destroys the wires that
  end there. Record what *fed* each input, not the wire objects.

- **After a reset, the engine refuses a wire into the input of an already-defined variable.**
  If you must rebuild, never rebuild port 0.

- **A slider bound equal to the value is refused.** `param("rule", 1.0, slider=(0.0, 1.0))`
  fails; widen to `(-0.2, 1.2)`.

---

## 6. Godley tables

The layout, which is not guessable:

```
row 0     column headers. cell(0,0) is a label; cells 1.. are STOCK names, PLAIN.
          An "Assets:" prefix does nothing and does NOT set the class.
row 1     initial conditions  (initialConditionRow() reports which row it is)
rows 2..  flows. Column 0 is the flow's label; cells 1.. are flow VARIABLE NAMES.
```

```python
api("/api/item", {"kind": "godley", "name": "Banks", "at": [400, 400]})
api("/api/godley/0/class", {"col": 1, "cls": "asset"})    # col 0 has no class
api("/api/godley/0/cell",  {"row": 0, "col": 1, "value": "Reserves"})
```

Asset classes are exactly `noAssetClass | asset | liability | equity`, set per column,
and **only** `assetClass(col, cls)` sets them.

**Balance.** `rowSum(r)` returns a **symbolic string**, not a number: `'0'` means balanced,
`'-2L'` means it is not. It raises on row 0. The sum is

```
assets  -  liabilities  -  equity
```

so a balanced transfer between an asset and a liability carries the **same** sign on both
sides, while two liabilities carry **opposite** signs. This trips people constantly.

Three traps, all verified end to end:

1. **The balance check is exact `!= 0`, with no tolerance.** Opening figures written at 10
   significant digits leave a row out by 1e-08; at full precision, by 7e-15. Only
   binary-exact values give a clean zero, so **snap opening figures to a dyadic rational**.

   **But not too fine a one, and this is the trap.** The engine writes a stock's initial
   condition into the `.mky` *twice*: once at full precision as the Godley cell text, and
   once **rounded to six significant figures** as the value it actually initialises the
   stock with. On reload the rounded one wins. So a sheet can balance exactly at build
   time, pass the engine's own row check, and still be out at `t=0` — with the residual
   *constant across every horizon*, which is the tell that it was never integration error.

   Observed: `48.998047 → 48.998`, `13.452148 → 13.452100`, and four net worths that should
   have summed to zero summing to −8e−5 instead.

   1/1024 is binary-exact but needs ten decimals, so six significant figures destroys it.
   **Use 1/16** (0.0625) for values below 100 — binary-exact and short enough to survive
   the round trip. That took the same model from −8e−5 to 1.8e−13.

2. **`icon.update()` must be called after editing a table**, or `reset()` dies with
   `Invalid valueId: :<stock>` and the stock variables are never created. Neither
   `editor.update()` nor doing nothing works — only the icon's own `update()`. Every
   mutating method in `headless.py` calls it, so going through that layer is safe.
   Note `update()` is a *Godley* method; do not call it on a PlotWidget.

3. **A numeric literal in a flow cell parses and balances but drives nothing.** The stock
   stays at its initial condition. Flow cells name flow *variables*, whose values come from
   the canvas.

**Shared stocks work by name**: the same stock name in two tables is the same stock. That is
how a liability of one sector becomes an asset of another, and it is what makes the row sums
cancel across a multi-sector model.

**And it carries the worst silent trap in the whole Godley surface.** There is only ONE
variable behind the shared name, so there is only ONE initial condition — but *each table
stores and displays its own*, and the engine quietly uses whichever was written last. A
table can show 100 for a stock the model is actually running at 250, and nothing is wrong on
screen. The server reports this as a `conflicts` block on the cell response; read it. If you
write an opening balance sheet across four tables, write each shared stock's IC **once** and
check the others agree.

**The `{index}` in `/api/godley/{index}` can go stale.** It resolves against `model.items`,
and a table edit can *reorder* that list — renaming a stock header moves the regenerated
variable and everything after it shifts. Capture the index returned by `/api/item` and
re-read it after edits rather than hardcoding a position.

Real capital is **not** a claim on anybody, so it has no counterparty and does not belong in
a table of claims. Keep it out and carry it as an ordinary stock.

---

## 7. Solver settings

Minsky ships `epsRel=1e-2`, which is far too loose for anything quantitative. Set it.

```python
api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 60.0})
```

- The **implicit** method is right for a genuinely stiff model, but on a large non-stiff one
  it can take 0.0005-long steps at 45 ms each — t=40 becomes an hour. The explicit method at
  1e-6/1e-8 takes steps ~140× longer at ~1/30 the cost and agrees with the tight implicit
  run to reported tolerance. `models/runner.py` defaults to explicit for this reason.
- **User functions cannot be used with the implicit method** — the engine refuses rather
  than using a wrong derivative.
- A run that exhausts its step budget is a real failure mode. `runner.go()` raises
  `the run stalled at t=...` rather than returning a short path as if it finished.

---

## 8. Running a model and reading values

```python
from models.runner import Run
R = Run("~/minsky-models/MyModel.mky")
path = R.go(60.0, ["r", "g", "d"], overrides={"m": 0.04}, samples=200)
drift = max(abs(path[k][-1] - path[k][0]) for k in ("r", "g", "d"))
```

**The lookup is the cost, not the read.** Reading 89 values costs 8.54 ms if you look each
one up per step, and 0.027 ms through objects bound once before the run — a 300× difference.
Bind `VariableValue` objects once, then read them each step.

**`valueId` is not `":name"`.** Minsky mangles names into ids (`\tau_L` is not stored under
`:\tau_L`). Ask the item for its `valueId()` and key off that.

**`RungeKutta::evalEquations` does `auto flow(flowVars)` — a copy.** Anything bound to the
global `ValueVector::flowVars` therefore reads *stale* data during a run. This is why a user
function that names a model variable read correctly at reset and then evaluated as 0 for
essentially every step.

---

## 9. User functions

The body and the argument list live in **different properties**:

- `expression` — the body
- `description` — the argument list is parsed out of this

Setting only the body leaves the function on the `x, y` it was born with, so `a*b + c` is
accepted, echoed back verbatim, and computes 0. Use
`POST /api/item/{ref}/expression` with the full `f(a,b,c) = body` form, which sets both.

**Order matters when the heading changes:** the endpoint calls `resync_wires()`, which
reloads the document and invalidates every item pointer. Read `raw.name()` and
`argNames()` **before** the resync, or you touch freed memory and segfault.

This repo runs a patched engine (`~/minsky`, patch kept at
`engine-patches/0001-userfunction.patch`). Upstream stock Minsky has two bugs this patch
fixes — arity capped at two arguments, and name-referenced variables reading zero during a
run. If you are on unpatched Minsky, both are live.

---

## 10. Measurement discipline

This project has retracted results twice for measurement design, not arithmetic. Both
mistakes are easy to repeat.

**Comparative static vs impulse response.** To compare two economies differing in one
parameter, you must **re-solve the baseline at each parameter setting** so that every run
sits on its own balanced path. Sweeping a parameter while leaving *solved* quantities at
their baseline values leaves every run but one off its rest point, and what you measure is a
transient that grows without bound with the horizon. A slope that changes when you extend
the run is not a comparative static.

Check it: a structural result is **horizon-independent**. If the number moves between t=12,
t=30 and t=60, it is a transient — which is a legitimate thing to report, but report it as
one.

**Verify the baseline actually sits still** before reading anything off a shock. Run it
unshocked and check the worst drift; `1e-13` or better is achievable and is what a genuine
rest point looks like.

**Check identities rather than imposing them.** An identity enforced by construction proves
nothing. Integrate each stock from its own flow and then test `K - L - E - RE` against zero.

---

## 11. Endpoint reference

Model: `POST /api/clear` `/api/load` `/api/save` `/api/reset` `/api/undo` `/api/redo`
`/api/layout` `/api/solver` `/api/init` · `GET /api/state` `/api/equations` `/api/files`
`/api/download`

Items: `POST /api/item` — `kind` is one of
`variable|parameter|operation|godley|plot|sheet|switch`, and `var_type` is one of
`flow|stock|parameter|integral|constant|tempFlow`. Both lists are longer than the
`ItemSpec` field descriptions in the source, which are stale. `constant` is how a numeric
literal is placed (the expression compiler uses it for every literal), and a constant takes
`value` and **rejects** `name` — its value is its name.
Also `/api/item/{ref}/rename` `/move` `/attrs` `/copy` `/data` `/expression` ·
`GET /api/item/{ref}/instances` — every icon of a variable and what defines it; use this
rather than the engine's `findVariableDefinition`, which **segfaults** in this build for
every input including an empty string ·
`DELETE /api/item/{ref}` · `POST /api/items/delete` `/api/items/move`

Wires: `POST /api/wire` (`src`, `dst`, `port`) · `DELETE /api/wire/{index}`

Godley: `GET /api/godley/{index}` · `POST /api/godley/{index}/cell` `/class` `/resize`
`/row/{action}` `/col/{action}`

Groups: `POST /api/group` `/api/group/{ref}/rename` `/ungroup`

Analysis: `POST /api/analysis/units` — dimensional analysis. Worth calling explicitly: the
engine says nothing at all when units check out, so silence is not evidence you ran it.

Export: `GET /api/export/canvas` `/api/export/plot/{ref}` (svg, png, pdf, ps) ·
`POST /api/export/animation`. These use the **engine's own** renderers directly; no external
converter is involved. `rsvg-convert` is used only by the *themed* renders —
`/api/equations`, `/api/phillips`, `/api/pubtabs/{i}/render` — which go through a themed SVG
so the output keeps the page's colours rather than the engine's black-on-transparent.

Run: `WS /ws/sim` (watching only — see §3)

`AttrSpec` carries `units`, `sliderMin/Max/Step`, `rotation`, `numLines` (PlotWidget only,
1–30). All optional; send only what you are changing.

---

## 12. Orientation in this repo

```
minskyweb/server.py      the HTTP API
minskyweb/headless.py    the Python layer over pyminsky; Godley semantics live here
models/build.py          expression -> blocks compiler; read its comments, they record
                         engine behaviour found the hard way
models/runner.py         headless runner; the reference for measuring a model
models/data/             FRED and FDIC pipelines that fetch series WITH their titles,
                         so a series is never used unidentified
docs/MINSKY_HEADLESS.md  the headless layer
docs/BUILDING_A_BIG_MODEL.md
test_server.py           both suites must print ALL PASS before any commit
test_headless.py
```

Working models to read as examples, smallest first: `models/enterprise_core.py` (40 items,
closed form to check against), `models/enterprise_banking.py`, `models/enterprise_equity.py`,
`models/shaikh_term_structure.py`, `models/shaikh_monetary_policy.py` (226 items, three
Godley tables).
