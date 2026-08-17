# Engine patches

Changes to Minsky's own C++, kept here so they are reproducible and survive a fresh
checkout. They are applied to the Minsky source tree (`~/minsky`) and the engine rebuilt;
`pyminsky.so` is a build product and is not in this repository.

## Applying

```bash
cd ~/minsky
git apply ~/minsky-web/engine-patches/0001-userfunction.patch
make CXXFLAGS='-stdlib=libc++ -isystem /opt/homebrew/include -Wno-deprecated-declarations' \
     pyminsky.so
```

The `CXXFLAGS` override is not part of the patch and is not optional on this machine:

- **`-isystem /opt/homebrew/include`** — boost lives there and is not on the default
  search path. `-I` also works for compiling, but boost/locale trips a
  `char_traits<unsigned int>` deprecation that `-Werror` turns into an error unless boost
  is treated as a system header.
- **`-Wno-deprecated-declarations`** — the same deprecation reaches `mdlReader.cc` through
  the SDK's own headers, where `-isystem` cannot help.

A first build after a fresh clone also needs `libclipboard` configured in place; if its
`CMakeCache.txt` records a different directory (the tree here was built elsewhere and
moved), delete the cache and let cmake redo it:

```bash
cd ~/minsky/libclipboard && rm -rf CMakeCache.txt CMakeFiles && \
  cmake -DBUILD_SHARED_LIBS=0 -DCMAKE_C_FLAGS=-fPIC . && make
```

## 0001 — user functions

Two things Minsky's user functions got wrong, both silently. They are one patch because
they touch the same files and the second builds on the machinery the first introduced.

### A function took only two arguments

`UserFunction::evaluate(double in1, double in2)` zeroed every argument after the second,
and the icon only ever grew two input ports, so

    f(a,b,c) = a*100 + b*10 + c        fed 1 and 2, returned 120

at reset and throughout a run, with no error anywhere. Declaring more arguments was
accepted and quietly ignored. The arity is now a property of the item: `numPorts()`
follows the declared argument list, the DAG already sized its arguments from `numPorts()`,
and the evaluator carries the arguments past the second and evaluates on all of them.

### An expression naming a model variable read stale values

`compile()` bound any model variable named in the expression to **that variable's own
storage**. It looks like a useful shorthand — write `0.03*K` and the function reads `K`
with no wire — and it reads correctly at reset. Then it reads stale data for the whole
run, because `RungeKutta::evalEquations` evaluates into a **copy** of the flow vector:

    auto flow(flowVars);                          // rungeKutta.cc
    for (...) equations[i]->eval(flow.data(), ...);

so the global vector the expression was bound to is not where the equations are being
computed. On `K' = 0.03*K` with `K` named inside the function, the derivative was **0 on
143 of 144 steps** and K came out **26% low**, on both solvers, with nothing reported.

Those values now travel as inputs like any other, read from the arrays the solver passes.
The expression binds to storage the function owns and the evaluator fills.

| file | change |
|---|---|
| `model/userFunction.h` | `numPorts()` from the argument list; `externalSymbols()`, `externalVals`, `evaluateAll()` |
| `model/userFunction.cc` | `updatePorts()` rebuilds the input ports and keeps the wires; `compile()` binds arguments first and named variables to its own storage |
| `model/operation.cc` | spreads more than two input ports down the icon's left edge, grows the icon to fit, labels each with its argument rather than always `x` and `y` |
| `engine/evalOp.h` | `inExtra` carries arguments past the second and the named variables; `evaluateN` |
| `engine/evalOp.cc` | one N-ary evaluation path; `numArgs()` reads the declared list; `deriv()` refuses rather than putting a zero in the Jacobian |
| `engine/equations.cc` | builds the eval op with every argument and every named variable, in the order `compile()` bound them; drops a stray `(x,y)` from function definitions in the LaTeX export |
| `engine/node_latex.cc`, `node_matlab.cc`, `equationDisplayRender.cc` | render every argument |

### Four things the implementation has to be careful about

**Rebuilding a port destroys the wires that end at it** — `~Port` calls `deleteWires()`.
So `updatePorts()` records what fed each input *before* rebuilding; the wire objects
themselves are gone by then.

**The output port is deliberately not rebuilt.** It does not depend on the argument list,
and its wire cannot simply be re-made: once the model has been reset, `addWire` refuses to
wire the input of a variable the equations already define, so the function would silently
lose whatever it fed.

**`compile()` and the equation builder must agree on the order** of the named variables,
because one binds them and the other supplies their values. `externalSymbols()` is the
single definition both use.

**`deriv()` now refuses when it cannot account for every input.** It switches on
`numArgs()`, and a function that declares no arguments but reads model variables would
have taken the `numArgs()==0` branch and put a **zero** into the Jacobian. The implicit
method has never had a derivative for a user function and still says so.

### Verified

- `f(a,b,c) = a*100+b*10+c` fed 1, 2, 3 returns **123**, at reset and through a run
- five arguments: `a + 10b + 100c + 1000d + 10000e` returns **54321**
- `K' = 0.03*K` with `K` named inside the function integrates to **1.26e-15** against the
  closed form, with the derivative zero on **0 of 144** steps
- a four-argument function driving `K' = (a+b+c)·K` integrates to **9.5e-16**
- wired arguments and a named variable in one expression, at reset and through a run
- functions chained by name, stable through a run
- arity, ports, wires and named references all survive save and load
- growing an argument list keeps every wire; shrinking drops only the wire whose argument
  has gone; the output stays connected throughout
- the implicit method still refuses, rather than integrating with a wrong derivative
- `models/shaikh_monetary_policy.py` produces results identical to the last digit
- both suites in this repository pass
