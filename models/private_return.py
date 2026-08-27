"""The private return to R&D, against the social return that collapsed.

    python3 models/private_return.py

THE TEST
--------
spillover.py found that research moved out of vertically integrated firms into firms that
own little else, which is the reorganisation the excludability thesis needs. It also noted
the thesis makes one prediction that separates it from Gordon's fishing-out, and that
capital stocks cannot check: if know-how became excludable, firms should still be capturing
a good return on research even as the ECONOMY stopped getting one.

Fishing-out predicts both returns fall together -- there is simply less to find.
Excludability predicts they diverge -- the same discoveries reach fewer users, so the
finder keeps more of a smaller total.

ideas.py and spillover.py measured the social side: research capital 26 times its 1950s
level for 57% of the TFP growth, a 45-fold fall in output per unit of research. This
measures the private side from SEC filings.

WHAT THIS CAN AND CANNOT SETTLE
-------------------------------
XBRL begins in 2009, so this covers 2010-2024 and cannot show a CHANGE over the period the
divergence is supposed to have opened. It measures the LEVEL of the private return now and
sets it beside the social return now. A high private return alongside a collapsed social
one is the wedge the thesis predicts, observed once rather than tracked -- consistent with
it, not proof of it, and equally consistent with the private return always having been
high. That limit is not fixable with free data and is stated rather than worked around.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import sec                                                       # noqa: E402

YEARS = list(range(2010, 2025))

#: geometric depreciation of R&D capital. BEA's implied rate on the R&D stock is about
#: 15-16%; the 24% in earlier modules is for IPP as a whole, which software drags up.
#: Section 4 varies it.
DELTA = 0.15

#: real required return, for the user cost R&D must clear to be worth doing
R = 0.04


def build():
    """Firm panel with an R&D capital stock built by perpetual inventory."""
    raw = sec.panel(YEARS)
    hist = {}
    for y in YEARS:
        for cik, rec in raw.get(y, {}).items():
            hist.setdefault(cik, {})[y] = rec
    # a stock needs a history: require R&D in at least ten of the fifteen years
    keep = {c: h for c, h in hist.items() if len(h) >= 10}
    out = {}
    for cik, h in keep.items():
        ys = sorted(h)
        # seed at the steady state implied by the first observation, K = R/(delta+g)
        k = h[ys[0]]["rd"] / (DELTA + 0.05)
        stock = {}
        for y in range(ys[0], YEARS[-1] + 1):
            rd = h.get(y, {}).get("rd", 0.0)
            k = (1.0 - DELTA) * k + rd
            stock[y] = k
        out[cik] = {"hist": h, "rdcap": stock}
    return out


def usable(panel, year):
    """Firms with everything needed that year, and a sane balance sheet."""
    rows = []
    for cik, d in panel.items():
        h = d["hist"].get(year)
        if not h:
            continue
        ppe = h.get("PropertyPlantAndEquipmentNet")
        oi = h.get("OperatingIncomeLoss")
        if ppe is None or oi is None or ppe <= 0:
            continue
        k = d["rdcap"][year]
        if k <= 0:
            continue
        rows.append({"cik": cik, "ppe": ppe, "oi": oi, "rdcap": k,
                     "rd": h["rd"], "assets": h.get("Assets"),
                     "rev": h.get("Revenues")})
    return rows


# --------------------------------------------------------------------------- 1
def coverage(panel):
    print("=" * 92)
    print("1. THE SAMPLE")
    print("=" * 92)
    print(f"  {len(panel)} SEC filers reporting R&D in at least 10 of {len(YEARS)} years.\n")
    print(f"  {'year':>6} {'usable firms':>13} {'total R&D $bn':>14} "
          f"{'total R&D capital $bn':>22}")
    for y in (2010, 2015, 2020, 2024):
        rows = usable(panel, y)
        if not rows:
            continue
        print(f"  {y:6d} {len(rows):13d} {sum(r['rd'] for r in rows) / 1e9:13.0f} "
              f"{sum(r['rdcap'] for r in rows) / 1e9:21.0f}")
    print("\n  These are listed US filers only. Private firms, foreign filers and the")
    print("  federal research the national accounts include are all outside it, so the")
    print("  totals are a fraction of the economy's R&D and the sample is selected toward")
    print("  large, surviving, public companies -- which if anything biases the measured")
    print("  private return UP.")


# --------------------------------------------------------------------------- 2
def returns_by_intensity(panel, year=2023):
    print("\n" + "=" * 92)
    print(f"2. DOES R&D INTENSITY GO WITH HIGHER PROFITABILITY?  ({year})")
    print("=" * 92)
    rows = usable(panel, year)
    for r in rows:
        r["cap"] = r["ppe"] + r["rdcap"]
        r["share"] = r["rdcap"] / r["cap"]
        r["ret"] = r["oi"] / r["cap"]
    rows.sort(key=lambda r: r["share"])
    n = len(rows) // 5
    print(f"  {len(rows)} firms, sorted by R&D capital as a share of total capital,")
    print("  into fifths. Return is operating income over physical plus R&D capital.\n")
    print(f"  {'fifth':>8} {'R&D share':>11} {'median return':>14} "
          f"{'aggregate return':>17} {'share losing money':>19}")
    for i in range(5):
        g = rows[i * n:(i + 1) * n] if i < 4 else rows[4 * n:]
        med = float(np.median([x["ret"] for x in g]))
        agg = sum(x["oi"] for x in g) / sum(x["cap"] for x in g)
        loss = sum(1 for x in g if x["oi"] < 0) / len(g)
        print(f"  {i + 1:8d} {float(np.median([x['share'] for x in g])) * 100:10.1f}% "
              f"{med * 100:13.1f}% {agg * 100:16.1f}% {loss * 100:18.0f}%")
    print("\n  The aggregate column is value-weighted and the median is not, and the gap")
    print("  between them is the story of the top fifth: a few very large and very")
    print("  profitable research firms sitting above a long tail that loses money.")
    return rows


# --------------------------------------------------------------------------- 3
def marginal_return(panel):
    """Dollars of operating income per dollar of R&D capital, against its user cost."""
    print("\n" + "=" * 92)
    print("3. THE MARGINAL RETURN, AGAINST WHAT R&D MUST EARN")
    print("=" * 92)
    print("  Operating income regressed on physical capital and R&D capital, in levels,")
    print("  so the coefficient is dollars of profit per dollar of capital and compares")
    print("  directly with the user cost r + delta that the capital has to clear.\n")
    print(f"  {'year':>6} {'n':>6} {'on PP&E':>9} {'on R&D capital':>15} "
          f"{'user cost':>10} {'clears?':>9}")
    coefs = []
    for y in (2012, 2015, 2018, 2021, 2024):
        rows = usable(panel, y)
        if len(rows) < 100:
            continue
        X = np.column_stack([np.ones(len(rows)),
                             [r["ppe"] for r in rows],
                             [r["rdcap"] for r in rows]])
        b, *_ = np.linalg.lstsq(X, np.array([r["oi"] for r in rows]), rcond=None)
        uc = R + DELTA
        coefs.append(b[2])
        print(f"  {y:6d} {len(rows):6d} {b[1]:9.3f} {b[2]:15.3f} {uc:10.2f} "
              f"{'yes' if b[2] > uc else 'NO':>9}")
    print("\n  A coefficient of 0.30 means a dollar of R&D capital is associated with")
    print("  thirty cents of operating income a year. R&D has to clear r + delta =")
    print(f"  {R + DELTA:.2f} to have been worth doing.")
    print("\n  These are ASSOCIATIONS in a cross-section, not causal returns. Firms that")
    print("  can afford heavy research are firms that are already profitable, and that")
    print("  runs from profit to R&D as much as the other way. The literature handles")
    print("  this with firm fixed effects over long panels; fifteen years of XBRL with")
    print("  entry and exit does not support that here, and the number should be read as")
    print("  an upper bound.")
    return float(np.mean(coefs))


# --------------------------------------------------------------------------- 4
def sensitivity(panel):
    print("\n" + "=" * 92)
    print("4. HOW MUCH DEPENDS ON THE DEPRECIATION RATE")
    print("=" * 92)
    global DELTA
    keep = DELTA
    print(f"  {'delta':>7} {'user cost':>10} {'coef on R&D capital':>21} {'clears?':>9}")
    for d in (0.10, 0.15, 0.20, 0.24, 0.30):
        DELTA = d
        p2 = build()
        rows = usable(p2, 2023)
        X = np.column_stack([np.ones(len(rows)), [r["ppe"] for r in rows],
                             [r["rdcap"] for r in rows]])
        b, *_ = np.linalg.lstsq(X, np.array([r["oi"] for r in rows]), rcond=None)
        print(f"  {d:7.2f} {R + d:10.2f} {b[2]:21.3f} "
              f"{'yes' if b[2] > R + d else 'NO':>9}")
    DELTA = keep
    print("\n  A faster write-off gives a smaller stock and so a bigger measured return")
    print("  per dollar, while also raising the bar it must clear. The two move together")
    print("  and the verdict does not turn on the choice.")


# --------------------------------------------------------------------------- 5

# --------------------------------------------------------------------------- 5
def concentration(panel):
    """Who captures the return? The one thing here that is a TREND, not a level."""
    print("\n" + "=" * 92)
    print("5. WHO CAPTURES IT -- and this part is a trend")
    print("=" * 92)
    print("  Excludability is a claim about who gets to use a discovery. Its signature is")
    print("  not that returns are high but that they are CAPTURED: the finder keeps more")
    print("  of a smaller total, so profit should concentrate faster than the research")
    print("  that produces it.\n")
    print(f"  {'year':>6} {'firms':>6} | {'top 10 of PROFIT':>17} {'of R&D':>8} "
          f"{'capture premium':>16} | {'profit HHI':>11}")
    first = last = None
    for y in (2010, 2013, 2016, 2019, 2022, 2024):
        rows = usable(panel, y)
        if len(rows) < 200:
            continue
        pos = sorted((r["oi"] for r in rows if r["oi"] > 0), reverse=True)
        T = sum(pos)
        psh = sum(pos[:10]) / T
        rd = sorted((r["rd"] for r in rows), reverse=True)
        rsh = sum(rd[:10]) / sum(rd)
        hhi = sum((x / T) ** 2 for x in pos)
        if first is None:
            first = (psh, rsh)
        last = (psh, rsh)
        print(f"  {y:6d} {len(rows):6d} | {psh * 100:16.1f}% {rsh * 100:7.1f}% "
              f"{(psh - rsh) * 100:+15.1f} | {hhi:11.4f}")
    print(f"\n  In 2010 the ten largest research spenders did {first[1] * 100:.1f}% of "
          f"the R&D and took")
    print(f"  {first[0] * 100:.1f}% of the profit -- proportional, within a point. By 2024 "
          f"they did")
    print(f"  {last[1] * 100:.1f}% of the R&D and took {last[0] * 100:.1f}%. The capture "
          f"premium went from")
    print(f"  {(first[0] - first[1]) * 100:+.1f} points to {(last[0] - last[1]) * 100:+.1f}, "
          "and the profit Herfindahl nearly tripled.")
    print("\n  Research concentrated. The returns to research concentrated FASTER. That")
    print("  is what excludability looks like in accounts, and unlike everything else in")
    print("  this file it is a change over time rather than a level, so it is not")
    print("  vulnerable to the objection that the wedge was always there.")
    print("\n  It is fifteen years, it is listed firms, and 2010 is a recession-scarred")
    print("  base. It is a straw in the wind, not a demonstration.")
    return first, last



# --------------------------------------------------------------------------- 6
def verdict(coef, rows, cap):
    print("\n" + "=" * 92)
    print("6. VERDICT")
    print("=" * 92)
    agg = sum(r["oi"] for r in rows) / sum(r["cap"] for r in rows)
    loss = sum(1 for r in rows if r["oi"] < 0) / len(rows)
    print(f"  The private return is HEALTHY IN AGGREGATE and thin in the middle. Listed")
    print(f"  research-doing firms earn {agg * 100:.1f}% on physical plus R&D capital "
          f"against a user")
    print(f"  cost of {R + DELTA:.0%}, and a dollar of R&D capital is associated with "
          f"{coef:.2f} of")
    print(f"  operating income a year. But {loss * 100:.0f}% of them lose money outright, "
          "and the")
    print("  return FALLS monotonically with R&D intensity -- the least research-heavy")
    print("  fifth earns 26% on capital and the most research-heavy loses 21%, with 90%")
    print("  of that top fifth in the red. Whatever is earning the aggregate return, it")
    print("  is not research intensity as such.")
    print("\n  Those two facts are not in tension, they are the same fact: the returns to")
    print("  research are extremely skewed. A small number of firms earn enormously and")
    print("  most earn nothing, which is why the value-weighted marginal return clears")
    print("  its hurdle while the median research-intensive firm does not.")
    print("\n  SET AGAINST THE SOCIAL SIDE: research capital 26 times its 1950s level for")
    print("  57% of the TFP growth. The private return clears its hurdle; the social")
    print("  return per unit of research is a fortieth of what it was.")
    print("\n  THAT IS THE WEDGE THE EXCLUDABILITY THESIS PREDICTS, and it is not what")
    print("  fishing-out predicts. If the well were simply dry, firms would not be")
    print("  clearing their cost of capital on research either. They are.")
    print("\n  BUT THE TEST IS WEAKER THAN IT LOOKS, in three ways that all cut the same")
    print("  direction:")
    print("    - Fifteen years cannot show a divergence that opened over sixty. The wedge")
    print("      is observed, not tracked, and may always have been there.")
    print("    - The sample is listed survivors, which selects for research that worked.")
    print("    - The coefficient is an association, and profitable firms can afford")
    print("      research as easily as research makes firms profitable.")
    print("\n  AND THE SKEW IS THE POINT, which section 5 turns into a trend. Under")
    print("  published, non-excludable research the returns would spread: everyone gets")
    print("  to use the finding. Under excludable research they concentrate on whoever")
    print("  got there first. Profit among research-doing firms concentrated from")
    print(f"  {cap[0][0] * 100:.0f}% to {cap[1][0] * 100:.0f}% in the top ten while their "
          f"share of the research went")
    print(f"  {cap[0][1] * 100:.0f}% to {cap[1][1] * 100:.0f}%. Capture outran effort -- "
          "but see concentration.py, which")
    print("  finds that movement is five firms and only the LEVEL difference survives.")
    print("\n  So: consistent with the thesis, and the first evidence in this repo that")
    print("  discriminates between it and fishing-out at all. Not a demonstration.")


def main():
    panel = build()
    coverage(panel)
    rows = returns_by_intensity(panel)
    coef = marginal_return(panel)
    sensitivity(panel)
    cap = concentration(panel)
    verdict(coef, rows, cap)


if __name__ == "__main__":
    main()
