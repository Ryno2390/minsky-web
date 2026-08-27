"""Is the rising capture of R&D returns real, or is it five companies?

    python3 models/concentration.py

WHY THIS EXISTS
---------------
private_return.py reported that profit among research-doing firms concentrated from 42.7%
to 60.4% in the top ten while their share of the research went 41.7% to 50.1%, called the
gap a "capture premium", and said that because it was a TREND rather than a level it was
"not vulnerable to the objection that the wedge was always there".

That was too confident and this file is the check that should have run first. Three
threats to it, in order of severity:

    THE BIG FIVE      Apple, Alphabet, Microsoft, Nvidia and Meta earn 43.8% of all
                      operating income among R&D filers in 2024. A concentration measure
                      over a few thousand firms can be moved almost entirely by five.
    ATTRITION         the usable sample falls from 1409 firms in 2018 to 935 in 2024.
                      If the firms that drop out are the unprofitable small ones,
                      concentration rises mechanically and means nothing.
    THE CONTROL       profit concentration has risen across the whole US economy. If
                      non-research firms concentrated as much, none of this is about
                      research.

The control is the one that could have killed it outright, so it runs first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import sec                                                       # noqa: E402

YEARS = [2010, 2013, 2016, 2019, 2022, 2024]


def conc(vals, n=10, drop=0):
    """(top-n share, Herfindahl) over positive values, after dropping the largest `drop`."""
    pos = sorted((v for v in vals if v > 0), reverse=True)[drop:]
    if not pos:
        return float("nan"), float("nan")
    tot = sum(pos)
    return sum(pos[:n]) / tot, sum((p / tot) ** 2 for p in pos)


def split(year):
    rd = sec.frame("ResearchAndDevelopmentExpense", year)
    oi = sec.frame("OperatingIncomeLoss", year)
    return ([v for c, v in oi.items() if c in rd],
            [v for c, v in oi.items() if c not in rd])


# --------------------------------------------------------------------------- 1
def control():
    print("=" * 92)
    print("1. THE CONTROL -- did non-research firms concentrate too?")
    print("=" * 92)
    print("  Every SEC filer reporting operating income, split by whether it also")
    print("  reported R&D. Same years, same source, no other selection.\n")
    print(f"  {'year':>6} | {'RESEARCH FIRMS':>26} | {'NON-RESEARCH':>26} | {'HHI':>7}")
    print(f"  {'':>6} | {'n':>6} {'top10':>8} {'HHI':>9} | {'n':>6} {'top10':>8} "
          f"{'HHI':>9} | {'ratio':>7}")
    first = last = None
    for y in YEARS:
        A, B = split(y)
        a, ah = conc(A)
        b, bh = conc(B)
        if first is None:
            first = (ah, bh)
        last = (ah, bh)
        print(f"  {y:6d} | {len(A):6d} {a * 100:7.1f}% {ah:9.4f} | {len(B):6d} "
              f"{b * 100:7.1f}% {bh:9.4f} | {ah / bh:7.2f}")
    print("\n  Both rose, and research firms rose much more: their Herfindahl went up")
    print(f"  {last[0] / first[0]:.1f} times against {last[1] / first[1]:.1f} for "
          "everyone else. So the superstar-firm")
    print("  phenomenon is not uniform across the economy, and it is concentrated among")
    print("  exactly the firms that do research. The control does not kill it.")


# --------------------------------------------------------------------------- 2
def without_the_giants():
    print("\n" + "=" * 92)
    print("2. AND NOW DROP THE FIVE LARGEST IN EACH GROUP")
    print("=" * 92)
    print(f"  {'year':>6} | {'RESEARCH':>20} | {'NON-RESEARCH':>20} | {'HHI ratio':>10}")
    print(f"  {'':>6} | {'top10':>9} {'HHI':>9} | {'top10':>9} {'HHI':>9} |")
    first = last = None
    for y in YEARS:
        A, B = split(y)
        a, ah = conc(A, drop=5)
        b, bh = conc(B, drop=5)
        if first is None:
            first = (ah, bh)
        last = (ah, bh)
        print(f"  {y:6d} | {a * 100:8.1f}% {ah:9.4f} | {b * 100:8.1f}% {bh:9.4f} | "
              f"{ah / bh:10.2f}")
    print(f"\n  THE TREND IS GONE. Research firms' Herfindahl is {first[0]:.4f} in 2010 "
          f"and {last[0]:.4f} in")
    print("  2024 -- flat, slightly DOWN. The ratio against non-research firms falls from")
    print(f"  {first[0] / first[1]:.2f} to {last[0] / last[1]:.2f} rather than rising.")
    print("\n  So the entire rise reported in private_return.py is five companies. Apple,")
    print("  Alphabet, Microsoft, Nvidia and Meta earn 43.8% of all operating income")
    print("  among research-doing filers in 2024. Remove them and research-firm profits")
    print("  are no more concentrated than they were fifteen years ago.")
    print("\n  What SURVIVES is the LEVEL. Research firms are about twice as concentrated")
    print("  as non-research firms at every single date, top five excluded. That is a")
    print("  real and persistent difference. It is not a trend, and the previous file")
    print("  should not have called it one.")


# --------------------------------------------------------------------------- 3
def balanced():
    """Rule out attrition: same firms in every year."""
    print("\n" + "=" * 92)
    print("3. IS IT ATTRITION? -- the same firms, every year")
    print("=" * 92)
    yrs = list(range(2012, 2025))
    fr = {y: (sec.frame("ResearchAndDevelopmentExpense", y),
              sec.frame("OperatingIncomeLoss", y)) for y in yrs}
    always = set.intersection(*[set(fr[y][1]) for y in yrs])
    rd_always = {c for c in always if all(c in fr[y][0] for y in yrs)}
    no_always = always - rd_always
    print(f"  {len(rd_always)} research firms and {len(no_always)} non-research firms")
    print("  report in every year 2012-2024. No entry, no exit, no survivorship.\n")
    print(f"  {'year':>6} | {'RESEARCH':>20} | {'NON-RESEARCH':>20} | "
          f"{'research, ex-top5':>18}")
    for y in (2012, 2016, 2020, 2024):
        A = [fr[y][1][c] for c in rd_always]
        B = [fr[y][1][c] for c in no_always]
        a, ah = conc(A)
        b, bh = conc(B)
        _, ah5 = conc(A, drop=5)
        print(f"  {y:6d} | {a * 100:8.1f}% {ah:9.4f} | {b * 100:8.1f}% {bh:9.4f} | "
              f"{ah5:17.4f}")
    print("\n  Attrition is NOT the explanation: on a fixed set of firms the research")
    print("  Herfindahl still rises. But the last column says the same thing section 2")
    print("  did -- take out five firms and the rise mostly goes with them. The two")
    print("  checks agree, and they agree against the trend claim rather than for it.")


# --------------------------------------------------------------------------- 4
def whose():
    print("\n" + "=" * 92)
    print("4. WHO THEY ARE, AND WHY IT MATTERS FOR THE INTERPRETATION")
    print("=" * 92)
    nm = sec.names(2024) or sec.names(2020)
    rd = sec.frame("ResearchAndDevelopmentExpense", 2024)
    oi = sec.frame("OperatingIncomeLoss", 2024)
    tot = sum(v for c, v in oi.items() if c in rd and v > 0)
    top = sorted(((v, c) for c, v in oi.items() if c in rd), reverse=True)[:8]
    print(f"  {'firm':>44} {'operating income':>18} {'share':>8}")
    for v, c in top:
        print(f"  {nm.get(c, '(name not in frame)')[:44]:>44} {v / 1e9:15.1f} $bn "
              f"{v / tot * 100:7.1f}%")
    print("\n  These are platform companies. Their advantage is usually explained by")
    print("  network effects, ecosystem lock-in and returns to scale in software, not by")
    print("  proprietary research know-how in the sense the excludability thesis means.")
    print("  Nvidia's 2024 profit is a demand shock in AI accelerators. Apple's is a")
    print("  hardware-plus-services ecosystem.")
    print("\n  Those explanations are not cleanly separable from excludability -- CUDA is")
    print("  proprietary know-how, Apple holds tens of thousands of patents, and a")
    print("  platform moat is partly an intellectual property moat. But they are not the")
    print("  SAME claim, and this data cannot tell them apart. A concentration measure")
    print("  moved by five firms is a fact about five firms until something identifies")
    print("  the mechanism.")


# --------------------------------------------------------------------------- 5
def verdict():
    print("\n" + "=" * 92)
    print("5. WHAT I GOT WRONG, AND WHAT SURVIVES")
    print("=" * 92)
    print("  WRONG: private_return.py presented the rising capture premium as the")
    print("  strongest evidence in the file, specifically because it was a trend rather")
    print("  than a level and so escaped the objection that the wedge was always there.")
    print("  It does not escape it. The trend is five companies; excluding them, research")
    print("  firms' profit concentration is flat to slightly falling over fifteen years.")
    print("\n  SURVIVES, and is not nothing:")
    print("\n    Research-doing firms are about twice as profit-concentrated as")
    print("    non-research firms, at every date, with the top five removed from both.")
    print("    A persistent structural difference between research and non-research")
    print("    industries is consistent with excludable know-how conferring durable")
    print("    advantage -- as a LEVEL, which is all it ever was.")
    print("\n    The private return still clears its user cost while the social return per")
    print("    unit of research fell fortyfold. That comparison is untouched by anything")
    print("    here and remains the part that distinguishes excludability from")
    print("    fishing-out.")
    print("\n  AND THE CAUSAL DIRECTION IS STILL OPEN, which matters for the reading that")
    print("  leading firms lead BECAUSE they own excludable know-how. The data are equally")
    print("  consistent with the reverse: firms that lead for other reasons -- scale,")
    print("  network effects, a demand shock -- can afford to spend heavily on research.")
    print("  Nothing in a cross-section of accounts orders those two, and the five firms")
    print("  driving the result are exactly the ones where the alternative story is")
    print("  strongest.")


def main():
    control()
    without_the_giants()
    balanced()
    whose()
    verdict()


if __name__ == "__main__":
    main()
