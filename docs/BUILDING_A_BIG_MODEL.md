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

## 3. Two arguments is the hard limit — fixed

`UserFunction::evaluate(double in1, double in2)` sets every argument after the second to
zero, and the icon only ever grows two input ports. `f(a,b,c) = a*100+b*10+c` fed 1 and 2
returns **120**, not 123, at reset and throughout a run. Declaring a third is now refused
rather than silently zeroed.

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

## 6. The default solver settings are impractical at this size — worth knowing

Minsky ships `implicit`, `epsRel` 1e-8, `epsAbs` 1e-10. On this 215-item model:

| solver | step size | cost/step | to reach t=5 |
|---|---|---|---|
| implicit, 1e-8/1e-10 | 0.0005 | 45.3 ms | **547 s** |
| implicit, 1e-4/1e-6 | 0.0414 | 13.9 ms | ~2 s |
| explicit, 1e-4/1e-6 | 0.0699 | 1.56 ms | ~0.1 s |

That is ~11,000× end to end. A user who opens a mid-sized model, presses Run and waits is
not going to guess that the tolerances are the reason. The model is saved with explicit /
1e-6 / 1e-8. **Worth considering: a warning, or defaults that scale with model size.**

## 7. The simulation socket costs 35× the engine — worth knowing

`/ws/sim` emits one frame per solver step carrying every value: ~55 ms/step against the
engine's 1.5 ms. Fine for watching a model, too slow for measuring one — the experiments
here run headless (`models/runner.py`) for that reason. **Worth considering:** a sampling
interval on the socket, so long runs stream every Nth step.

## 8. Smaller things

- A user function on the **implicit solver** is refused at step 0, mid-run, rather than
  when the model is built or reset. The message itself is good ("user functions cannot be
  used with an implicit method") — it just arrives after the user has pressed Run.
- **Slider bounds** are refused when the current value sits exactly on a bound, and the
  message ("the engine did not keep sliderMin") does not say so.
- `POST /api/item` has no `userFunction` kind; it is `kind=operation, op=userFunction`.
- A **parameter's value** has no endpoint of its own — it goes through `/api/init`, since
  a parameter's value is its initial condition. `attrs` covers units, sliders and rotation
  but not the value.
- **max steps defaults to 2000**, which this model needs ~860 of for t=60. A longer run
  hits the cap silently-ish.

## What worked well

- Godley tables: multi-table, shared stocks, per-column asset classes, symbolic row sums
  that cancel to `0` when the flows match. The whole accounting discipline held to 1e-15
  across every run without a single imposed constraint.
- The wiring engine is exact. Every ODE built from plain operation blocks integrated to
  1e-12 or better against closed forms.
- Tidy laid out 215 items and 220 wires without overlaps.
- `/api/layout`, `/api/godley/*`, the units checker and the equation view all handled a
  model an order of magnitude larger than the bundled examples.
