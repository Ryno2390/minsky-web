"""Did offshoring drive the shift into intellectual property, or did technology?

    python3 models/hollowing.py

THE TWO STORIES
---------------
wedge.py found that intellectual property carries more than the whole rise in the
aggregate depreciation rate, and moral.py argued that is what accelerating obsolescence
looks like when it cannot shorten the life of capital that already wears out fast. That
is a technology story and it is not the only candidate.

The hollowing-out story says the same shift is a consequence of offshoring: US firms
moved physical production to lower-wage countries and kept design and intellectual
property at home, so the DOMESTIC capital stock tilted toward IP because the machinery
left the country rather than because IP became more important to production.

Both predict the observed composition. They are separable on two things they do not
share:

    TIMING   offshoring is datable. NAFTA 1994, China's WTO accession 2001, and the
             import surge that followed. If most of the IP shift predates that, the
             offshoring story cannot be carrying it.

    WHAT MOVED  offshoring removes PRODUCTION, so it should hollow out the physical
             capital stock, not merely change its composition. Technology changes what
             is bought without anyone leaving.

WHAT THIS CANNOT DO
-------------------
BEA publishes fixed assets by industry, and FRED does not carry those series, so the
cleanest test -- manufacturing's own capital stock and its own IP share -- is not
available here. What follows uses economy-wide asset composition against sectoral
employment and trade, which is weaker, and the verdict is hedged accordingly.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

CLASSES = [("structures", "K1NTOTL1ST000"), ("equipment", "K1NTOTL1EQ000"),
           ("IP products", "K1NTOTL1IP000")]


def annual(sid, scale=1.0):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v * scale)
    return {y: float(np.mean(v)) for y, v in by.items()}


def load():
    K = {nm: annual(sid, 1e-3) for nm, sid in CLASSES}
    d = {"manemp": annual("MANEMP"), "emp": annual("PAYEMS"),
         "imports": annual("IMPGS"), "gdp": annual("GDP")}
    # manufacturing value added as a share of GDP starts only in 2005 on FRED, so it is
    # a lookup rather than part of the intersection -- including it truncated the whole
    # panel to 2005 and silently destroyed the timing test this module exists for.
    manva = annual("VAPGDPMA")
    years = sorted(set.intersection(*(set(v) for v in K.values()),
                                    *(set(v) for v in d.values())))
    rows = []
    for y in years:
        tot = sum(K[nm][y] for nm, _ in CLASSES)
        rows.append({"year": y, "tot": tot,
                     **{f"sh_{nm}": K[nm][y] / tot for nm, _ in CLASSES},
                     "manshare": d["manemp"][y] / d["emp"][y],
                     "imp_gdp": d["imports"][y] / d["gdp"][y],
                     "manva": manva.get(y, float("nan")) / 100.0})
    return rows


# --------------------------------------------------------------------------- 1
def timing(rows):
    print("=" * 92)
    print("1. TIMING -- when did the IP shift happen, and when did offshoring?")
    print("=" * 92)
    print(f"  {'year':>6} {'IP share':>9} {'equip share':>12} {'struct share':>13} | "
          f"{'mfg emp share':>14} {'imports/GDP':>12} {'mfg VA/GDP':>11}")
    for y in (1960, 1970, 1980, 1990, 1994, 2001, 2010, 2019, rows[-1]["year"]):
        r = next((x for x in rows if x["year"] == y), None)
        if r is None:
            continue
        mark = ""
        if y == 1994:
            mark = "  <- NAFTA"
        if y == 2001:
            mark = "  <- China joins the WTO"
        mv = f"{r['manva'] * 100:.1f}%" if np.isfinite(r["manva"]) else "--"
        print(f"  {y:6d} {r['sh_IP products'] * 100:8.1f}% {r['sh_equipment'] * 100:11.1f}% "
              f"{r['sh_structures'] * 100:12.1f}% | {r['manshare'] * 100:13.1f}% "
              f"{r['imp_gdp'] * 100:11.1f}% {mv:>10}{mark}")
    a = next(x for x in rows if x["year"] == 1960)
    b = next(x for x in rows if x["year"] == 2001)
    c = rows[-1]
    total = c["sh_IP products"] - a["sh_IP products"]
    before = b["sh_IP products"] - a["sh_IP products"]
    print(f"\n  The IP share went {a['sh_IP products'] * 100:.1f}% in 1960 to "
          f"{b['sh_IP products'] * 100:.1f}% by 2001 to {c['sh_IP products'] * 100:.1f}% now.")
    print(f"  {before / total * 100:.0f}% of the whole rise had already happened BEFORE")
    print("  China joined the WTO. That is the first thing the offshoring story has to")
    print("  account for and it is not a detail: the shift was most of the way done")
    print("  before the shock that is supposed to have caused it.")
    return a, b, c


# --------------------------------------------------------------------------- 2
def what_moved(rows):
    """Offshoring removes production. Did the physical stock actually hollow out?"""
    print("\n" + "=" * 92)
    print("2. WHAT ACTUALLY HOLLOWED OUT")
    print("=" * 92)
    print("  Offshoring takes production away, so it should shrink the physical capital")
    print("  stock, not merely re-weight it. Stocks are DEFLATED by the GDP deflator, so")
    print("  these are real and the employment column is comparable. 1960 = 100.\n")
    a = next(x for x in rows if x["year"] == 1960)
    defl = annual("GDPDEF")
    manemp = annual("MANEMP")
    print(f"  {'year':>6} {'equip stock':>12} {'struct stock':>13} {'IP stock':>10} | "
          f"{'mfg employment':>15}")
    for y in (1960, 1980, 2001, 2010, rows[-1]["year"]):
        r = next((x for x in rows if x["year"] == y), None)
        if r is None:
            continue
        f = (defl[1960] / defl[y]) * 100.0
        print(f"  {y:6d} "
              f"{r['sh_equipment'] * r['tot'] / (a['sh_equipment'] * a['tot']) * f:11.0f} "
              f"{r['sh_structures'] * r['tot'] / (a['sh_structures'] * a['tot']) * f:12.0f} "
              f"{r['sh_IP products'] * r['tot'] / (a['sh_IP products'] * a['tot']) * f:9.0f} | "
              f"{manemp[y] / manemp[1960] * 100:14.0f}")
    print("\n  The shapes disagree, and that is the section. Manufacturing employment")
    print("  peaks and falls back BELOW where it started, while every class of capital")
    print("  grows several-fold in real terms -- equipment included, the class offshoring")
    print("  is supposed to have taken away.")
    print("\n  So nothing was hollowed out of the capital stock. Equipment's SHARE fell,")
    print("  32.8% to 25.9%, but only because IP grew faster, not because equipment")
    print("  shrank. What left the country was labour, and the machinery stayed.")


# --------------------------------------------------------------------------- 3
def correlate(rows):
    print("\n" + "=" * 92)
    print("3. DOES THE IP SHIFT TRACK THE OFFSHORING MEASURES?")
    print("=" * 92)
    ys = [r["year"] for r in rows]
    ip = np.array([r["sh_IP products"] for r in rows])
    imp = np.array([r["imp_gdp"] for r in rows])
    mfg = np.array([r["manshare"] for r in rows])
    print("  In LEVELS everything trends together and the correlations are meaningless.")
    print("  In CHANGES, which is the specification, they are not:\n")
    d = np.diff
    print(f"  {'':>34} {'levels':>9} {'changes':>9}")
    for lab, x in (("IP share vs imports/GDP", imp),
                   ("IP share vs mfg employment share", mfg)):
        print(f"  {lab:>34} {np.corrcoef(ip, x)[0, 1]:+8.3f} "
              f"{np.corrcoef(d(ip), d(x))[0, 1]:+8.3f}")
    # the decade in which each moved fastest
    def fastest(v):
        best = None
        for i in range(len(ys) - 10):
            ch = v[i + 10] - v[i]
            if best is None or abs(ch) > abs(best[0]):
                best = (ch, ys[i], ys[i + 10])
        return best
    for lab, v in (("IP share", ip), ("imports/GDP", imp),
                   ("mfg employment share", mfg)):
        ch, y0, y1 = fastest(v)
        print(f"  fastest decade for {lab:>22}: {y0}-{y1}, {ch * 100:+.1f} pp")
    print("\n  The three move in different decades, which is the point of the table.")
    print("\n  ONE CAVEAT ON THE -0.51. Imports collapse in recessions and equipment")
    print("  investment collapses harder than IP investment does, so the IP SHARE rises")
    print("  in a downturn for reasons that have nothing to do with trade. That is enough")
    print("  to produce a negative correlation on its own, so the sign should not be read")
    print("  as evidence AGAINST offshoring -- only as evidence of no positive relation.")


# --------------------------------------------------------------------------- 4
def verdict():
    print("\n" + "=" * 92)
    print("4. VERDICT")
    print("=" * 92)
    print("  WHAT IS TRUE, and it is a lot. Manufacturing employment fell from 28.4% of")
    print("  payrolls to 8.1%, and in absolute terms it is now BELOW its 1960 level after")
    print("  a peak in 1979. Imports went from 4.2% of GDP to 14.0%. Manufacturing value")
    print("  added is under a tenth of GDP. Deindustrialisation in the sense people mean")
    print("  it -- the disappearance of industrial employment -- is not in dispute here")
    print("  and nothing below denies it.")
    print("\n  WHAT DOES NOT FOLLOW is that this is what moved the capital stock into")
    print("  intellectual property, and three things say it is not:")
    print("\n    TIMING. 63% of the rise in the IP share had happened before China joined")
    print("    the WTO, and the fastest decade for IP was 1982-1992 -- before the fastest")
    print("    decade for imports, 1998-2008, and long after the fastest decade for")
    print("    manufacturing employment loss, 1966-1976. The three peak in different")
    print("    decades, which is hard for a single causal chain.")
    print("\n    THE STOCK DID NOT LEAVE. Real equipment capital is six times its 1960")
    print("    level. If US firms had exited physical production the machinery would show")
    print("    it, and it does not. Equipment's SHARE fell only because IP grew faster.")
    print("\n    NO POSITIVE CO-MOVEMENT. In changes, the IP share has essentially zero")
    print("    correlation with the manufacturing employment share (+0.007).")
    print("\n  THE STEELMAN, which survives all of that. The offshoring story does not")
    print("  need a sharp break in 2001. It can be a slow specialisation: US firms moved")
    print("  up the value chain into design and branding over decades, from the Japanese")
    print("  competition of the 1970s onward, precisely BECAUSE production could be")
    print("  bought cheaply elsewhere. On that reading the 1982-1992 acceleration is not")
    print("  an embarrassment, it is the mechanism. Nothing above rules this out.")
    print("\n  WHAT WOULD SETTLE IT is the one thing this module cannot reach: BEA's")
    print("  fixed assets BY INDUSTRY. If the IP shift is concentrated in manufacturing")
    print("  firms, the specialisation story is carrying it. If it is economy-wide --")
    print("  and finance, health and retail have IP stocks too -- then it is technology.")
    print("  Those tables exist and are not on FRED.")
    print("\n  ON THE BALANCE OF WHAT IS HERE: deindustrialisation is real and is a")
    print("  labour phenomenon, not a capital one. The machinery stayed and the jobs went,")
    print("  which is what automation looks like and is not what offshoring looks like.")
    print("  The shift into IP is at most partly a specialisation story and mostly not a")
    print("  dated-shock story, and moral.py's account -- that obsolescence cannot shorten")
    print("  the life of capital that already wears out fast, so it shows up as buying")
    print("  different capital instead -- remains the better-supported explanation.")


def main():
    rows = load()
    print(f"BEA fixed assets and BLS employment, {rows[0]['year']}-{rows[-1]['year']}\n")
    timing(rows)
    what_moved(rows)
    correlate(rows)
    verdict()


if __name__ == "__main__":
    main()
