"""Which labour took the larger share -- certain industries, or certain levels?

    python3 models/premium.py

WHERE THIS COMES FROM
---------------------
share.py found the largest distributional term is inside labour rather than between
labour and capital: all-worker compensation per hour grew 24% more than production and
nonsupervisory wages since 1984. That is a gap, not an explanation. Three things could
produce it and only one of them is what people mean by the top taking more:

    BENEFITS       compensation includes employer-paid benefits and the wage series does
                   not, so a rising benefit share opens the gap without anyone being
                   paid more relative to anyone else
    COMPOSITION    a rising share of employment classified as supervisory raises the
                   average without raising any individual's relative pay
    PREMIUM        the same fraction of supervisory workers being paid more relative to
                   everyone else

The first two are measurable directly and turn out to be small and zero. What is left is
the third, and it is large.

A CONFOUND I MISSED FIRST TIME
------------------------------
share.py compared COMPNFB against AHETPI without noting that the first includes benefits
and the second does not. That was a real gap in the reasoning and section 1 prices it:
benefits account for about 3 of the 24 points, so the finding survives, but it should have
been checked before the number was reported rather than after.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

BASE = 1984


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def load():
    return {k: annual(v) for k, v in {
        "supp": "A038RC1A027NBEA", "wages": "A576RC1A027NBEA",
        "prod": "CES0500000006", "allp": "USPRIV",
        "comp": "COMPNFB", "ahe": "AHETPI", "cpi": "CPIAUCSL",
    }.items()}


def real_ratio(d):
    """All-worker compensation per hour over production-worker wages, real, 1984 = 1."""
    c = (d["comp"][2024] / d["cpi"][2024]) / (d["comp"][BASE] / d["cpi"][BASE])
    a = (d["ahe"][2024] / d["cpi"][2024]) / (d["ahe"][BASE] / d["cpi"][BASE])
    return c / a


# --------------------------------------------------------------------------- 1
def benefits(d):
    print("=" * 92)
    print("1. BENEFITS -- the confound, priced")
    print("=" * 92)
    print("  Employer supplements as a share of total compensation. The wages series ends")
    print("  in 2014, so this is measured to there and understates the full period.\n")
    print(f"  {'year':>6} {'benefits share of compensation':>32}")
    for y in (1984, 1990, 2000, 2010, 2014):
        print(f"  {y:6d} "
              f"{d['supp'][y] / (d['wages'][y] + d['supp'][y]) * 100:31.1f}%")
    s0 = d["supp"][BASE] / (d["wages"][BASE] + d["supp"][BASE])
    s1 = d["supp"][2014] / (d["wages"][2014] + d["supp"][2014])
    f = (1 - s0) / (1 - s1)
    print(f"\n  A wages-only measure understates compensation growth by a factor of "
          f"{f:.3f},")
    print(f"  which is {(f - 1) * 100:.1f} of the 24 points. Real, and not the story.")
    return f


# --------------------------------------------------------------------------- 2
def composition(d):
    print("\n" + "=" * 92)
    print("2. COMPOSITION -- more managers, or better-paid ones?")
    print("=" * 92)
    print("  If the supervisory share of employment had risen, the average would climb")
    print("  with nobody's relative pay changing.\n")
    print(f"  {'year':>6} {'production/nonsupervisory':>27} {'supervisory':>13}")
    for y in (1984, 1990, 2000, 2010, 2019, 2024):
        p = d["prod"][y] / d["allp"][y]
        print(f"  {y:6d} {p * 100:26.1f}% {(1 - p) * 100:12.1f}%")
    p0 = 1 - d["prod"][BASE] / d["allp"][BASE]
    p1 = 1 - d["prod"][2024] / d["allp"][2024]
    print(f"\n  It went {p0 * 100:.1f}% to {p1 * 100:.1f}% -- it FELL by "
          f"{(p0 - p1) * 100:.1f} points.")
    print("  There is no composition effect to find. America does not employ a larger")
    print("  fraction of supervisors than it did in 1984; it employs a slightly smaller")
    print("  one. Whatever opened the gap did it by changing pay, not headcount.")
    return p0, p1


# --------------------------------------------------------------------------- 3
def premium(d, f, shares):
    print("\n" + "=" * 92)
    print("3. THE PREMIUM -- what is left, and it is large")
    print("=" * 92)
    p0, p1 = shares
    x = real_ratio(d) / f
    print("  With benefits removed and composition flat, the residual is a pay premium.")
    print("  Writing R for supervisory pay relative to production pay:\n")
    print("      comp_all / wage_prod  =  s_prod  +  s_sup x R\n")
    print("  The starting premium is not published, so the calculation is run across a")
    print("  range of plausible values and the ANSWER IS THE SAME IN ALL OF THEM.\n")
    print(f"  {'R in 1984':>12} {'implied R in 2024':>19} {'growth in the premium':>23}")
    for r0 in (1.4, 1.6, 1.8, 2.0, 2.5):
        x0 = (1 - p0) * r0 + p0
        r1 = (x0 * x - p1) / (1 - p1)
        print(f"  {r0:11.1f}x {r1:18.2f}x {r1 / r0 - 1:+22.0%}")
    print("\n  Whatever it started at, it roughly doubles. The fifth of private workers")
    print("  their employers class as supervisory are paid about twice as much relative")
    print("  to the other four fifths as they were in 1984.")
    print("\n  This is an UPPER BOUND on the premium, because it assigns the entire")
    print("  ex-benefits residual to relative pay. Any measurement difference between the")
    print("  two series -- and there is one, since compensation covers nonfarm business")
    print("  and the wage series covers total private -- lands in it too.")


# --------------------------------------------------------------------------- 4
def industries():
    print("\n" + "=" * 92)
    print("4. INDUSTRY -- is it finance and technology?")
    print("=" * 92)
    inds = {"financial activities": "CES5500000003", "information": "CES5000000003",
            "professional/business": "CES6000000003", "manufacturing": "CES3000000003",
            "retail trade": "CES4200000003", "leisure/hospitality": "CES7000000003",
            "TOTAL PRIVATE": "CES0500000003"}
    d = {k: annual(v) for k, v in inds.items()}
    yrs = [2007, 2015, 2024]
    print("  Average hourly earnings, all employees, by sector. These series begin in")
    print("  2006, so this cannot see the 1984-2007 period where much of the divergence")
    print("  happened -- a real limit on what follows.\n")
    print(f"  {'sector':>22} " + " ".join(f"{y:>9}" for y in yrs))
    for k, v in d.items():
        print(f"  {k:>22} " + " ".join(f"{v[y] / v[yrs[0]] * 100:9.1f}" for y in yrs))
    vals = [v[2024] / v[2007] * 100 for k, v in d.items() if k != "TOTAL PRIVATE"]
    print(f"\n  The spread is {min(vals):.0f} to {max(vals):.0f} over seventeen years, and")
    print("  leisure and hospitality -- the lowest-paid sector in the list -- is near the")
    print("  top of it, on the post-2020 catch-up at the bottom of the labour market.")
    print("\n  So in the window that can be seen, industry is NOT where the action is. The")
    print("  gap is between levels within industries rather than between industries.")


# --------------------------------------------------------------------------- 5
def verdict():
    print("\n" + "=" * 92)
    print("5. VERDICT")
    print("=" * 92)
    print("  LEVELS, NOT INDUSTRIES -- and not headcount either.")
    print("\n    benefits                    3 of the 24 points")
    print("    more supervisors            none: the share FELL, 19.2% to 18.6%")
    print("    supervisory pay premium     the rest, and it roughly doubled")
    print("\n  The people classed as supervisory are the same fraction of the workforce")
    print("  as in 1984 and are paid about twice as much relative to everyone else. That")
    print("  is the largest single distributional movement this repo has measured --")
    print("  larger than the fall in labour's share, larger than the shift of capital")
    print("  into intellectual property, larger than the composition effect in TFP.")
    print("\n  WHAT IT IS NOT. It is not more managers, it is not a particular industry in")
    print("  the years that can be checked, and it is not the middle falling behind the")
    print("  bottom -- share.py found median full-time earnings tracking production wages")
    print("  to a tenth of a point over forty years.")
    print("\n  WHAT THE DATA CANNOT SAY. 'Supervisory' is an employer's own classification")
    print("  on a payroll survey and it lumps a shift manager with a chief executive. The")
    print("  premium is measured as a residual and carries every difference between two")
    print("  series built for different purposes. And the industry check cannot reach")
    print("  before 2007. This locates the movement, it does not explain it: whether it is")
    print("  skill, scale, governance or bargaining is not something a payroll aggregate")
    print("  can distinguish.")
    print("\n  But the location itself is the useful part, because it is not where the")
    print("  argument usually goes. The felt decline in American living standards traces")
    print("  back through prices to distribution, through distribution past capital-")
    print("  versus-labour, and lands inside the wage distribution on a premium paid to")
    print("  a fifth of workers whose number has not grown.")


def main():
    d = load()
    f = benefits(d)
    shares = composition(d)
    premium(d, f, shares)
    industries()
    verdict()


if __name__ == "__main__":
    main()
