"""Is the TFP slowdown Baumol's cost disease?

    python3 models/baumol.py

THE QUESTION
------------
productive.py found that commodity production kept cheapening its output -- durable goods
prices peaked in 1995 and have fallen 32% in nominal terms since, against services up
twelvefold from 1960 -- while goods fell from 53.5% of consumption to 31.5%. That invites
the reading that aggregate TFP fell because the weight moved onto a sector where
productivity grows slowly, which is Baumol.

Baumol is a claim about REALLOCATION, and reallocation can be measured. Hold the
progressive sector's share of employment at its 1960s level, recompute the aggregate with
each era's own within-sector growth rates, and the difference is the pure composition
effect. Everything else is the sectors themselves slowing down, which is not Baumol.

TWO TRAPS, AND THE FIRST ONE INVERTS THE ANSWER
-----------------------------------------------
NBER-CES TFP is GROSS-OUTPUT based; BLS multifactor productivity is VALUE-ADDED based.
Gross-output TFP growth is smaller by roughly the value-added share, which in
manufacturing is about 0.44. Compared raw, manufacturing TFP growth reads 1.05% against
an aggregate of 1.90% in the 1960s and manufacturing looks like the LAGGING sector, which
would refute Baumol before it starts. Divided by the value-added share it is 2.30% and
leads. The conversion is done here and the raw series shown beside it.

Second, manufacturing TFP growth is famously carried by computers and semiconductors,
whose hedonic deflators make their real output growth enormous. Section 3 removes NAICS
334 and the picture changes a great deal in the middle decades.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402
import nberces                                                   # noqa: E402

ERAS = [(1960, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
        (2000, 2009), (2010, 2016)]


def annual(sid):
    s = fred.series(sid)
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def mfg_tfp(d, exclude=()):
    """Value-added-basis manufacturing TFP growth, {year: rate}.

    dtfp5 is gross-output based, so it is divided by the value-added share to be
    comparable with a value-added aggregate. Weighted by value added across industries.
    """
    out = {}
    for y in range(1959, 2017):
        num = den = va = go = 0.0
        for (i, yy), r in d.items():
            if yy != y or i in exclude:
                continue
            va += r["vadd"]
            go += r["vship"]
            if r.get("dtfp5") is None:
                continue
            num += r["vadd"] * r["dtfp5"]
            den += r["vadd"]
        if den and go:
            out[y] = (num / den) / (va / go)
    return out


def mean(d, a, b):
    v = [d[y] for y in range(a, b + 1) if y in d]
    return float(np.mean(v)) if v else float("nan")


def agg_growth(agg, a, b):
    v = [agg[y] / agg[y - 1] - 1.0 for y in range(a, b + 1)
         if y in agg and y - 1 in agg]
    return float(np.mean(v)) if v else float("nan")


# --------------------------------------------------------------------------- 1
def units(d, agg):
    print("=" * 92)
    print("1. THE CONVERSION THAT DECIDES THE SIGN")
    print("=" * 92)
    raw = {}
    for y in range(1959, 2017):
        num = den = 0.0
        for (i, yy), r in d.items():
            if yy != y or r.get("dtfp5") is None:
                continue
            num += r["vadd"] * r["dtfp5"]
            den += r["vadd"]
        if den:
            raw[y] = num / den
    va = mfg_tfp(d)
    print("  Manufacturing TFP growth on both bases, against the value-added aggregate.\n")
    print(f"  {'era':>12} {'gross-output':>13} {'VA/GO':>7} {'value-added':>12} "
          f"{'BLS aggregate':>14} {'lead':>7}")
    for a, b in ERAS:
        g, v = mean(raw, a, b), mean(va, a, b)
        ratio = g / v if v else float("nan")
        ga = agg_growth(agg, a, b)
        print(f"  {f'{a}-{b}':>12} {g * 100:12.2f}% {ratio:7.3f} {v * 100:11.2f}% "
              f"{ga * 100:13.2f}% {(v - ga) * 100:+6.2f}")
    print("\n  On the raw gross-output numbers manufacturing trails the aggregate in the")
    print("  1960s and Baumol is refuted on the first line. Converted, it leads by 0.40")
    print("  points and leads by more later. Same data, opposite conclusion, and the")
    print("  difference is a units convention.")
    return va


# --------------------------------------------------------------------------- 2
def decompose(va, agg, memp, emp):
    print("\n" + "=" * 92)
    print("2. WHERE THE SLOWDOWN SITS")
    print("=" * 92)
    print("  Non-manufacturing is the residual: (aggregate - share x manufacturing)")
    print("  over the remaining share. It therefore absorbs every measurement error in")
    print("  both series, and is the weakest number here.\n")
    print(f"  {'era':>12} {'manufacturing':>14} {'non-mfg (resid)':>16} "
          f"{'aggregate':>10} {'mfg emp share':>14}")
    rows = {}
    for a, b in ERAS:
        gm, ga = mean(va, a, b), agg_growth(agg, a, b)
        sh = float(np.mean([memp[y] / emp[y] for y in range(a, b + 1)]))
        gr = (ga - sh * gm) / (1 - sh)
        rows[(a, b)] = (gm, gr, ga, sh)
        print(f"  {f'{a}-{b}':>12} {gm * 100:13.2f}% {gr * 100:15.2f}% "
              f"{ga * 100:9.2f}% {sh * 100:13.1f}%")
    f, l = rows[ERAS[0]], rows[ERAS[-1]]
    print(f"\n  Manufacturing {f[0] * 100:.2f}% -> {l[0] * 100:.2f}%, essentially "
          f"unchanged over 56 years.")
    print(f"  Non-manufacturing {f[1] * 100:.2f}% -> {l[1] * 100:.2f}%, down "
          f"{(f[1] - l[1]) * 100:.2f} points.")
    print(f"  Its employment share went {f[3] * 100:.1f}% -> {100 - l[3] * 100:.1f}% "
          "of the economy.")
    print("\n  On these numbers the slowdown is entirely outside manufacturing. The")
    print("  commodity-producing sector never slowed; everything that went wrong went")
    print("  wrong in services. Section 3 is why that should not be believed as stated.")
    return rows


# --------------------------------------------------------------------------- 3
def computers(d):
    print("\n" + "=" * 92)
    print("3. HOW MUCH OF MANUFACTURING IS COMPUTERS")
    print("=" * 92)
    allm, ex = mfg_tfp(d), mfg_tfp(d, exclude=("334",))
    print("  NAICS 334 is computers and electronic products, whose hedonic deflators")
    print("  make measured real output growth very large. Removing it:\n")
    print(f"  {'era':>12} {'all mfg':>9} {'ex 334':>9} {'334 contributes':>17} "
          f"{'334 share of VA':>16}")
    for a, b in ERAS:
        x, z = mean(allm, a, b), mean(ex, a, b)
        y = b
        tot = sum(r["vadd"] for (i, yy), r in d.items() if yy == y)
        v3 = sum(r["vadd"] for (i, yy), r in d.items() if yy == y and i == "334")
        print(f"  {f'{a}-{b}':>12} {x * 100:8.2f}% {z * 100:8.2f}% "
              f"{(x - z) * 100:+16.2f} {v3 / tot * 100:15.1f}%")
    print("\n  In the 1990s a seventh of manufacturing value added supplied 2.15 of its")
    print("  2.60 points. Manufacturing's productivity lead over the rest of the economy")
    print("  in that decade was almost entirely one industry with an unusual deflator.")
    print("\n  Section 2's clean story -- manufacturing flat, services collapsing -- does")
    print("  not survive this. Excluding computers, manufacturing TFP growth runs 2.21%,")
    print("  0.66%, 0.37%, 0.45%, -1.44%, 2.11% by decade: volatile, mostly low, and with")
    print("  a 2010-16 rebound on seven years that should not be leaned on.")
    return ex


# --------------------------------------------------------------------------- 4
def counterfactual(va, ex, agg, memp, emp):
    print("\n" + "=" * 92)
    print("4. THE BAUMOL QUESTION, ANSWERED TWICE")
    print("=" * 92)
    print("  Hold manufacturing's employment share at its 1960s level and recompute the")
    print("  aggregate with each era's own within-sector rates. The gap is reallocation")
    print("  and nothing else.\n")
    sh60 = float(np.mean([memp[y] / emp[y] for y in range(1960, 1970)]))
    for label, series in (("ALL MANUFACTURING", va), ("EXCLUDING COMPUTERS", ex)):
        print(f"  {label}  (1960s share {sh60 * 100:.1f}%)")
        print(f"    {'era':>10} {'actual':>9} {'counterfactual':>15} "
              f"{'reallocation':>13}")
        for a, b in ERAS:
            gm, ga = mean(series, a, b), agg_growth(agg, a, b)
            sh = float(np.mean([memp[y] / emp[y] for y in range(a, b + 1)]))
            gr = (ga - sh * gm) / (1 - sh)
            cf = sh60 * gm + (1 - sh60) * gr
            print(f"    {f'{a}-{b}':>10} {ga * 100:8.2f}% {cf * 100:14.2f}% "
                  f"{(ga - cf) * 100:+12.2f}")
        print()
    total = agg_growth(agg, 1960, 1969) - agg_growth(agg, 2010, 2016)
    print(f"  The total slowdown to be explained is {total * 100:.2f} points.")
    print("  Reallocation costs 0.31 points in 2010-16 on all manufacturing and 0.29")
    print("  excluding computers -- about a quarter either way, and the two agree in the")
    print("  final era because manufacturing's measured lead is similar there with or")
    print("  without 334. They diverge badly in the middle decades, where the sign even")
    print("  flips in 2000-09, so a quarter is the right order and not a firm figure.")


# --------------------------------------------------------------------------- 5
def verdict():
    print("\n" + "=" * 92)
    print("5. VERDICT")
    print("=" * 92)
    print("  PARTLY, AND ABOUT A QUARTER AT MOST.")
    print("\n  Baumol's mechanism is reallocation toward a sector where productivity grows")
    print("  slowly, and that is measurable rather than arguable. Holding manufacturing's")
    print("  employment share at its 1960s level recovers 0.31 points of a 1.20-point")
    print("  slowdown, or 0.29 with computers removed from manufacturing. So roughly a")
    print("  quarter, and the era-by-era path is unstable enough that a quarter is an")
    print("  order of magnitude rather than an estimate.")
    print("\n  THE OTHER THREE QUARTERS IS NOT REALLOCATION. It is the sectors themselves")
    print("  slowing, and overwhelmingly the non-manufacturing sector, whose implied TFP")
    print("  growth falls from about 1.8% to about 0.6%. That is not Baumol -- Baumol's")
    print("  services grow slowly and CONSTANTLY, dragging the average as their weight")
    print("  rises. These services got slower. A constant drag cannot produce an")
    print("  accelerating one.")
    print("\n  AND THE RESIDUAL IS THE WEAKEST NUMBER IN THE FILE. Non-manufacturing is")
    print("  computed as what is left after subtracting manufacturing from the aggregate,")
    print("  using two TFP series built by different people on different methods with a")
    print("  units conversion in between. Every error in either lands there. The direction")
    print("  is probably right; the magnitude should not be quoted.")
    print("\n  SO THE ANSWER TO THE QUESTION AS ASKED: no, the TFP decline is not")
    print("  measuring Baumol's disease, though a quarter of it may be. The larger part is")
    print("  a genuine slowdown in productivity growth outside manufacturing, which is")
    print("  where this repo's earlier findings already pointed -- research moved there,")
    print("  the capital stock moved there, and the output is hardest to measure there.")
    print("  Naming it Baumol would file it as solved when it is the thing still to")
    print("  explain.")


def main():
    d = nberces.by3()
    agg, memp, emp = (annual("MFPNFBS"), annual("MANEMP"), annual("PAYEMS"))
    va = units(d, agg)
    decompose(va, agg, memp, emp)
    ex = computers(d)
    counterfactual(va, ex, agg, memp, emp)
    verdict()


if __name__ == "__main__":
    main()
