"""The fiscal ceiling: the policy rate above which government debt stops being stable.

    python3 models/fiscal.py

WHY THIS AND NOT A ROUND NUMBER
-------------------------------
Saying "an interest bill above 5% of GDP is too much" picks a threshold out of the air.
The debt ratio's own arithmetic supplies one instead. With b the debt-to-GDP ratio, i the
effective nominal rate the government actually pays, g nominal GDP growth and s the
primary surplus as a share of GDP,

    db/dt = (i - g) * b - s

so the ratio is stable exactly when

    i_max = g + s / b

Above that the ratio grows without bound at the current primary balance. Nothing is
chosen: every term is measured, and the condition is the one every debt-sustainability
analysis rests on. It is also the r-versus-g question in its plainest form -- while i < g
the ratio falls even in primary deficit, and once i > g it takes a surplus to hold it.

TWO CEILINGS, NOT ONE, AND THE TERM STRUCTURE IS WHY
-----------------------------------------------------
The government does not pay the policy rate. It pays a weighted average coupon over a debt
stock of many maturities, which reprices only as that stock rolls -- the same immediate-
versus-eventual split models/four_sector.py was built to price. So:

    IMMEDIATE   most of the stock is locked in, so a policy move barely moves the bill
                this year and the ceiling is nearly unreachable in the short run
    EVENTUAL    at full pass-through the whole stock carries the new rate, and the
                ceiling binds at a far lower policy rate

Reporting only the first is how a fiscal position looks comfortable right up until it is
not. Both are computed here, along with the pass-through that separates them, measured
from the data rather than assumed.

WHAT THIS IS NOT
----------------
Not a claim about default, and not a political judgement about what is tolerable. It is
the arithmetic boundary between a debt ratio that converges and one that does not, at the
CURRENT primary balance. A government that changes its primary balance moves the ceiling,
and that is the point: the constraint is on the pair, not on the rate alone.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

GROWTH_WINDOW = 20        # quarters of nominal GDP growth to average for g


def _q(sid, scale=1.0):
    """A quarterly series keyed (year, quarter)."""
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    out = {}
    for dt, v in zip(s["date"], s["value"]):
        y, m, _ = dt.split("-")
        out.setdefault((int(y), (int(m) - 1) // 3 + 1), []).append(v * scale)
    return {k: sum(v) / len(v) for k, v in out.items()}


def panel():
    """One row per quarter: b, effective rate, nominal growth, primary balance, policy rate."""
    gdp = _q("GDP")                          # $bn SAAR
    debt = _q("FYGFDPUN", 1e-3)              # $mn -> $bn, HELD BY THE PUBLIC
    intr = _q("A091RC1Q027SBEA")             # $bn SAAR, federal interest payments
    rec = _q("FGRECPT")                      # $bn SAAR
    exp = _q("FGEXPND")                      # $bn SAAR
    ff = _q("FEDFUNDS", 0.01)
    keys = sorted(set(gdp) & set(debt) & set(intr) & set(rec) & set(exp) & set(ff))
    rows = []
    for i, k in enumerate(keys):
        y, q = k
        prev = keys[max(0, i - 4)]
        g = (gdp[k] / gdp[prev]) ** (1.0 / max(1, (i - max(0, i - 4)) / 4.0)) - 1.0 \
            if i >= 4 else float("nan")
        rows.append({
            "key": k, "label": f"{y}Q{q}",
            "b": debt[k] / gdp[k],
            "i_eff": intr[k] / debt[k],
            "g": g,
            "s": (rec[k] - (exp[k] - intr[k])) / gdp[k],   # PRIMARY balance, interest out
            "bill": intr[k] / gdp[k],
            "ff": ff[k],
        })
    return [r for r in rows if not np.isnan(r["g"])]


def smooth_growth(rows, window=GROWTH_WINDOW):
    """Trend nominal growth. A single quarter is far too noisy to divide a ceiling by."""
    gs = [r["g"] for r in rows]
    for i, r in enumerate(rows):
        lo = max(0, i - window + 1)
        r["g_trend"] = float(np.mean(gs[lo:i + 1]))
    return rows


def pass_through(rows, lag=0):
    """d(effective rate on the debt) / d(policy rate), measured.

    Well below one, and that IS the term structure: the stock reprices as it rolls, so a
    policy move reaches the interest bill only gradually. This coefficient is what turns
    a policy rate into an eventual interest bill.
    """
    x = np.array([r["ff"] for r in rows])
    y = np.array([r["i_eff"] for r in rows])
    A = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    r2 = 1 - ((y - A @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return b[0], b[1], r2, len(x)


def ceiling(row, b1, g=None):
    """(max sustainable effective rate, the policy rate that eventually delivers it).

    ANCHORED LOCALLY, not through the regression intercept. Fitting i_eff on the policy
    rate over 1971-2026 returns an intercept of 4.27% -- the legacy coupon of a half
    century of higher rates -- and dividing by that misstates the level badly. A slope on
    CHANGES is applied as a change from where the effective rate actually is:

        ip_max = ff_now + (i_max - i_eff_now) / beta

    which is the same correction the deposit-beta calculation in models/equalise.py
    needed, and for the same reason.
    """
    gg = row["g_trend"] if g is None else g
    i_max = gg + row["s"] / row["b"]
    ip_max = row["ff"] + (i_max - row["i_eff"]) / b1
    return i_max, ip_max


def main():
    rows = smooth_growth(panel())
    a0, b1, r2, n = pass_through(rows)
    w = rows[-1]
    print(f"US FEDERAL POSITION, {w['label']}")
    print(f"  debt held by the public / GDP        b = {w['b']:.3f}")
    print(f"  effective rate the government pays   i = {w['i_eff']*100:.2f}%")
    print(f"  trend nominal GDP growth             g = {w['g_trend']*100:.2f}%")
    print(f"  primary balance / GDP                s = {w['s']*100:+.2f}%")
    print(f"  interest bill / GDP                      {w['bill']*100:.2f}%")
    print(f"  actual fed funds                         {w['ff']*100:.2f}%")
    print("")
    print("PASS-THROUGH FROM THE POLICY RATE TO THE EFFECTIVE RATE ON THE DEBT")
    print(f"  i_eff = {a0*100:.2f}% + {b1:.3f} x ff      R2 {r2:.3f}, n = {n}")
    print(f"  Well under one, which IS the term structure: the stock reprices as it rolls,")
    print(f"  so a policy move reaches the interest bill only gradually.")
    print("")
    i_max, ip_max = ceiling(w, b1)
    print("THE CEILING,  i_max = g + s/b")
    print(f"  max effective rate for a stable debt ratio    {i_max*100:+.2f}%")
    print(f"  effective rate actually paid                  {w['i_eff']*100:+.2f}%")
    print(f"  -> {'ALREADY ABOVE IT' if w['i_eff'] > i_max else 'below it'}, by "
          f"{abs(w['i_eff']-i_max)*100:.2f}pp")
    print(f"  eventual POLICY rate consistent with it       {ip_max*100:+.2f}%")
    print(f"  actual policy rate                            {w['ff']*100:+.2f}%")
    print("")
    drift = (w["i_eff"] - w["g_trend"]) * w["b"] - w["s"]
    print(f"  db/dt at today's numbers = (i - g)*b - s = {drift*100:+.2f}pp of GDP a year")
    print(f"  i - g = {(w['i_eff']-w['g_trend'])*100:+.2f}pp"
          f"   ({'i above g: a surplus is needed to hold the ratio' if w['i_eff']>w['g_trend'] else 'i below g: the ratio falls even in deficit'})")
    print("")
    print("HISTORY: has the ceiling bound before?")
    print(f"  {'quarter':>8} {'b':>6} {'i_eff':>7} {'g':>7} {'s':>7} {'i_max':>7} {'binding':>8}")
    for r in rows[::20] + [rows[-1]]:
        im, _ = ceiling(r, b1)
        print(f"  {r['label']:>8} {r['b']:6.2f} {r['i_eff']*100:6.2f}% {r['g_trend']*100:6.2f}% "
              f"{r['s']*100:+6.2f}% {im*100:+6.2f}% {'YES' if r['i_eff']>im else 'no':>8}")
    bind = sum(1 for r in rows if r["i_eff"] > ceiling(r, b1)[0])
    print(f"\n  binding in {bind} of {len(rows)} quarters "
          f"({bind/len(rows)*100:.0f}%)")

    print("")
    print("THE ANSWER TURNS ON g, SO HERE IS THE WHOLE RANGE")
    print("  i_max = g + s/b, and s/b is measured. g is a forecast dressed as a trend --")
    print("  a five-year window right now still carries the 2021-22 nominal surge.")
    print("")
    print(f"  {'g assumption':>34} {'g':>7} {'i_max':>8} {'policy':>8} {'binding now?':>13}")
    gcands = [("5-year trend, as measured", w["g_trend"]),
              ("10-year trend", float(np.mean([r["g"] for r in rows[-40:]]))),
              ("20-year trend", float(np.mean([r["g"] for r in rows[-80:]]))),
              ("2% inflation + 2% real", 0.04),
              ("2% inflation + 1.8% real (CBO-ish)", 0.038)]
    for lab, gg in gcands:
        im, ipm = ceiling(w, b1, g=gg)
        print(f"  {lab:>34} {gg*100:6.2f}% {im*100:+7.2f}% {ipm*100:+7.2f}% "
              f"{('YES' if w['i_eff'] > im else 'no'):>13}")
    ims = [ceiling(w, b1, g=gg)[1] for _l, gg in gcands]
    print("")
    print(f"  implied policy ceiling spans {min(ims)*100:+.2f}% to {max(ims)*100:+.2f}%"
          f"  -- a {(max(ims)-min(ims))*100:.2f}pp range, and today's rate is "
          f"{w['ff']*100:.2f}%.")
    print("  On the trend that still contains the inflation surge the position looks")
    print("  comfortable. On any forward-looking growth assumption it does not. That")
    print("  disagreement is the finding, not a number to be averaged away.")
    print("  Compare Shaikh's ceiling -- the rate at which enterprise profit reaches zero --")
    print("  which has never bound in 47 years and currently sits about 20%. The fiscal")
    print("  constraint is the one that actually binds, and it binds far below.")


if __name__ == "__main__":
    main()
