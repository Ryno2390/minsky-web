# What building a 215-item model surfaced

Notes from constructing `models/shaikh_monetary_policy.py` — a stock-flow-consistent
monetary policy model with three Godley tables — entirely through the HTTP API. Every
claim here was measured, not inferred.

Ordered by how much damage each one does silently.

## 1. A user function that names a model variable is wrong during a run — fixed

`UserFunction::compile()` walks the identifiers in the expression and binds any that is a
**model variable** straight to that variable's storage. It looks like a useful shorthand:
write `0.03*K` and the function reads `K` with no wire at all. It even reads correctly at
reset.

Then it evaluates as 0 for essentially every step of a run.

Measured on `K' = 0.03·K`, K(0)=100, against the analytic `100·e^{0.03t}`:

| how the derivative is built | implicit solver | explicit solver |
|---|---|---|
| wired blocks | exact, 4e-12 | exact, 1e-15 |
| user function, input **wired** | refused with a clear message | exact, 1e-15 |
| user function, `K` **by name** | 26% low, `dK` = 0 on 143/144 steps | 26% low, 0 on 145/146 |

No error frame on either solver. The model looks right on the canvas, and the run is
wrong. **Now refused** by `POST /api/item/{ref}/expression`, with the fix spelled out.

## 2. A user function's arguments live somewhere else — fixed

The body is `expression`. The **argument list** is parsed out of `description`, written as
a name like `f(a,b)`. Setting only the body left every function on the `x, y` a fresh one
is born with, so `a*b + c` was accepted, echoed back verbatim, and computed 0.

The endpoint now takes either form: a bare body, or `f(a,b) = body`.

## 3. Two arguments was the hard limit — fixed in the engine

`UserFunction::evaluate(double in1, double in2)` set every argument after the second to
zero, and the icon only ever grew two input ports. `f(a,b,c) = a*100+b*10+c` fed 1 and 2
returned **120**, not 123, at reset and throughout a run, with nothing reported.

This one is fixed in Minsky's own C++ rather than guarded around: the arity is now a
property of the item, so a function takes as many arguments as its name declares. The
patch is in `engine-patches/`, with the build flags this machine needs.

    f(a,b,c) = a*100 + b*10 + c   fed 1,2,3   ->  123
    k(a,b,c,d,e) = a+10b+100c+1000d+10000e   ->  54321
    a 4-argument function driving K' = (a+b+c)K  ->  9.5e-16 against the closed form

Ports spread down the icon's left edge and are labelled with the argument each carries,
the icon grows to fit them, and editing an argument list keeps the wires that still have
somewhere to land. The output port is deliberately left alone: its wire cannot be re-made
once the model has been reset, because `addWire` refuses to wire the input of a variable
the equations already define.

## 4. Godley table rows must balance in exact floating point — worth knowing

`GodleyTable::stringify` filters terms on `i->second != 0` — an exact comparison, no
tolerance. An initial-conditions row out by 1e-15 is reported as not balancing, and it is
right to: the accounting either closes or it does not.

The fix on the model side is to snap the opening figures to multiples of 1/1024, which are
exact in binary, and compute the residual column from those. Writing them at 10
significant digits left the row out by 1e-08; at full precision, by 7e-15. Only the
binary-exact version gives a clean zero.

## 5. A Godley table's own variable icons cannot be wired — worth knowing

A table draws an icon for every stock column and every flow row, and both are display
only. The engine refuses a wire out of one, and our API refuses a wire into one
("Godley table variables cannot be wired into from outside").

The idiom is to place **ordinary copies** elsewhere and wire those. In `LoanableFunds`
every flow has one icon wired into it and several plain copies feeding other blocks. Not
obvious from the outside; it cost an hour.

## 6. The default solver settings are impractical at this size — now diagnosed

Minsky ships `implicit`, `epsRel` 1e-8, `epsAbs` 1e-10. On this 215-item model:

| solver | step size | cost/step | to reach t=5 |
|---|---|---|---|
| implicit, 1e-8/1e-10 | 0.0005 | 45.3 ms | **547 s** |
| implicit, 1e-4/1e-6 | 0.0414 | 13.9 ms | ~2 s |
| explicit, 1e-4/1e-6 | 0.0699 | 1.56 ms | ~0.1 s |

That is ~11,000× end to end, and a user who presses Run and waits has no way to guess the
tolerances are the reason. A run that stops on the step cap now says where it got to, how
many steps the current step size would need, and — when the step size is the giveaway —
names the settings to change:

    stopped after 300 solver steps, at t=0.1523, short of tmax=60. At this step size
    (0.000508) reaching tmax needs about 118,157 steps. Steps this small usually mean
    the solver tolerances rather than the model: try epsRel 1e-6, epsAbs 1e-8, and
    implicit off.

The defaults themselves are left alone: implicit is the right choice for a genuinely
stiff model, and silently switching someone's solver is not a fix. The step cap in the
interface went from 2,000 to 50,000, which reporting no longer scales with.

## 7. Reporting a run cost more than solving it — fixed

`/ws/sim` emitted one frame per solver step, and each frame read every value out of the
engine. Two things were wrong with that.

`live_value_ids()` walks every item in the model — 29 ms here — and it was called from
**inside a comprehension over the value keys**: 89 calls, ~2.6 s of pure waste before
every run, growing with the square of the model.

And nearly all the cost of reading a variable is the **lookup**, not the read. Measured on
this model:

| reading all 89 values | cost |
|---|---|
| `variableValues[k].value()` each step | 8.54 ms |
| through objects bound once per run | **0.027 ms** |

316×. The bound objects track the run exactly — checked against fresh lookups every 40
steps over 400 steps: zero disagreement — and nothing can invalidate them, because editing
is locked for the duration of a run.

Same model, same run, same result to the last digit:

| | frames | time |
|---|---|---|
| before | 430 | 6.62 s |
| after | 430 | **0.89 s** |

The engine step is 1.56 ms, so 430 steps cannot cost less than 0.67 s. What is left is
within a third of that floor.

Clients can also thin what they are *sent* without changing what is solved: `every: N`
reports one step in N, `maxFps: F` reports at most F frames a second. Both default to off,
so nothing changed for a client that says nothing, and whatever a cap held back is sent
before the run closes — the last frame is always the true final state. The interface asks
for 30 fps, which is all a screen can paint.

## 8. There was no way to make a chart — fixed

`POST /api/item` had no plot kind, so a model built through the API had nothing to look
at: the Plots workspace correctly reported "this model has no plots" and there was no way
to give it one. `canvas.addPlot()` was there all along.

A plot is also born with room for **one** line — one series per axis — and nothing grew
it, so every extra series needed its own chart. `numLines` on `POST /api/item/{ref}/attrs`
sets the count and rebuilds the ports (6 + 4N of them; with N lines the y ports run
6..6+2N-1, the first N left axis and the next N right). A plot's title is its name, so
`rename` sets it.

The model now ships with three charts and is watchable the moment it opens.

## 9. Smaller things

- A user function on the **implicit solver** is still refused at step 0, mid-run, rather than
  when the model is built or reset. The message itself is good ("user functions cannot be
  used with an implicit method") — it just arrives after the user has pressed Run.
- **Slider bounds** are refused when the current value sits exactly on a bound, and the
  message ("the engine did not keep sliderMin") does not say so.
- `POST /api/item` has no `userFunction` kind; it is `kind=operation, op=userFunction`.
- A **parameter's value** has no endpoint of its own — it goes through `/api/init`, since
  a parameter's value is its initial condition. `attrs` covers units, sliders and rotation
  but not the value.
- The **step cap** now defaults to 50,000 in the interface and a run that hits it explains
  itself, but it is still a cap the user has to know about.

## What worked well

- Godley tables: multi-table, shared stocks, per-column asset classes, symbolic row sums
  that cancel to `0` when the flows match. The whole accounting discipline held to 1e-15
  across every run without a single imposed constraint.
- The wiring engine is exact. Every ODE built from plain operation blocks integrated to
  1e-12 or better against closed forms.
- Tidy laid out 215 items and 220 wires without overlaps.
- `/api/layout`, `/api/godley/*`, the units checker and the equation view all handled a
  model an order of magnitude larger than the bundled examples.
