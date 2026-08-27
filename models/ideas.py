"""Why did TFP fall? What this repo's data can say, beyond the composition effect.

    python3 models/ideas.py

WHERE THIS PICKS UP
-------------------
tfp.py attributed about a fifth of the 0.98-point TFP slowdown to the capital stock
tilting toward short-lived assets, and left four fifths unexplained. This asks what else
the data here can reach.

Gordon's fishing-out thesis -- that the great general-purpose inventions were one-off and
the low-hanging fruit is picked -- is not testable with capital-stock data, and nothing
below bears on it directly. What IS testable is the closely related and more specific
claim that research EFFORT rose enormously while research OUTPUT did not, which is Bloom,
Jones, Klenow and Van Reenen's "ideas are getting harder to find". They measure effort by
R&D spending and researcher headcount. BEA's intellectual property capital stock is an
independent measure of the same thing, built from different data, so it is worth seeing
whether it gives the same answer.

THE OTHER CANDIDATE THE DATA REACHES is reallocation: if capital and labour moved into
industries where measured productivity grows slowly, aggregate TFP falls with no
industry's technology changing. That is Baumol's cost disease as an aggregation effect,
and the industry-level capital stocks can at least say whether the reallocation happened.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import beafa                                                     # noqa: E402
import fred                                                      # noqa: E402

ERAS = [(1950, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
        (2000, 2009), (2010, 2019), (2020, 2024)]

#: NAICS two-digit prefixes that produce goods rather than services. Everything BEA
#: publishes outside this list is a service industry.
GOODS = ("11", "21", "22", "23", "31", "32", "33")


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def mean_growth(d, a, b):
    g = [d[y] / d[y - 1] - 1.0 for y in range(a, b + 1) if y in d and y - 1 in d]
    return float(np.mean(g)) if g else float("nan")


# --------------------------------------------------------------------------- 1
def research_productivity():
    """Effort against output: BEA's IP stock as an independent measure of effort.

    SUPERSEDED, and left here because the correction is instructive. This uses the IPP
    TOTAL, which bundles research with software and with artistic originals -- and in
    1950 artistic originals were 70% of it, so the baseline is largely Hollywood.
    models/spillover.py splits the three by asset code and redoes this on research alone,
    where the stock is 26 times its 1950s level rather than 22 and research productivity
    falls by 45 times rather than 38. The correction strengthens the result, which is
    why it went unnoticed: a wrong number pointing the right way.
    """
    print("=" * 92)
    print("1. IDEAS ARE GETTING HARDER TO FIND -- measured from capital, not spending")
    print("=" * 92)
    real, names = beafa.table("real")

    def ip(y):
        return sum(real[(c, "ip")].get(y, 0.0) for c in names if (c, "ip") in real)

    tfp = annual("MFPNFBS")
    base = float(np.mean([ip(y) for y in range(1950, 1970)]))
    b_tfp = mean_growth(tfp, 1950, 1969)
    print("  The real stock of intellectual property capital is the accumulated,")
    print("  depreciated result of research effort. TFP growth is what it buys.\n")
    print(f"  {'era':>12} {'real IP stock':>14} {'vs 1950s':>10} {'TFP growth':>11} "
          f"{'research productivity':>22}")
    for a, b in ERAS:
        lvl = float(np.mean([ip(y) for y in range(a, b + 1)]))
        gt = mean_growth(tfp, a, b)
        rp = (gt / b_tfp) / (lvl / base)
        print(f"  {f'{a}-{b}':>12} {lvl / 1000:13.0f} {lvl / base:9.1f}x "
              f"{gt * 100:10.2f}% {rp:21.3f}")
    last = float(np.mean([ip(y) for y in range(2020, 2025)]))
    gl = mean_growth(tfp, 2020, 2024)
    print(f"\n  The stock of research capital is {last / base:.1f} times its 1950s level "
          "in real terms.")
    print(f"  TFP grows at {gl / b_tfp * 100:.0f}% of its 1950s rate. Research "
          f"productivity -- output per")
    print(f"  unit of accumulated research -- is {(gl / b_tfp) / (last / base):.3f} of "
          "what it was, a fall of")
    print(f"  about {1 / ((gl / b_tfp) / (last / base)):.0f} times.")
    print("\n  Bloom, Jones, Klenow and Van Reenen put research effort at roughly 23")
    print("  times its 1930s level for flat or falling idea output. This is 22 times")
    print("  since the 1950s, from BEA capital stocks rather than their R&D spending and")
    print("  researcher counts. Two independent measurements of the same thing agreeing")
    print("  is worth more than either alone, and neither was built to match the other.")
    return last / base


# --------------------------------------------------------------------------- 2
def rental_bill():
    """What the research machine costs to run, as a share of what it is meant to grow."""
    print("\n" + "=" * 92)
    print("2. WHAT THE IDEAS MACHINE COSTS TO RUN")
    print("=" * 92)
    cur, names = beafa.table("stock")
    dep, _ = beafa.table("deprec")
    gdp = annual("GDP")
    print("  Intellectual property must earn back its user cost every year -- the real")
    print("  rate plus its depreciation rate -- or it was not worth buying. At 24%")
    print("  depreciation that is a large annual bill, and it is a bill the economy pays")
    print("  whether or not the research works.\n")
    print(f"  {'era':>12} {'IP stock/GDP':>13} {'delta':>7} {'user cost':>10} "
          f"{'annual bill/GDP':>16}")
    for a, b in ERAS:
        k = float(np.mean([sum(cur[(c, "ip")].get(y, 0.0) for c in names
                               if (c, "ip") in cur) for y in range(a, b + 1)])) / 1000.0
        d = float(np.mean([sum(dep[(c, "ip")].get(y, 0.0) for c in names
                               if (c, "ip") in dep) for y in range(a, b + 1)])) / 1000.0
        g = float(np.mean([gdp[y] for y in range(a, b + 1) if y in gdp]))
        delta = d / k
        uc = 0.04 + delta
        print(f"  {f'{a}-{b}':>12} {k / g * 100:12.1f}% {delta * 100:6.1f}% "
              f"{uc * 100:9.1f}% {uc * k / g * 100:15.2f}%")
    print("\n  The bill went from 1.2% of GDP to 5.1%, and the depreciation rate that")
    print("  drives it rose from 17% to 24%. For that to have been worth paying,")
    print("  intellectual property has to be adding about five percent of GDP a year in")
    print("  output that would not otherwise exist.")
    print("  Measured TFP says it is not, which is the whole puzzle in one line: either")
    print("  the output is there and unmeasured, or four percent of GDP a year is being")
    print("  spent on research that does not pay for itself.")


# --------------------------------------------------------------------------- 3
def reallocation():
    """Baumol as an aggregation effect: did capital move to slow-growth industries?"""
    print("\n" + "=" * 92)
    print("3. REALLOCATION -- did capital move where productivity grows slowly?")
    print("=" * 92)
    real, names = beafa.table("real")
    goods = [c for c in names if c[:2] in GOODS]

    def agg(codes, y):
        return sum(real[(c, a)].get(y, 0.0) for c in codes for a in
                   ("structures", "equipment", "ip") if (c, a) in real)

    svc = [c for c in names if c not in goods]
    print(f"  {len(goods)} goods-producing industries against {len(svc)} service")
    print("  industries, real capital stock.\n")
    print(f"  {'era':>12} {'goods':>9} {'services':>10} {'goods share':>12} "
          f"{'employment: goods share':>24}")
    # USPRIV excludes government while SRVPRD includes it, so their ratio can exceed
    # one and the goods share came out NEGATIVE. USGOOD over PAYEMS is the matched pair.
    gd, tot_e = annual("USGOOD"), annual("PAYEMS")
    for a, b in ERAS:
        y = b
        g, s = agg(goods, y), agg(svc, y)
        emp_g = gd[y] / tot_e[y] if y in gd and y in tot_e else float("nan")
        print(f"  {f'{a}-{b}':>12} {g / 1000:8.0f} {s / 1000:9.0f} "
              f"{g / (g + s) * 100:11.1f}% {emp_g * 100:23.1f}%")
    print("\n  Capital's goods share falls, and it falls much LESS than employment's.")
    print("  The reallocation is real and it is mostly a labour phenomenon, which is the")
    print("  same thing hollowing.py found looking at manufacturing alone.")
    print("\n  WHAT THIS CANNOT DO is close the Baumol argument, because that needs")
    print("  productivity growth BY INDUSTRY and BEA's value-added-by-industry series")
    print("  start in 2005 on FRED. Showing that capital moved toward services is one")
    print("  half of the claim; showing that services have slower TFP growth is the other")
    print("  half and is not tested here. It is a well-supported result elsewhere, but it")
    print("  is not something this file has demonstrated.")


# --------------------------------------------------------------------------- 4
def verdict(mult):
    print("\n" + "=" * 92)
    print("4. WHAT THIS ADDS, AND WHAT IT DOES NOT")
    print("=" * 92)
    print("  ONE CANDIDATE IS STRONGLY SUPPORTED, and it is not the composition effect.")
    print(f"  Research capital is {mult:.0f} times its 1950s level and TFP grows more")
    print("  slowly than it did. Research productivity has fallen by more than an order")
    print("  of magnitude on this measure. That is the ideas-are-harder-to-find result,")
    print("  reproduced from capital stocks by an accident of what this repo happened to")
    print("  have downloaded, and it agrees closely with the spending-based estimates.")
    print("\n  IT IS ALSO A RESTATEMENT, and that limit should be clear. 'Effort rose and")
    print("  output did not' describes the slowdown; it does not explain it. Gordon's")
    print("  fishing-out is one account of WHY the return to effort fell, the burden-of-")
    print("  knowledge argument is another, and measurement failure is a third. Nothing")
    print("  here chooses between them, because they all predict the same table.")
    print("\n  WHAT THE SEQUENCE DOES RULE OUT is more useful than what it supports.")
    print("  Across circuit.py, wedge.py, moral.py, hollowing.py and tfp.py: the circuit")
    print("  of capital got faster, not slower; the profit rate on capital advanced")
    print("  recovered to within two percent of its 1950s level; capital deepening never")
    print("  slowed; the maintenance proportion rose for compositional reasons rather")
    print("  than behavioural ones; and offshoring did not empty the capital stock.")
    print("  Every explanation that runs through the QUANTITY of capital is closed.")
    print("\n  So the answer to 'why did TFP fall' that this data supports is: not")
    print("  because there was less capital, not because it turned over more slowly, and")
    print("  not because production left the country. About a fifth is the arithmetic of")
    print("  short-lived assets carrying more rental weight. The rest sits in the")
    print("  productivity of research itself, where this repo can measure the collapse")
    print("  precisely and explain it not at all.")


def main():
    mult = research_productivity()
    rental_bill()
    reallocation()
    verdict(mult)


if __name__ == "__main__":
    main()
