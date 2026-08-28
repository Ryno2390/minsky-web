"""Capital per worker, adjusted for who is not working -- because they still consume.

    python3 models/percapita.py

THE QUESTION
------------
wedge.py measured capital DEEPENING as net investment over the capital stock less
EMPLOYMENT growth, and found it flat: 1.08% a year in the fifties and 1.09% now. Net
investment fell by a third and employment growth fell by half, and the two cancelled.

That invites an objection. If employment growth slowed partly because people retired
rather than because fewer people exist, then dividing by workers flatters the result. A
retired person consumes goods and services and does not produce them, so the capital
stock has to support them too. The measure that answers to living standards is capital
per CONSUMER, which is capital per head of population, and the question is whether the
increase survives that.

It does, and the reason is not the one the objection assumes.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import beafa                                                     # noqa: E402
import fred                                                      # noqa: E402

ERAS = [(1960, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
        (2000, 2009), (2010, 2019), (2020, 2024)]


def annual(sid):
    s = fred.series(sid)
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def growth(s, a, b):
    v = [s[y] / s[y - 1] - 1.0 for y in range(a, b + 1) if y in s and y - 1 in s]
    return float(np.mean(v)) if v else float("nan")


def stock():
    real, names = beafa.table("real")
    return {y: sum(real[(c, a)].get(y, 0.0) for c in names
                   for a in ("structures", "equipment", "ip") if (c, a) in real)
            for y in range(1948, 2025)}


# --------------------------------------------------------------------------- 1
def per_what():
    print("=" * 92)
    print("1. PER WORKER AND PER HEAD")
    print("=" * 92)
    K, emp, pop = stock(), annual("PAYEMS"), annual("POPTHM")
    kw = {y: K[y] / emp[y] for y in K if y in emp}
    kc = {y: K[y] / pop[y] for y in K if y in pop}
    print("  Real private nonresidential capital, per employed person and per head of")
    print("  total population -- the second counts everyone who consumes.\n")
    print(f"  {'era':>10} {'K per worker':>13} {'K per head':>12} {'difference':>12}")
    for a, b in ERAS:
        w, c = growth(kw, a, b), growth(kc, a, b)
        print(f"  {f'{a}-{b}':>10} {w * 100:12.2f}% {c * 100:11.2f}% {(c - w) * 100:+11.2f}")
    print("\n  BOTH GREW, IN EVERY DECADE. Capital per head has never fallen, and for most")
    print("  of the period it grew FASTER than capital per worker rather than slower.")
    print("  The adjustment the question asks for makes the picture better, not worse.")


# --------------------------------------------------------------------------- 2
def why():
    print("\n" + "=" * 92)
    print("2. WHY -- the premise about the working-age share is not right for the US")
    print("=" * 92)
    em, hrs, pop = annual("EMRATIO"), annual("HOANBS"), annual("POPTHM")
    hpc = {y: hrs[y] / pop[y] for y in hrs if y in pop}
    base = float(np.mean([hpc[y] for y in range(1960, 1970)]))
    print("  Employment as a share of the civilian population 16+, and total hours")
    print("  worked per head of population, 1960s = 100.\n")
    print(f"  {'era':>10} {'EMRATIO':>9} {'change':>8} {'hours/head':>12} "
          f"{'growth':>9}")
    for a, b in ERAS:
        lvl = float(np.mean([em[y] for y in range(a, b + 1) if y in em]))
        ch = em[b] - em[a] if a in em and b in em else float("nan")
        h = float(np.mean([hpc[y] for y in range(a, b + 1) if y in hpc])) / base * 100
        print(f"  {f'{a}-{b}':>10} {lvl:8.1f}% {ch:+7.1f} {h:11.1f} "
              f"{growth(hpc, a, b) * 100:+8.2f}%")
    print("\n  The employment ratio ROSE from 56.4% to a peak of 64% around 2000 as women")
    print("  entered paid work, and has fallen back to 59.1% -- still ABOVE its 1960s")
    print("  level. Hours worked per head of total population are 14% higher than in the")
    print("  1960s. Fewer Americans are working as a share of adults than in 2000, but")
    print("  more than in 1960, so there is no sixty-year demographic drag to adjust for.")
    print("\n  The one decade where the objection bites exactly as posed is 2000-2009:")
    print("  the ratio fell 5.1 points, hours per head fell 1.67% a year, and capital per")
    print("  head grew 0.8 points SLOWER than capital per worker. That is the boomer")
    print("  retirement and the post-2000 participation decline, and it is real. It is")
    print("  one decade out of seven.")


# --------------------------------------------------------------------------- 3
def living_standards():
    """The version of the objection that does hold, and it is worth more than the first."""
    print("\n" + "=" * 92)
    print("3. BUT THE OBJECTION IS RIGHT ABOUT SOMETHING ELSE")
    print("=" * 92)
    oph, gdpc = annual("OPHNFB"), annual("A939RX0Q048SBEA")
    hrs, pop = annual("HOANBS"), annual("POPTHM")
    hpc = {y: hrs[y] / pop[y] for y in hrs if y in pop}
    print("  Output per hour is what production does. GDP per head is what people get.")
    print("  They differ by hours worked per head, and that is where demography enters.\n")
    print(f"  {'era':>10} {'output/hour':>12} {'hours/head':>12} {'GDP/head':>10} "
          f"{'check':>8}")
    for a, b in ERAS:
        o, h, c = growth(oph, a, b), growth(hpc, a, b), growth(gdpc, a, b)
        print(f"  {f'{a}-{b}':>10} {o * 100:11.2f}% {h * 100:+11.2f}% {c * 100:9.2f}% "
              f"{(o + h) * 100:7.2f}%")
    o0, o1 = growth(oph, 1960, 1969), growth(oph, 2020, 2024)
    c0, c1 = growth(gdpc, 1960, 1969), growth(gdpc, 2020, 2024)
    h0, h1 = growth(hpc, 1960, 1969), growth(hpc, 2020, 2024)
    print(f"\n  Output per hour fell {(o0 - o1) * 100:.2f} points between the 1960s and "
          f"now. GDP per head fell")
    print(f"  {(c0 - c1) * 100:.2f} points -- more than twice as much. The difference is "
          "hours per head,")
    print(f"  which grew {h0 * 100:+.2f}% a year in the 1960s and {h1 * 100:+.2f}% now.")
    print("\n  So the right statement is not that a demographic HEADWIND started. It is")
    print("  that a TAILWIND stopped. Rising participation added roughly half a point a")
    print("  year to living standards for forty years, and that contribution is now zero.")
    print("  Living standards therefore slowed by more than productivity did, which is")
    print("  exactly the concern behind the question, arrived at from the other side.")


# --------------------------------------------------------------------------- 4
def verdict():
    print("\n" + "=" * 92)
    print("4. ANSWER")
    print("=" * 92)
    print("  YES, capital per worker still rose after adjusting, and by more rather than")
    print("  less. Capital per head of population -- which counts retirees, children and")
    print("  everyone else who consumes without producing -- grew in every decade since")
    print("  1960 and grew FASTER than capital per worker in six of the seven decades.")
    print("\n  The premise does not hold for the United States over this period. The share")
    print("  of adults working is higher now than in 1960, not lower, because forty years")
    print("  of rising female participation more than offset twenty of retirement. Hours")
    print("  worked per head of population are 14% above their 1960s level.")
    print("\n  BUT THE INSTINCT BEHIND THE QUESTION IS RIGHT, and it lands on the growth")
    print("  rate rather than the level. Output per hour slowed by 0.55 points between")
    print("  the 1960s and now; GDP per head slowed by 1.25. More than half the fall in")
    print("  living-standards growth is not productivity at all -- it is that hours per")
    print("  head stopped rising. A measure of what people GET has to carry that, and")
    print("  output per worker does not.")
    print("\n  Which matters for everything earlier in this repo: the TFP slowdown is a")
    print("  1.2-point story about production, and the living-standards slowdown is a")
    print("  larger story of which demography is roughly half. Those have been treated")
    print("  as one question and they are two.")


def main():
    per_what()
    why()
    living_standards()
    verdict()


if __name__ == "__main__":
    main()
