# minsky-web

A modern browser front end for **[Minsky](https://github.com/highperformancecoder/minsky)**,
driving the existing engine headlessly. The engine is not forked or modified — only the
interface is new.

Minsky's value is its engine: Godley tables, stock-flow consistency, and models that
actually run through time rather than being solved as simultaneous equations. What is
dated is the Tcl/Tk shell around it. This replaces the shell and leaves the engine alone.

    python3 -m minskyweb.server        # http://127.0.0.1:8765

See **[docs/MINSKY_HEADLESS.md](docs/MINSKY_HEADLESS.md)** for what the engine exposes and where it bites.

## What it does

- **Build** — palette of variables, parameters, operations and Godley tables; drag to
  place, drag output→input to wire.
- **Edit Godley tables** — full double-entry grid with asset/liability/equity classes,
  add and remove rows and columns, and a **live per-row balance check**, which is the
  thing that makes Minsky worth keeping.
- **Rename** — F2 or double-click a variable; renaming affects every icon of it.
- **Edit** — click a wire to select it, Delete to remove; an input that is already
  connected says so rather than failing obscurely.
- **Undo / redo** — ⌘Z and ⇧⌘Z across items, wires and Godley edits.
- **Navigate** — zoom about the cursor, pan by drag or two-finger scroll, fit to model.
- **Run** — simulation streams over a WebSocket with a live plot; diverging models are
  detected and reported rather than crashing the stream.
- **Open** — any of the shipped examples, or upload a `.mky`. All 37 shipped examples
  load with exact wire topology.
- **Save** — Save / Save As / Download, with an unsaved-changes indicator. The shipped
  examples are readable but **not** writable, so a mis-click cannot overwrite a reference
  model.

## Why a server exists

Minsky ships `minsky-RESTService`, which despite the name is **not** an HTTP server — it
is a stdin/stdout line REPL over a command registry. There is no network layer, so this
supplies one, talking to the engine in-process via `pyminsky`.

## Requirements

A built Minsky providing `pyminsky.so`. Point `MINSKY_HOME` at the directory containing
it, or place it at `~/minsky`.

    pip install fastapi uvicorn python-multipart
    export MINSKY_HOME=/path/to/minsky
    python3 -m minskyweb.server

## Layout

    minskyweb/session.py    locate and import pyminsky
    minskyweb/headless.py   logical model API over Minsky's geometric one
    minskyweb/server.py     HTTP + WebSocket surface
    minskyweb/ui/           the browser front end (single file, no build step)
    docs/MINSKY_HEADLESS.md what the engine exposes headlessly, and its traps

## Tests

    python3 test_headless.py    # 12 checks
    python3 test_server.py      # 115 checks

Both build models whose answers are known analytically, so a mis-wired model fails loudly
instead of producing plausible numbers.

## Notes for anyone extending this

`docs/MINSKY_HEADLESS.md` is the useful document. The engine has several behaviours that
fail **silently**, each of which cost real time to find:

- Port coordinates are stale until `updateBoundingBox()`; wiring at a stale coordinate
  creates nothing and raises nothing.
- `model.deleteItem(i)` accepts an index and deletes nothing; deletion goes through the
  canvas hit-test.
- A Godley table needs `icon.update()` after editing or `reset()` dies with
  `Invalid valueId`.
- A number in a Godley flow cell balances but drives nothing.
- `pyminsky` is a **singleton**: two model objects are one engine.
- Nothing pushes undo history; `pushHistory()` also **reorders items**; and `undo(0)`
  is not a getter — it discards unpushed changes.

Every one of those is wrapped and verified in `headless.py` so it cannot bite twice.

## Licence

Minsky is GPL-3. This front end talks to it and is released under the same terms.
