"""Is it distribution, and if so distribution of what?

    python3 models/share.py

THE CLAIM TO TEST
-----------------
felt.py and anchors.py converged on distribution: the median household captures 30% less
of GDP per capita than in 1984, and had it kept pace it would have outrun even the anchor
bundle. The natural reading is that workers have been getting less than their share.

That reading is directionally right and too simple, because at least three quite different
things sit inside the 30 points and they have different remedies:

    CAPITAL VS LABOUR      the share of income going to work rather than to ownership
    TOP VS THE REST        the share of labour income going to the highest-paid
    NOT DISTRIBUTION       household size fell, so a household measure understates what
                           happened to a person

The third is not a distributional fact at all and it is worth about a third of the gap.
Separating them is the point of this file.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

BASE = 1984
MARKS = (1984, 1990, 2000, 2010, 2019, 2024)


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
        "wshare": "W270RE1A156NBEA",     # wage and salary share of gross domestic income
        "supp": "A038RC1A027NBEA",       # supplements: employer benefits
        "wages": "A576RC1A027NBEA",      # wages and salaries
        "lshare": "PRS85006173",         # nonfarm business labour share, index 2017=100
        "comp": "COMPNFB",               # compensation per hour, ALL workers
        "ahe": "AHETPI",                 # hourly wage, production and nonsupervisory
        "medwk": "LES1252881600Q",       # median usual weekly earnings, real
        "medhh": "MEHOINUSA672N", "medpers": "MEPAINUSA672N",
        "gdpc": "A939RX0Q048SBEA", "cpi": "CPIAUCSL",
        "shelter": "CUSR0000SAH1", "medical": "CPIMEDSL", "tuition": "CUUR0000SEEB",
    }.items()}


# --------------------------------------------------------------------------- 1
def capital_vs_labour(d):
    print("=" * 92)
    print("1. CAPITAL VERSUS LABOUR")
    print("=" * 92)
    print("  The wage and salary share of gross domestic income, and the same with")
    print("  employer-paid benefits added back, since benefits are compensation that a")
    print("  money-income measure never sees.\n")
    print(f"  {'year':>6} {'wage share of GDI':>19} {'with benefits':>15} "
          f"{'nonfarm labour share':>22}")
    for y in MARKS:
        ws, su, wg = d["wshare"].get(y), d["supp"].get(y), d["wages"].get(y)
        ls = d["lshare"].get(y)
        tot = f"{ws * (1 + su / wg):14.1f}%" if all((ws, su, wg)) else f"{'--':>15}"
        print(f"  {y:6d} {ws:18.1f}% {tot} {ls:21.1f}")
    a, b = d["wshare"][BASE], d["wshare"][2024]
    la, lb = d["lshare"][BASE], d["lshare"][2024]
    print(f"\n  The wage share fell {a:.1f}% to {b:.1f}%, which is "
          f"{(b / a - 1) * 100:.1f}% of itself.")
    print(f"  The nonfarm business labour share index fell {(lb / la - 1) * 100:.1f}%.")
    print("\n  So labour did lose ground to capital, by something between 8 and 11 percent")
    print("  over forty years. Real, and nowhere near thirty points. The benefits column")
    print("  matters here: a good deal of what employers pay went into health insurance")
    print("  rather than wages, and money-income measures record none of it.")
    return b / a - 1


# --------------------------------------------------------------------------- 2
def top_vs_rest(d):
    print("\n" + "=" * 92)
    print("2. THE TOP VERSUS EVERYONE ELSE")
    print("=" * 92)
    print("  Compensation per hour covers ALL workers, so it carries executives and the")
    print("  highly paid. Average hourly earnings covers production and nonsupervisory")
    print("  workers only, about four fifths of employment. The ratio is the top pulling")
    print("  away. Real, 1984 = 100.\n")
    print(f"  {'year':>6} {'comp/hr, all':>14} {'wage/hr, production':>21} "
          f"{'median weekly':>15} {'ratio':>8}")
    for y in MARKS:
        c = (d["comp"][y] / d["cpi"][y]) / (d["comp"][BASE] / d["cpi"][BASE]) * 100
        a = (d["ahe"][y] / d["cpi"][y]) / (d["ahe"][BASE] / d["cpi"][BASE]) * 100
        m = d["medwk"][y] / d["medwk"][BASE] * 100
        print(f"  {y:6d} {c:13.1f} {a:20.1f} {m:14.1f} {c / a:7.2f}x")
    c = (d["comp"][2024] / d["cpi"][2024]) / (d["comp"][BASE] / d["cpi"][BASE])
    a = (d["ahe"][2024] / d["cpi"][2024]) / (d["ahe"][BASE] / d["cpi"][BASE])
    print(f"\n  All-worker compensation per hour grew {(c / a - 1) * 100:.0f}% more than "
          "production-worker wages.")
    print("  That is the largest single distributional term in this file, and it is")
    print("  inside labour rather than between labour and capital.")
    print("\n  AND THE MIDDLE DID NOT FALL BEHIND THE TYPICAL. Median full-time weekly")
    print("  earnings rose 117.9 against production wages at 117.6 -- the same, to a")
    print("  tenth. The dispersion that opened is between the top and everyone else, not")
    print("  between the middle and the bottom, and that is a different problem with a")
    print("  different remedy.")
    return c / a - 1


# --------------------------------------------------------------------------- 3
def households(d):
    print("\n" + "=" * 92)
    print("3. THE THIRD OF IT THAT IS NOT DISTRIBUTION AT ALL")
    print("=" * 92)
    print("  Median HOUSEHOLD income against median PERSONAL income. Households got")
    print("  smaller, so the same person is spread across a smaller household and the")
    print("  household measure understates what happened to them.\n")
    print(f"  {'year':>6} {'median household':>18} {'median person':>15} {'gap':>8}")
    for y in (1984, 1990, 2000, 2010, 2019, 2024):
        h = d["medhh"][y] / d["medhh"][BASE] * 100
        p = d["medpers"][y] / d["medpers"][BASE] * 100
        print(f"  {y:6d} {h:17.1f} {p:14.1f} {p - h:+7.1f}")
    print("\n  Real median personal income is up 61% since 1984. Real median household")
    print("  income is up 39%. The 22-point difference is household composition, and it")
    print("  is not a distributional fact -- nobody took it from anyone.")
    print("\n  It matters both ways, though, and this is worth being careful about. A")
    print("  smaller household needs less food and less clothing. It needs the same")
    print("  house. So the per-person measure flatters and the per-household measure")
    print("  overstates, and the truth about the anchors sits between them.")


# --------------------------------------------------------------------------- 4
def the_gap(d):
    print("\n" + "=" * 92)
    print("4. THE GAP, MEASURED THREE WAYS")
    print("=" * 92)
    m = lambda k, y=2024: d[k][y] / d[k][BASE]                   # noqa: E731
    cpi = m("cpi")
    g = m("gdpc") * cpi
    hh = m("medhh") * cpi
    pe = m("medpers") * cpi
    anchor = 0.45 * m("shelter") + 0.30 * m("medical") + 0.25 * m("tuition")
    print(f"  {'':>32} {'multiple':>10} {'vs GDP/capita':>15} {'vs anchors':>12}")
    print(f"  {'GDP per capita':>32} {g:9.2f}x {'--':>15} {'--':>12}")
    print(f"  {'anchor bundle':>32} {anchor:9.2f}x {anchor / g - 1:+14.1%} {'--':>12}")
    print(f"  {'median HOUSEHOLD income':>32} {hh:9.2f}x {hh / g - 1:+14.1%} "
          f"{hh / anchor - 1:+11.1%}")
    print(f"  {'median PERSONAL income':>32} {pe:9.2f}x {pe / g - 1:+14.1%} "
          f"{pe / anchor - 1:+11.1%}")
    print("\n  THIS QUALIFIES felt.py AND anchors.py, which both used the household")
    print("  measure. On a per-person basis the median fell 8% short of the anchor")
    print("  bundle over forty years, not 21%. The direction of those files survives and")
    print("  the magnitude does not: the squeeze is real and about a third smaller than")
    print("  the household series makes it look.")
    return hh / g - 1, pe / g - 1


# --------------------------------------------------------------------------- 5
def verdict(lab, top, gaps):
    print("\n" + "=" * 92)
    print("5. VERDICT")
    print("=" * 92)
    hh, pe = gaps
    print(f"  YES, IT IS DISTRIBUTION -- and it is three things, not one.\n")
    print(f"  {'household size, not distribution at all':>44}  about 11 of the 30 points")
    print(f"  {'the top pulling away from other workers':>44}  the largest real term, "
          f"{top * 100:.0f}%")
    print(f"  {'capital taking more than labour':>44}  real but smaller, 8 to 11%")
    print("\n  The ordering matters for what would fix it. If the problem were mainly")
    print("  capital versus labour, the remedies are bargaining power, unionisation, and")
    print("  the taxation of ownership. That term is real and it is the SMALLEST of the")
    print("  three. The larger distributional term is inside labour -- the highest-paid")
    print("  pulling away from everyone else -- which those remedies barely touch.")
    print("\n  AND ONE FINDING CUTS AGAINST THE FRAMING ENTIRELY. The median full-time")
    print("  worker's earnings tracked the typical production worker's almost exactly,")
    print("  117.9 against 117.6 over forty years. The middle did not fall behind the")
    print("  bottom. Whatever happened, it did not happen between ordinary workers.")
    print("\n  So 'workers have been getting less than their fair share' is right about")
    print("  the direction and wrong about the shape. Ordinary workers lost ground to")
    print("  the top far more than labour as a whole lost ground to capital, and a third")
    print("  of what looks like loss is households getting smaller. The felt decline is")
    print("  real, it is smaller than the household series suggests, and most of it is a")
    print("  gap that opened inside the wage distribution rather than across it.")


def main():
    d = load()
    lab = capital_vs_labour(d)
    top = top_vs_rest(d)
    households(d)
    gaps = the_gap(d)
    verdict(lab, top, gaps)


if __name__ == "__main__":
    main()
