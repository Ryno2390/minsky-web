"""Did research move out of firms that gave it away? The disintegration thesis, tested.

    python3 models/spillover.py

THE THEORY
----------
Vertically integrated firms used to publish their research. Bell Labs, Xerox PARC, DuPont,
IBM and GE put findings into the open literature because they captured the value
downstream, through their own manufacturing: a better transistor was worth more to a
company that made and sold transistors than the paper describing it was worth to keep
secret. Know-how was effectively non-rival and non-excludable, and the spillovers are what
made research socially productive.

Vertical disintegration breaks that link. A research unit that no longer owns the factory
must monetise the knowledge itself, so it patents rather than publishes, and know-how
becomes rival and excludable. Aggregate TFP can then fall while each firm's private return
to research holds up, because the same discoveries reach fewer users. The modern form of
the old arrangement is a chip company publishing open-weight models to drive demand for
its chips -- the research is given away because the money is made downstream of it.

This is Arora, Belenzon and Patacconi's account of the decline of science in corporate
R&D. It is not testable here in its central claim, because whether research was PUBLISHED
is a bibliometric fact and this repo has capital stocks. What is testable is the
structural change the theory says drove it: whether research moved out of firms that own
production and into firms that do not.

FIRST, A CORRECTION TO ideas.py
-------------------------------
That module measured research effort with BEA's intellectual property total. It should
not have. IPP bundles research with software and with ARTISTIC ORIGINALS -- films,
television, books, music -- and in 1950 artistic originals were 70% of it. The 1950s
baseline was mostly movies. models/data/beafa.py now splits the three by asset code, and
everything below uses research and development alone, which strengthens the result rather
than weakening it: R&D is 26 times its 1950s level where the contaminated series said 22.
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
PHYS = ("structures", "equipment")


def annual(sid):
    s = fred.series(sid)
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def mean_growth(d, a, b):
    g = [d[y] / d[y - 1] - 1.0 for y in range(a, b + 1) if y in d and y - 1 in d]
    return float(np.mean(g)) if g else float("nan")


# --------------------------------------------------------------------------- 1
def split():
    print("=" * 92)
    print("1. WHAT IS ACTUALLY IN 'INTELLECTUAL PROPERTY'")
    print("=" * 92)
    t, names = beafa.table("real")

    def tot(a, y):
        return sum(t[(c, a)].get(y, 0.0) for c in names if (c, a) in t) / 1000.0

    print("  Real stock, $bn. The three groups sum to the published IPP total to a few")
    print(f"  parts per million: {max(beafa.check().values()):.1e} at worst.\n")
    print(f"  {'year':>6} {'R&D':>9} {'software':>10} {'artistic':>10} {'IPP':>9} | "
          f"{'artistic share':>15}")
    for y in (1950, 1960, 1980, 2000, 2024):
        rd, sw, ae, ip = (tot(a, y) for a in ("rd", "software", "artistic", "ip"))
        print(f"  {y:6d} {rd:9.0f} {sw:10.0f} {ae:10.0f} {ip:9.0f} | {ae / ip * 100:14.1f}%")
    print("\n  In 1950 seventy percent of what BEA calls intellectual property was films,")
    print("  television, books and music. Using the IPP total as a measure of research")
    print("  effort, which ideas.py did, understates the growth in research by taking a")
    print("  baseline that was mostly Hollywood.")


# --------------------------------------------------------------------------- 2
def research_productivity():
    print("\n" + "=" * 92)
    print("2. RESEARCH PRODUCTIVITY, ON RESEARCH ALONE")
    print("=" * 92)
    t, names = beafa.table("real")

    def rd(y):
        return sum(t[(c, "rd")].get(y, 0.0) for c in names if (c, "rd") in t)

    tfp = annual("MFPNFBS")
    base = float(np.mean([rd(y) for y in range(1950, 1970)]))
    b_tfp = mean_growth(tfp, 1950, 1969)
    print(f"  {'era':>12} {'R&D stock':>10} {'vs 1950s':>9} {'TFP growth':>11} "
          f"{'research productivity':>22}")
    for a, b in ERAS:
        lvl = float(np.mean([rd(y) for y in range(a, b + 1)]))
        gt = mean_growth(tfp, a, b)
        print(f"  {f'{a}-{b}':>12} {lvl / 1000:9.0f} {lvl / base:8.1f}x "
              f"{gt * 100:10.2f}% {(gt / b_tfp) / (lvl / base):21.3f}")
    last = float(np.mean([rd(y) for y in range(2020, 2025)]))
    gl = mean_growth(tfp, 2020, 2024)
    print(f"\n  26 times the research capital for {gl / b_tfp * 100:.0f}% of the TFP "
          f"growth: research productivity")
    print(f"  down by a factor of {1 / ((gl / b_tfp) / (last / base)):.0f}. Sharper than "
          "the 38 times ideas.py reported off")
    print("  the contaminated series, and closer to the spending-based literature.")


# --------------------------------------------------------------------------- 3
def structure():
    """The theory's premise: did research leave the firms that own production?"""
    print("\n" + "=" * 92)
    print("3. THE PREMISE -- did research move out of integrated firms?")
    print("=" * 92)
    t, names = beafa.table("real")
    print("  For each year, take every industry's share of the national R&D stock and")
    print("  weight by how much of that industry's OWN capital is physical plant. A firm")
    print("  that owns factories profits from research downstream; one that owns only")
    print("  research has to sell the research.\n")
    print(f"  {'year':>6} {'R&D-weighted physical intensity':>32} "
          f"{'manufacturing share of R&D':>27}")
    out = {}
    for y in (1950, 1960, 1970, 1980, 1990, 2000, 2010, 2024):
        rds = {c: t.get((c, "rd"), {}).get(y, 0.0) for c in names}
        T = sum(rds.values())
        if T <= 0:
            continue
        inten = 0.0
        for c in names:
            own = sum(t.get((c, a), {}).get(y, 0.0) for a in PHYS) \
                + t.get((c, "ip"), {}).get(y, 0.0)
            if own > 0:
                phys = sum(t.get((c, a), {}).get(y, 0.0) for a in PHYS)
                inten += (rds[c] / T) * (phys / own)
        mf = sum(rds[c] for c in names if beafa.is_manufacturing(c)) / T
        out[y] = (inten, mf)
        print(f"  {y:6d} {inten * 100:31.1f}% {mf * 100:26.1f}%")
    print("\n  Both fall and neither is subtle. In 1960, 92% of America's research capital")
    print("  sat inside manufacturing firms, and the industries holding research had 82%")
    print("  of their own capital in plant and equipment. Today those are 57% and 53%.")
    print("\n  That is the structural change the theory needs, measured, and it is large.")
    print("  Research has moved from firms that owned production into firms that do not.")
    return out


# --------------------------------------------------------------------------- 4
def timing(struct):
    print("\n" + "=" * 92)
    print("4. THE TIMING, WHICH IS AWKWARD")
    print("=" * 92)
    tfp = annual("MFPNFBS")
    print(f"  {'era':>12} {'TFP growth':>11} {'R&D physical intensity':>24} "
          f"{'as of':>7} {'change':>9}")
    prev = None
    for a, b in ERAS:
        # the intensity is computed on decade marks, so name the year actually used
        # rather than let a 1970 reading sit on a row labelled 1950-1969
        y = min(struct, key=lambda k: abs(k - b))
        v = struct[y][0]
        ch = "" if prev is None else f"{(v - prev) * 100:+8.1f}"
        print(f"  {f'{a}-{b}':>12} {mean_growth(tfp, a, b) * 100:10.2f}% "
              f"{v * 100:23.1f}% {y:7d} {ch:>9}")
        prev = v
    print("\n  TFP growth collapses in the 1970s and 1980s -- 1.91% to 1.08% to 0.17% --")
    print("  while the physical intensity of research-holding industries is still around")
    print("  80%. The disintegration accelerates AFTERWARDS, through the 1990s and 2000s.")
    print("\n  That ordering is a real problem for a causal reading and is not explained")
    print("  away here. Two things soften it without removing it. A capital STOCK lags the")
    print("  flow decisions that build it, so the change in what firms chose to do")
    print("  precedes the change in what they owned by years. And the events the theory")
    print("  points to -- the AT&T divestiture in 1984, the unwinding of the central")
    print("  corporate laboratories -- sit between the collapse and the stock's response.")
    print("  But the honest reading of this table is that the structural shift followed")
    print("  the productivity slowdown more than it led it.")


# --------------------------------------------------------------------------- 5
def verdict():
    print("\n" + "=" * 92)
    print("5. VERDICT")
    print("=" * 92)
    print("  THE PREMISE IS CONFIRMED AND IT IS BIG. Research moved out of vertically")
    print("  integrated manufacturers and into firms holding little else: 92% of R&D")
    print("  capital in manufacturing in 1960 against 57% now, and the physical intensity")
    print("  of research-holding industries down from 82% to 53%. If the theory needed")
    print("  the reorganisation to have happened, it did.")
    print("\n  THE MECHANISM IS NOT TESTED. Whether research became less PUBLISHED is a")
    print("  bibliometric question and capital stocks cannot answer it. Arora, Belenzon")
    print("  and Patacconi answer it directly with publication counts and find the")
    print("  decline; nothing here confirms or contradicts that, and this file should not")
    print("  be read as evidence for it. What it establishes is that the organisational")
    print("  change they identify shows up independently in the capital accounts.")
    print("\n  THE TIMING IS AGAINST A SIMPLE CAUSAL READING, and section 4 says so.")
    print("\n  WHY IT IS STILL THE BEST CANDIDATE THIS REPO HAS SEEN. Every other")
    print("  explanation tested here has been closed off: the circuit got faster, the")
    print("  profit rate recovered, capital deepening never slowed, offshoring did not")
    print("  empty the capital stock, and composition explains only a fifth. What is left")
    print("  is that research effort rose enormously and produced less, which ideas.py")
    print("  could measure and not explain. This gives that residual a mechanism with a")
    print("  measurable footprint, which is more than fishing-out offers -- fishing-out")
    print("  predicts declining returns to research and nothing else, and so cannot be")
    print("  distinguished from the thing it is meant to explain.")
    print("\n  It also makes a prediction that could be checked against data not here:")
    print("  if excludability is the mechanism, the PRIVATE return to R&D should have")
    print("  held up while the social return fell. Firm-level returns to R&D are")
    print("  published and that comparison would be a real test rather than another")
    print("  description.")


def main():
    split()
    research_productivity()
    st = structure()
    timing(st)
    verdict()


if __name__ == "__main__":
    main()
