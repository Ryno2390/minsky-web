# Engine patches

Changes to Minsky's own C++, kept here so they are reproducible and survive a fresh
checkout. They are applied to the Minsky source tree (`~/minsky`) and the engine rebuilt;
`pyminsky.so` is a build product and is not in this repository.

## Applying

```bash
cd ~/minsky
git apply ~/minsky-web/engine-patches/0001-userfunction-arity.patch
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

## 0001 — a user function takes as many arguments as it declares

Minsky's user functions were fixed at two arguments, and said nothing about it.
`UserFunction::evaluate(double in1, double in2)` zeroed every argument after the second,
and the icon only ever grew two input ports, so

    f(a,b,c) = a*100 + b*10 + c        fed 1 and 2, returned 120

at reset and throughout a run, with no error anywhere. Declaring more arguments was
accepted and quietly ignored.

The arity is now a property of the item rather than of the operation type.

| file | change |
|---|---|
| `model/userFunction.h` | `numPorts()` returns `argNames.size()+1` |
| `model/userFunction.cc` | `updatePorts()` rebuilds the input ports when the argument list changes, keeping the wires; called from `description()` |
| `model/operation.cc` | spreads more than two input ports down the icon's left edge, grows the icon to fit them, and labels each with its argument rather than always `x` and `y` |
| `engine/evalOp.h` | `inExtra` carries arguments beyond the second; `evaluateN` evaluates on all of them |
| `engine/evalOp.cc` | `ScalarEvalOp::eval` gathers every argument when there are more than two; `numArgs()` for a user function reads the declared list |
| `engine/equations.cc` | builds the eval op with every argument, not the first two; drops a stray `(x,y)` appended to function definitions in the LaTeX export |
| `engine/node_latex.cc`, `node_matlab.cc`, `equationDisplayRender.cc` | render every argument |

### Two things worth knowing about the implementation

**Rebuilding a port destroys the wires that end at it** — `~Port` calls `deleteWires()`.
So `updatePorts()` records what fed each input *before* rebuilding and puts those wires
back afterwards; the wire objects themselves are gone by then.

**The output port is deliberately not rebuilt.** It does not depend on the argument list,
and its wire cannot simply be re-made: once the model has been reset, `addWire` refuses to
wire the input of a variable the equations already define, so the function would silently
lose whatever it fed.

### Verified

- `f(a,b,c) = a*100+b*10+c` fed 1, 2, 3 returns **123**, at reset and through a run
- five arguments: `a + 10b + 100c + 1000d + 10000e` returns **54321**
- a four-argument function driving `K' = (a+b+c)·K` integrates to a relative error of
  **9.5e-16** against the closed form
- arity, ports and wires survive save and load
- growing the argument list keeps every wire; shrinking drops only the wire whose
  argument has gone; the output stays connected throughout
- `models/shaikh_monetary_policy.py` produces results identical to the last digit
- both suites in this repository pass
