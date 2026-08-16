# The logo is a model run

The **M** in the masthead and the favicon is not a drawing of a chart. It is a chart:
the raw trajectory of **net investment (`I_n`) in `MinskyNonLinear`**, over the window
**t = 6.404 to 12.130**, plotted with time on the x axis and nothing else done to it.

Open the model, run it to t=12, and put `I_n` on a plot. The logo is on screen.

```
model      MinskyNonLinear.mky      (ships with Minsky, in minsky/examples)
variable   I_n                      net investment
window     t 6.404 .. 12.130        one full period either side of the middle trough
samples    410 raw -> 31 after simplification (Ramer-Douglas-Peucker, eps 0.004)
peaks      48.8692 and 48.8632      symmetry 0.9999
```

## Why this model and this variable

The obvious candidates do not work. The employment rate in `GoodwinLinear` and the prey
population in `PredatorPrey` both oscillate, but *smoothly*: two periods of a near-sine
read as **two humps**, not as a letter. A letterform M needs steep, near-straight strokes
and sharp vertices.

`MinskyNonLinear`'s investment variables are **relaxation oscillations** rather than
sinusoids -- they climb steeply, peak sharply and fall away -- so two periods give an M
with real corners. `I_g` (gross investment) and `g_r` (growth rate) also work; `I_n` has
the cleanest valley.

The two shoulders come out level on their own. It is a limit cycle, so successive peaks
are identical by construction -- 48.8692 against 48.8632 -- and nothing had to be
stretched or straightened to make the letter balance.

## Regenerating it

`tools/logo_path.py` re-runs the model and prints the SVG path. It takes no arguments and
depends only on `pyminsky`:

```
python3 tools/logo_path.py                  # the path used in index.html
python3 tools/logo_path.py --variable I_g   # a different candidate
python3 tools/logo_path.py --raw            # every sample, unsimplified
```

The path is inlined twice in `minskyweb/ui/index.html` -- once in the `<link rel="icon">`
data URI and once in the masthead `<svg class="logo">`. If you regenerate it, replace
both.

## Using it

- The stroke has to stay heavy. The middle valley is the first thing to close up as the
  mark gets smaller; at favicon size the stroke is `16` against a 200x120 viewBox.
- `overflow: visible` on the `<svg>` matters. The stroke is centred on the path, so half
  of it sits outside the viewBox at the feet and the peaks, and it gets clipped otherwise.
- The mark carries no colour of its own -- it inherits `--ink` -- so it works on either
  theme without a second file.
