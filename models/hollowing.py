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

SECTION 5 IS THE ONE THAT SETTLES IT
------------------------------------
Sections 1 to 4 use economy-wide asset composition against sectoral employment and trade,
because FRED carries BEA's fixed assets only in aggregate. That is weak evidence and the
verdict there is hedged accordingly. BEA publishes the industry detail itself, in
spreadsheets needing no key, and models/data/beafa.py fetches them: 74 industries, three
asset classes, 1925 to 2024. Section 5 asks the question directly.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import beafa                                                     # noqa: E402
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


# --------------------------------------------------------------------------- 5
def by_industry():
    """The direct test: is the IP shift concentrated in manufacturing, or everywhere?"""
    print("\n" + "=" * 92)
    print("5. BEA'S INDUSTRY DETAIL -- the test sections 1-4 could not run")
    print("=" * 92)
    t, names = beafa.table("stock")
    mfg = beafa.is_manufacturing

    def agg(pred, asset, y):
        return sum(t[(c, asset)].get(y, 0.0) for c in names
                   if pred(c) and (c, asset) in t)

    print("  74 industries, current-cost net stock, $bn.\n")
    print(f"  {'year':>6} | {'MANUFACTURING':>26} | {'EVERYTHING ELSE':>26} | "
          f"{'mfg share':>10}")
    print(f"  {'':>6} | {'equip':>8} {'struct':>8} {'IP share':>8} | "
          f"{'equip':>8} {'struct':>8} {'IP share':>8} | {'of stock':>10}")
    for y in (1960, 1980, 1994, 2001, 2010, 2024):
        cells, tots = [], []
        for pred in (mfg, lambda c: not mfg(c)):
            e = agg(pred, "equipment", y)
            st = agg(pred, "structures", y)
            ip = agg(pred, "ip", y)
            tots.append(e + st + ip)
            cells.append(f"{e / 1000:8.0f} {st / 1000:8.0f} "
                         f"{ip / (e + st + ip) * 100:7.1f}%")
        print(f"  {y:6d} | {cells[0]} | {cells[1]} | "
              f"{tots[0] / sum(tots) * 100:9.1f}%")

    print("\n  MANUFACTURING DID TRANSFORM, and far harder than anything else: its IP")
    print("  share went 13.2% to 35.4%, so better than a third of the capital a US")
    print("  manufacturer now holds is intellectual property. That is the strongest")
    print("  evidence for the hollowing-out reading that this repo has found.")
    print("\n  BUT SO DID EVERYTHING ELSE, from 3.3% to 11.2% -- also more than tripled,")
    print("  in industries that never had production to send anywhere.")

    tot0 = sum(agg(lambda c: True, a, 1960) for a in ("equipment", "structures", "ip"))
    tot1 = sum(agg(lambda c: True, a, 2024) for a in ("equipment", "structures", "ip"))
    contrib = []
    for c in names:
        if (c, "ip") not in t:
            continue
        contrib.append((t[(c, "ip")].get(2024, 0.0) / tot1
                        - t[(c, "ip")].get(1960, 0.0) / tot0, c, names[c]))
    contrib.sort(reverse=True)
    print("\n  Contributions to the ECONOMY-WIDE rise in the IP share, 1960-2024:\n")
    print(f"  {'':>8} {'industry':>46} {'pp':>7}")
    for d, c, n in contrib[:8]:
        print(f"  {'MFG' if mfg(c) else '':>8} {n[:46]:>46} {d * 100:+6.2f}")
    m_tot = sum(d for d, c, _ in contrib if mfg(c))
    n_tot = sum(d for d, c, _ in contrib if not mfg(c))
    print(f"\n  {'manufacturing, all 21 industries':>56} {m_tot * 100:+6.2f} pp")
    print(f"  {'everything else, all 53':>56} {n_tot * 100:+6.2f} pp")
    print(f"\n  Non-manufacturing carries {n_tot / (m_tot + n_tot) * 100:.0f}% of the "
          "economy-wide shift, more than twice")
    print("  what manufacturing carries. The largest single contributor is Chemical")
    print("  Products -- pharmaceutical research, done in the United States -- and the")
    print("  list beneath it is publishing, data processing, telecoms, legal services,")
    print("  insurance and securities. Those industries did not offshore production and")
    print("  then keep the design work. They accumulated intellectual property because")
    print("  intellectual property became what their capital IS.")
    return m_tot, n_tot


# --------------------------------------------------------------------------- 6
def mfg_real():
    """Did manufacturing's own capital stock hollow out, in real terms?"""
    print("\n" + "=" * 92)
    print("6. AND DID MANUFACTURING'S OWN CAPITAL LEAVE?")
    print("=" * 92)
    t, names = beafa.table("stock")
    defl = annual("GDPDEF")
    mfg = beafa.is_manufacturing
    manemp = annual("MANEMP")
    print("  Manufacturing's stock, deflated, 1960 = 100, against its employment.\n")
    print(f"  {'year':>6} {'equipment':>11} {'structures':>11} {'IP':>8} "
          f"{'all three':>10} | {'employment':>11}")
    base = {}
    for y in (1960, 1980, 2001, 2010, 2024):
        vals = {a: sum(t[(c, a)].get(y, 0.0) for c in names
                       if mfg(c) and (c, a) in t)
                for a in ("equipment", "structures", "ip")}
        vals["all"] = sum(vals.values())
        f = defl[1960] / defl[y]
        if not base:
            base = dict(vals)
        print(f"  {y:6d} " + " ".join(
            f"{vals[a] / base[a] * f * 100:10.0f}" for a in
            ("equipment", "structures", "ip")) +
            f" {vals['all'] / base['all'] * f * 100:10.0f} | "
            f"{manemp[y] / manemp[1960] * 100:10.0f}")
    print("\n  Manufacturing's real capital stock more than doubles while its employment")
    print("  ends below where it started. Even its EQUIPMENT -- the machinery that")
    print("  offshoring is supposed to have shipped abroad -- grows in real terms.")
    print("  Manufacturing in America has more capital and fewer workers than in 1960,")
    print("  which is the signature of automation, not of exit.")


# --------------------------------------------------------------------------- 7
def verdict(m_tot, n_tot):
    print("\n" + "=" * 92)
    print("7. VERDICT")
    print("=" * 92)
    print("  WHAT IS TRUE, and it is a lot. Manufacturing employment fell from 28.4% of")
    print("  payrolls to 8.1% and is now BELOW its 1960 level in absolute terms. Imports")
    print("  went 4.2% of GDP to 14.0%. Manufacturing value added is under a tenth of")
    print("  GDP. Deindustrialisation in the sense people mean it happened, and nothing")
    print("  here denies it.")
    print("\n  WHAT THE INDUSTRY DATA CONCEDES TO THE HYPOTHESIS, and it is more than I")
    print("  expected before running it:")
    print("\n    Manufacturing transformed hardest of any sector. Its IP share went 13.2%")
    print("    to 35.4% -- better than a third of what a US manufacturer now owns is")
    print("    intellectual property, against 11.2% everywhere else.")
    print("\n    Its equipment grew slowest of its own three asset classes: 3.7x in real")
    print("    terms since 1960, against 5.5x for structures and 16x for IP. If US")
    print("    manufacturing had kept building machinery at the old rate that ratio would")
    print("    not look like this.")
    print("\n    And its share of the national capital stock did fall, 20.2% to 16.1%.")
    print("\n  WHAT THE INDUSTRY DATA REFUSES:")
    print(f"\n    The shift is not concentrated in manufacturing. Non-manufacturing")
    print(f"    carries {n_tot / (m_tot + n_tot) * 100:.0f}% of the economy-wide rise in the "
          "IP share -- more than twice")
    print("    what manufacturing carries -- and it is carried by publishing, data")
    print("    processing, telecoms, insurance, securities and legal services. Those")
    print("    industries had no production to send abroad. Something that happened to")
    print("    them cannot be explained by offshoring, and the same something is")
    print("    sufficient for manufacturing.")
    print("\n    Manufacturing's capital did not leave. Its real stock is six times its")
    print("    1960 level and even its equipment is 3.7 times, while its employment ends")
    print("    below where it started. More capital, fewer workers, is automation.")
    print("\n    And the timing is wrong. 63% of the IP shift predates China's WTO")
    print("    accession, and the three series peak in three different decades.")
    print("\n  SO: the hollowing-out narrative is right about what happened to industrial")
    print("  EMPLOYMENT and wrong about what happened to industrial CAPITAL. The machinery")
    print("  stayed, grew, and was joined by a great deal of intellectual property -- in")
    print("  manufacturing more than anywhere, which is the part of the hypothesis that")
    print("  survives, but everywhere else as well, which is the part that sinks it as a")
    print("  general explanation.")
    print("\n  moral.py's account still fits better: obsolescence cannot shorten the life")
    print("  of capital that already wears out fast, so it shows up as buying capital")
    print("  that is short-lived by nature. That happens in a chemical company's research")
    print("  and in an insurer's software for the same reason, and neither has anything")
    print("  to do with a container ship.")



def main():
    rows = load()
    print(f"BEA fixed assets and BLS employment, {rows[0]['year']}-{rows[-1]['year']}\n")
    timing(rows)
    what_moved(rows)
    correlate(rows)
    m_tot, n_tot = by_industry()
    mfg_real()
    verdict(m_tot, n_tot)


if __name__ == "__main__":
    main()
