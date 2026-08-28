"""Is it the top fifth, or is the top fifth itself wildly unequal?

    python3 models/whotook.py

THE CHALLENGE TO premium.py
---------------------------
That file found the supervisory pay premium roughly doubled: the fifth of private workers
their employers class as supervisory are paid about twice as much relative to the other
four fifths as in 1984. It also said, in its own caveats, that "supervisory" lumps a shift
manager with a chief executive.

That caveat turns out to carry the whole question. A payroll aggregate reports a GROUP
MEAN, and a group mean rises the same way whether everyone in the group gained or a
handful gained enormously. Section 3 shows the arithmetic is genuinely indifferent between
those, so premium.py's headline should not have been phrased as though the fifth of
workers had all been paid more. It cannot tell.

What can distinguish them is distributional data rather than payroll data, and that says
the concentration is far higher up than the fifth.
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


# --------------------------------------------------------------------------- 1
def skew():
    print("=" * 92)
    print("1. THE SKEW -- mean against median, which assumes nothing")
    print("=" * 92)
    med, mean = annual("MEFAINUSA672N"), annual("MAFAINUSA672N")
    print("  The mean is dragged by the top tail and the median is not, so their ratio is")
    print("  a measure of how much sits above the middle. Real family income.\n")
    print(f"  {'year':>6} {'median':>11} {'mean':>11} {'mean/median':>13} "
          f"{'1984 = 100':>12}")
    for y in (1984, 1990, 2000, 2010, 2019, 2024):
        r = mean[y] / med[y]
        print(f"  {y:6d} {med[y]:10,.0f} {mean[y]:10,.0f} {r:12.3f} "
              f"{r / (mean[BASE] / med[BASE]) * 100:11.1f}")
    print(f"\n  The ratio went 1.175 to 1.366, a rise of 16%. Income really did skew, and")
    print("  the skew is moderate at this resolution -- which is the resolution a mean")
    print("  and a median can see.")


# --------------------------------------------------------------------------- 2
def tops():
    print("\n" + "=" * 92)
    print("2. HOW FAR UP -- and the answer is: further than a fifth, and further than 1%")
    print("=" * 92)
    w1, w01 = annual("WFRBST01134"), annual("WFRBSTP1300")
    print("  Federal Reserve Distributional Financial Accounts. This is WEALTH, not")
    print("  income, and wealth is always more concentrated -- but the SHAPE is the point.\n")
    print(f"  {'year':>6} {'top 1% share':>14} {'top 0.1% share':>16} "
          f"{'0.1% as a share of the 1%':>28}")
    for y in (1989, 1995, 2000, 2010, 2019, 2024):
        print(f"  {y:6d} {w1[y]:13.1f}% {w01[y]:15.1f}% {w01[y] / w1[y] * 100:27.1f}%")
    print("\n  The last column is the finding. Even INSIDE the top one percent, the top")
    print("  tenth of that one percent took a growing share -- 37.8% to 45.1%. The")
    print("  concentration is fractal: every level up the distribution, the level above it")
    print("  is pulling away from it too.")
    print(f"\n  The top 0.1% share rose {w01[2024] / w01[1989] - 1:+.0%} since 1989 while "
          f"the top 1% rose {w1[2024] / w1[1989] - 1:+.0%}.")
    print("  A group nine times smaller gained proportionally twice as much.")


# --------------------------------------------------------------------------- 3
def indifferent():
    """The arithmetic that premium.py cannot resolve, stated as the limit it is."""
    print("\n" + "=" * 92)
    print("3. THE AGGREGATE IS INDIFFERENT -- which is a correction to premium.py")
    print("=" * 92)
    print("  The measured object is comp_all / wage_prod, up 20% after benefits. Writing")
    print("  s for the gaining group's share of employment and R for its pay relative to")
    print("  everyone else, that ratio is s x R + (1 - s). Fix the observed 20% rise and")
    print("  the same number is produced by very different worlds:\n")
    x = 1.20
    print(f"  {'gaining group':>16} {'R in 1984':>11} {'implied R now':>15} "
          f"{'premium growth':>16}")
    for s, lab, r0 in ((0.19, "top 19%", 1.8), (0.10, "top 10%", 2.5),
                       (0.01, "top 1%", 5.0), (0.001, "top 0.1%", 15.0)):
        x0 = s * r0 + (1 - s)
        r1 = (x0 * x - (1 - s)) / s
        print(f"  {lab:>16} {r0:10.1f}x {r1:14.1f}x {r1 / r0 - 1:+15.0%}")
    print("\n  Every row produces the identical payroll aggregate. A fifth of workers")
    print("  being paid twice as much, and a thousandth being paid five times as much,")
    print("  are the same number at this level of measurement.")
    print("\n  So premium.py located the movement correctly and described its SHAPE wrong.")
    print("  It said the fifth of workers classed as supervisory are paid twice as much")
    print("  relative to everyone else. What it was entitled to say is that a group inside")
    print("  that fifth is, and the aggregate cannot say how large the group is.")
    print("\n  The top-1% row is worth reading against what is known independently: the")
    print("  ratio of chief-executive pay to a typical worker's went from roughly 30 to 1")
    print("  in the late 1970s to several hundred to one. A fivefold rise in the top 1%'s")
    print("  relative pay is not an extreme reading of that; it is a conservative one.")


# --------------------------------------------------------------------------- 4
def verdict():
    print("\n" + "=" * 92)
    print("4. VERDICT")
    print("=" * 92)
    print("  THE CHALLENGE IS RIGHT AND premium.py's PHRASING WAS NOT.")
    print("\n  Three things point the same way:")
    print("    - Mean family income pulled away from median by 16%, so the gains are")
    print("      above the middle rather than spread across it.")
    print("    - The top 0.1% wealth share rose 62% since 1989 against the top 1%'s 34%.")
    print("      The smaller group gained proportionally twice as fast.")
    print("    - Inside the top 1%, the top tenth of it went from 37.8% of that 1%'s")
    print("      wealth to 45.1%. The concentration does not stop at any level examined.")
    print("\n  And the arithmetic in section 3 shows the payroll aggregate never could")
    print("  distinguish a broad gain from a narrow one. It was never evidence for the")
    print("  fifth; it was evidence for a transfer whose recipients it cannot name.")
    print("\n  WHAT THIS DOES NOT ESTABLISH, and it matters. The top-share series here are")
    print("  WEALTH, from the Distributional Financial Accounts, and wealth concentration")
    print("  runs ahead of income concentration in both level and movement -- asset prices")
    print("  do much of the work. The income evidence is thinner: the top decile's share")
    print("  of income rose about four points, which is real and far less dramatic than")
    print("  the wealth series. Anyone reading a 62% rise as an income fact is reading")
    print("  the wrong column.")
    print("\n  SO THE HONEST STATEMENT: the gains went to a group much smaller than a")
    print("  fifth, plausibly smaller than one percent, and the data available here cannot")
    print("  pin the number. What it can say is that every time the question is asked one")
    print("  level further up, the answer is still yes -- which is what a distribution")
    print("  with a very long tail looks like, and is not what a well-paid fifth looks")
    print("  like.")


def main():
    skew()
    tops()
    indifferent()
    verdict()


if __name__ == "__main__":
    main()
