"""The rise of the professional class: a price event that ended, then a quantity process.

    python3 models/credential.py

THE FRAMING TO TEST
-------------------
ceos.py established that the within-labour divergence needs millions of people rather
than a boardroom, and that management and professional occupations grew from 33.8% of
employment in 2000 to 43.8% in 2024. The natural name for that is the rise of a
professional, credentialed and managerial class above everyone else.

The name is fair. What it hides is that the thing has two phases with different
mechanisms, and only one of them is still running.

    a CREDENTIAL story says the return to being in that class rose -- a price effect
    a COMPOSITION story says more people joined it at an unchanged return -- a quantity
      effect

Those have different remedies and different futures. Splitting the divergence at 2000
separates them cleanly, because the college premium can be measured from 2000 and the
occupational share from 1983.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402


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
        "comp": "COMPNFB", "ahe": "AHETPI", "cpi": "CPIAUCSL",
        "mgmt": "LNU02032201", "emp": "CE16OV",
        "ba": "LEU0252919100Q", "hs": "LEU0252917300Q",
    }.items()}


def divergence(d, a, b):
    c = (d["comp"][b] / d["cpi"][b]) / (d["comp"][a] / d["cpi"][a])
    w = (d["ahe"][b] / d["cpi"][b]) / (d["ahe"][a] / d["cpi"][a])
    return c / w


# --------------------------------------------------------------------------- 1
def two_phases(d):
    print("=" * 92)
    print("1. THE DIVERGENCE SPLITS AT 2000, AND NOT EVENLY")
    print("=" * 92)
    print("  All-worker compensation per hour against production-worker wages, real.\n")
    print(f"  {'period':>14} {'divergence':>12} {'professional share':>21} "
          f"{'college premium':>17}")
    for a, b in ((1984, 2000), (2000, 2024), (1984, 2024)):
        dv = divergence(d, a, b)
        s0 = d["mgmt"][a] / d["emp"][a] * 100
        s1 = d["mgmt"][b] / d["emp"][b] * 100
        pr = (f"{(d['ba'][b] / d['hs'][b]) / (d['ba'][a] / d['hs'][a]):16.2f}x"
              if a in d["ba"] and b in d["ba"] else f"{'not published':>17}")
        print(f"  {f'{a}-{b}':>14} {(dv - 1) * 100:+11.1f}% "
              f"{s0:8.1f}% -> {s1:5.1f}% {pr}")
    print("\n  Four fifths of forty years of divergence happened in the first sixteen.")
    print("  Since 2000 it has added 4.2 points in twenty-four years, which is close to")
    print("  stopped. Whatever opened this gap did most of its work before the millennium.")


# --------------------------------------------------------------------------- 2
def premium(d):
    print("\n" + "=" * 92)
    print("2. THE CREDENTIAL PREMIUM STOPPED RISING")
    print("=" * 92)
    print("  Median usual weekly earnings, bachelor's degree and higher over high school")
    print("  graduates with no college. The series begins in 2000, which is the limit.\n")
    print(f"  {'year':>6} {'BA+ weekly':>12} {'HS weekly':>11} {'premium':>9} "
          f"{'2000 = 100':>12}")
    b = 2000
    for y in (2000, 2005, 2010, 2015, 2019, 2024):
        r = d["ba"][y] / d["hs"][y]
        print(f"  {y:6d} {d['ba'][y]:11,.0f} {d['hs'][y]:10,.0f} {r:8.2f}x "
              f"{r / (d['ba'][b] / d['hs'][b]) * 100:11.1f}")
    print("\n  Flat. 1.63x in 2000 and 1.65x now, a rise of one percent across a quarter")
    print("  century. The return to a degree is not what has been moving.")
    print("\n  What cannot be seen here is 1984-2000, where the premium is documented")
    print("  elsewhere to have risen sharply. That is the period which also holds four")
    print("  fifths of the divergence, and the two fit together -- but this file cannot")
    print("  measure the first half of its own story and says so rather than implying it.")


# --------------------------------------------------------------------------- 3
def decompose(d):
    print("\n" + "=" * 92)
    print("3. COMPOSITION ALONE, AT A FROZEN PREMIUM")
    print("=" * 92)
    print("  Hold the professional premium fixed and let only the SHARE move. If a")
    print("  period's divergence is fully reproduced, nothing needed to be repriced.\n")
    R = d["ba"][2024] / d["hs"][2024]
    print(f"  {'period':>14} {'share moves':>18} {'composition gives':>19} "
          f"{'measured':>10} {'explained':>11}")
    for a, b in ((1984, 2000), (2000, 2024)):
        s0 = d["mgmt"][a] / d["emp"][a]
        s1 = d["mgmt"][b] / d["emp"][b]
        x0, x1 = s0 * R + (1 - s0), s1 * R + (1 - s1)
        comp = x1 / x0 - 1
        meas = divergence(d, a, b) - 1
        print(f"  {f'{a}-{b}':>14} {s0 * 100:7.1f}% -> {s1 * 100:5.1f}% "
              f"{comp * 100:+18.1f}% {meas * 100:+9.1f}% {comp / meas * 100:10.0f}%")
    print(f"\n  Premium held at {R:.2f}x throughout, its 2024 value.\n")
    print("  Before 2000, composition gives a seventh of what happened -- so six sevenths")
    print("  of that divergence is the professional class being paid relatively more.")
    print("  After 2000, composition gives MORE than the whole of it: the share shift")
    print("  alone over-predicts, which means the premium slightly compressed while the")
    print("  class grew.")


# --------------------------------------------------------------------------- 4
def verdict(d):
    print("\n" + "=" * 92)
    print("4. VERDICT")
    print("=" * 92)
    s84 = d["mgmt"][1984] / d["emp"][1984] * 100
    s24 = d["mgmt"][2024] / d["emp"][2024] * 100
    print("  THE NAME IS FAIR AND THE TENSE IS WRONG. It is not the rise of a")
    print("  professional class -- it is the rise of one, largely completed, followed by")
    print("  a quarter century of that class getting bigger rather than richer.")
    print(f"\n    1984-2000   divergence +18.6%, mostly a rising premium")
    print(f"    2000-2024   divergence  +4.2%, entirely more people joining")
    print(f"\n  The professional and managerial share of employment went {s84:.1f}% in 1984")
    print(f"  to {s24:.1f}% now. Nearly half of American workers are in it. A class that")
    print("  contains half the workforce is not a class in the sense the phrase implies,")
    print("  and 'above the rest' describes a majority standing above a minority.")
    print("\n  WHICH CHANGES WHAT THE PROBLEM IS. If the professional premium had kept")
    print("  climbing, the story would be a credentialed elite pulling away and the")
    print("  remedies would be about credentials -- their cost, their necessity, their")
    print("  gatekeeping. It stopped climbing in 2000. What continued is people crossing")
    print("  into the higher-paid tier, which is mobility rather than extraction, and")
    print("  which leaves the people who did not cross further outside a larger group.")
    print("\n  THE HONEST SUMMARY OF THE WHOLE CHAIN. The felt decline traces through")
    print("  prices to distribution, past capital-versus-labour, past chief executives,")
    print("  and lands on a divergence that opened between 1984 and 2000 and has barely")
    print("  moved since. Most of what people feel now is not a process still running.")
    print("  It is a gap that opened once, was never closed, and is measured against a")
    print("  memory of the years before it opened.")


def main():
    d = load()
    two_phases(d)
    premium(d)
    decompose(d)
    verdict(d)


if __name__ == "__main__":
    main()
