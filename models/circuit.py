"""Has the circuit of capital slowed, and would it explain the stagnation?

    python3 models/circuit.py

THE QUESTION
------------
turnover.py section 5 established three things about turnover and growth: it works
exactly for a single capital, it is a genuine CEILING for an economy (g <= alpha*e*n_agg,
never violated), and it is a poor predictor because the same aggregate turnover supports
growth from 10% to 45%. So "the West stagnated because the circuit slowed" is a real
hypothesis with a real mechanism, and it is testable rather than rhetorical.

It needs two things to be true, and they are independent:

    1. the circuit actually lengthened
    2. that lengthening accounts for a material share of the fall in growth

THE DECOMPOSITION THAT DECIDES IT
---------------------------------
Growth of capital is accumulation over capital advanced, and that factors exactly:

    g = alpha * s/K = alpha * (s/GVA) * (GVA/K)
              accumulation rate  profit share  output-capital ratio

The third term IS the turnover measure -- how much product a unit of advanced capital
turns out in a year, which is Marx's n_agg with surplus left in. If the circuit slowed,
GVA/K fell, and the hypothesis says that is where the growth went. If instead the fall
sits in alpha or the profit share, the circuit is not the story however much it moved.

MEASUREMENT
-----------
US nonfinancial corporate business, Z.1 for the stocks and NIPA for the flows, because
the two are defined on the same sector. NIPA's own decomposition of gross value added
is already Marx's:

    GVA = consumption of fixed capital + compensation + net operating surplus + taxes
        =            c                +      v       +          s           + taxes

which is the reproduction schemes' c + v + s with a tax line the schemes do not have.
Intermediate inputs net out of value added, which is exactly what the schemes do when
Dept I's purchases from itself are consolidated away.

THE VALUATION CAVEAT, STATED UP FRONT
-------------------------------------
The Z.1 nonfinancial assets series is at MARKET value, so it carries land and property
revaluation that has nothing to do with how fast anything turns over. That inflates K and
depresses GVA/K in any period when property is expensive, which is most of the sample
after 1995. Section 2 therefore reports the equipment-only current-cost series alongside,
where no revaluation is possible, and the two are allowed to disagree.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

#: (id, scale to $bn). Z.1 levels are $mn, NIPA flows are $bn.
SERIES = {
    "K_nonfin": ("BOGZ1LM102010005Q", 1e-3),   # nonfinancial assets, MARKET value
    "equip": ("BOGZ1FL105013265Q", 1e-3),      # equipment, current cost -- no revaluation
    "inven": ("IABSNNCB", 1e-3),               # inventories, current cost
    "recv": ("TRABSNNCB", 1e-3),               # trade receivables
    "pay": ("TPLBSNNCB", 1e-3),                # trade payables
    "GVA": ("A455RC1Q027SBEA", 1.0),           # gross value added
    "CFC": ("B456RC1Q027SBEA", 1.0),           # consumption of fixed capital  = c
    "comp": ("A460RC1Q027SBEA", 1.0),          # compensation of employees     = v
    "surp": ("W326RC1Q027SBEA", 1.0),          # net operating surplus         = s
    "tax": ("W325RC1Q027SBEA", 1.0),           # taxes on production
    "defl": ("GDPDEF", 1.0),                   # to take the inflation out of growth
}


def panel():
    """One row per quarter where every series exists."""
    raw = {}
    for k, (sid, sc) in SERIES.items():
        s = fred.series(sid)
        if s is None:
            raise SystemExit(f"could not fetch {sid} for {k}")
        d = {}
        for dt, v in zip(s["date"], s["value"]):
            y, mo = int(dt[:4]), int(dt[5:7])
            d[(y, (mo - 1) // 3 + 1)] = v * sc
        raw[k] = d
    keys = sorted(set.intersection(*(set(v) for v in raw.values())))
    rows = []
    for k in keys:
        r = {n: raw[n][k] for n in raw}
        r["key"], r["label"] = k, f"{k[0]}Q{k[1]}"
        # fixed capital excludes inventories, which do not depreciate
        r["K_fix"] = r["K_nonfin"] - r["inven"]
        # capital ADVANCED in the circuit: productive assets, stocks of goods, and the
        # net credit extended to customers, which is capital tied up exactly as Marx's
        # circulation time says it is
        r["K_adv"] = r["K_nonfin"] + r["recv"] - r["pay"]
        rows.append(r)
    return rows


def era(rows, a, b):
    """Mean of each field over calendar years [a, b]."""
    sel = [r for r in rows if a <= r["key"][0] <= b]
    if not sel:
        return None
    out = {k: float(np.mean([r[k] for r in sel]))
           for k in sel[0] if k not in ("key", "label")}
    out["label"] = f"{a}-{b}"
    out["n"] = len(sel)
    return out


ERAS = [(1955, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
        (2000, 2009), (2010, 2019), (2020, 2026)]


# --------------------------------------------------------------------------- 1
def circulating(rows):
    """Did the circulating part of the circuit lengthen? Days, which is Marx's unit."""
    print("=" * 92)
    print("1. THE CIRCULATING CIRCUIT -- inventories, receivables, payables, in days")
    print("=" * 92)
    print("  Marx's turnover time is production time plus circulation time. The modern")
    print("  accounting name for the same quantity is the cash conversion cycle: days of")
    print("  stock, plus days waiting to be paid, less days before paying suppliers.")
    print("  Days are taken against gross value added, so the LEVELS are not comparable")
    print("  to a firm's own figures -- only the trend is being read.\n")
    print(f"  {'era':>10} {'invent':>8} {'receiv':>8} {'payable':>8} {'cycle':>8} "
          f"{'vs 1955-69':>11}")
    base = None
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        di = 365.0 * m["inven"] / m["GVA"]
        dr = 365.0 * m["recv"] / m["GVA"]
        dp = 365.0 * m["pay"] / m["GVA"]
        cc = di + dr - dp
        if base is None:
            base = cc
        print(f"  {m['label']:>10} {di:8.1f} {dr:8.1f} {dp:8.1f} {cc:8.1f} "
              f"{cc - base:+10.1f}d")
    print("\n  Read the inventory column first: that is the part of the circuit that")
    print("  everyone agrees was transformed, by containerisation, by just-in-time, and")
    print("  by the computerisation of the supply chain.")


# --------------------------------------------------------------------------- 2
def fixed_turnover(rows):
    """And the fixed part -- did capital lives lengthen? CFC/K_fix is 1/L."""
    print("\n" + "=" * 92)
    print("2. THE FIXED CIRCUIT -- how long does fixed capital now last?")
    print("=" * 92)
    print("  Consumption of fixed capital over the fixed capital stock IS 1/L, the")
    print("  reciprocal of the average service life. Reported on the market-value stock")
    print("  and on equipment at current cost, because the first carries property")
    print("  revaluation and the second cannot.\n")
    print(f"  {'era':>10} {'CFC/K_fix':>10} {'implied L':>10} | {'CFC/equip':>10} "
          f"{'implied L':>10} | {'CFC/GVA':>9}")
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        d1 = m["CFC"] / m["K_fix"]
        d2 = m["CFC"] / m["equip"]
        print(f"  {m['label']:>10} {d1 * 100:9.2f}% {1 / d1:10.1f}y | "
              f"{d2 * 100:9.2f}% {1 / d2:10.1f}y | {m['CFC'] / m['GVA'] * 100:8.2f}%")
    print("\n  The two disagree in level by construction -- equipment is a subset of the")
    print("  stock, so CFC over it is far too high to be a service life. The TREND is the")
    print("  claim, and CFC/GVA is the version with no stock in it at all.")


# --------------------------------------------------------------------------- 3
def decompose(rows):
    """g = alpha * (s/GVA) * (GVA/K). An exact decomposition in logs, so it adds up."""
    print("\n" + "=" * 92)
    print("3. THE DECOMPOSITION -- where the profit rate on capital advanced went")
    print("=" * 92)
    print("    s/K = (s/GVA) * (GVA/K)      profit share times the turnover measure\n")
    print(f"  {'era':>10} {'profit share':>13} {'GVA/K_adv':>10} {'s/K_adv':>9} "
          f"{'from share':>11} {'from turnover':>14}")
    base = None
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        ps, ok = m["surp"] / m["GVA"], m["GVA"] / m["K_adv"]
        sk = ps * ok
        if base is None:
            base = (ps, ok, sk)
            print(f"  {m['label']:>10} {ps * 100:12.2f}% {ok:10.4f} {sk * 100:8.2f}% "
                  f"{'--':>11} {'--':>14}")
            continue
        cs = np.log(ps / base[0]) * 100.0
        ct = np.log(ok / base[1]) * 100.0
        print(f"  {m['label']:>10} {ps * 100:12.2f}% {ok:10.4f} {sk * 100:8.2f}% "
              f"{cs:+10.1f}% {ct:+13.1f}%")
    print("\n  The last two columns are log contributions against 1955-69 and add to the")
    print("  total change, so nothing is hidden between them. Turnover DID subtract, and")
    print("  the profit share added more than it took away.")
    print("\n  BUT THAT TURNOVER TERM IS MOSTLY A PRICE. K_adv carries real estate at")
    print("  market value, which revalues for reasons that have nothing to do with how")
    print("  fast anything turns over. Redone against equipment at current cost, where")
    print("  no revaluation is possible:\n")
    print(f"  {'era':>10} {'GVA/K_adv':>10} {'GVA/equip':>10} {'inventories/GVA':>16}")
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        print(f"  {m['label']:>10} {m['GVA'] / m['K_adv']:10.4f} "
              f"{m['GVA'] / m['equip']:10.4f} {m['inven'] / m['GVA']:15.4f}")
    print("\n  The market-value ratio falls and the current-cost one RISES. Sections 1")
    print("  and 2 already said which to believe: stock days fell, capital lives")
    print("  shortened, and nothing measured in physical time got slower. The fall in")
    print("  GVA/K_adv is the price of land and buildings, not the speed of the circuit.")


# --------------------------------------------------------------------------- 4
def bound_is_thin(rows):
    """A correction: the ceiling from turnover.py cannot be used as a diagnostic."""
    print("\n" + "=" * 92)
    print("4. A CORRECTION -- the turnover ceiling has less content than it looked")
    print("=" * 92)
    print("  turnover.py section 5 proved g <= alpha*e*n_agg and called it a ceiling on")
    print("  growth. The inequality is true and the proof stands. But asking how much of")
    print("  it is USED turns out to measure nothing, and the algebra says so:\n")
    print("      g / (alpha*e*n_agg) = (s/K) / ((s/v)*((c+v)/K)) = v / (c + v)\n")
    print("  The slack in the bound is exactly c/(c+v). So the 'fraction of the ceiling")
    print("  used' is the wage share of costs wearing a different hat, and it falls")
    print("  whenever depreciation rises whether or not anything has slowed:\n")
    print(f"  {'era':>10} {'ceiling used':>13} {'v/(c+v)':>9} {'identical?':>11}")
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        e = m["surp"] / m["comp"]
        na = (m["CFC"] + m["comp"]) / m["K_adv"]
        used = (m["surp"] / m["K_adv"]) / (e * na)
        wsh = m["comp"] / (m["CFC"] + m["comp"])
        print(f"  {m['label']:>10} {used * 100:12.1f}% {wsh * 100:8.1f}% "
              f"{'yes' if abs(used - wsh) < 1e-9 else 'NO':>11}")
    print("\n  Identical to every decimal, because it is the same quantity. The ceiling")
    print("  is real -- a slow-turning economy genuinely cannot grow fast -- but it is")
    print("  slack by construction and cannot say whether turnover is what binds.")
    print("  Reported because the first version of this file used it as evidence.")


# --------------------------------------------------------------------------- 5
def accumulation(rows):
    """If the profit rate recovered and growth did not, alpha is what moved."""
    print("\n" + "=" * 92)
    print("5. THE TERM THAT IS LEFT -- what happened to accumulation")
    print("=" * 92)
    print("  g = alpha * s/K. Section 3 has s/K nearly back to its 1950s level. If growth")
    print("  did not come back with it, then alpha did the falling. Real growth of gross")
    print("  value added, nominal less the GDP deflator, against the profit rate:\n")
    print("  WHAT THIS RESIDUAL IS, BEFORE IT IS READ. alpha here is g divided by s/K,")
    print("  so it is not a measurement of the accumulation rate -- it is everything that")
    print("  g and s/K do not share, which includes capacity utilisation, the gap between")
    print("  output growth and capital-stock growth, and every decade-average artefact of")
    print("  a period containing two recessions. 2000-09 reads 0.106 for exactly that")
    print("  reason and should not be read as a decade in which firms reinvested a tenth")
    print("  of profits. The TREND is the claim; no single row is.\n")
    print(f"  {'era':>10} {'real GVA g':>11} {'s/K_adv':>9} {'implied alpha':>14} "
          f"{'vs 1955-69':>11}")
    by_year = {}
    for r in rows:
        by_year.setdefault(r["key"][0], []).append(r)
    base = None
    for a, b in ERAS:
        gs = []
        for y in range(a, b + 1):
            if y - 1 in by_year and y in by_year:
                p0 = float(np.mean([x["GVA"] for x in by_year[y - 1]]))
                p1 = float(np.mean([x["GVA"] for x in by_year[y]]))
                d0 = float(np.mean([x["defl"] for x in by_year[y - 1]]))
                d1 = float(np.mean([x["defl"] for x in by_year[y]]))
                gs.append((p1 / p0) / (d1 / d0) - 1.0)
        m = era(rows, a, b)
        if m is None or not gs:
            continue
        g = float(np.mean(gs))
        sk = m["surp"] / m["K_adv"]
        al = g / sk
        if base is None:
            base = al
        print(f"  {m['label']:>10} {g * 100:10.2f}% {sk * 100:8.2f}% {al:14.3f} "
              f"{(al / base - 1) * 100:+10.1f}%")
    print("\n  That is the answer to the question as asked. The profit rate on capital")
    print("  advanced is within two percent of where it was in 1955-69. Real growth is")
    print("  less than half. Whatever opened between them, it is not the speed of the")
    print("  circuit, because the circuit is faster than it was.")


def main():
    rows = panel()
    print(f"US nonfinancial corporate business, {rows[0]['label']} to "
          f"{rows[-1]['label']}, {len(rows)} quarters")
    print("Z.1 for stocks, NIPA for flows, same sector on both sides.\n")
    circulating(rows)
    fixed_turnover(rows)
    decompose(rows)
    bound_is_thin(rows)
    accumulation(rows)


if __name__ == "__main__":
    main()
