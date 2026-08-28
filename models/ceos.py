"""Does CEO pay explain the distribution inside labour's share? The arithmetic says no.

    python3 models/ceos.py

THE QUESTION
------------
whotook.py established that the gains inside labour went to a group much smaller than the
fifth premium.py had implied, and that wealth concentration is fractal -- even inside the
top 1%, the top tenth of it gained share. The natural next step is that CEO pay explains
the income side.

It cannot, and the reason is arithmetic rather than interpretive. There are not enough
chief executives. This file does that sum, then asks how many people the divergence
actually requires, and finds an answer that is neither CEOs nor the top fifth.

WHY INCOME AND WEALTH SEPARATE HERE
-----------------------------------
whotook.py's strongest numbers were WEALTH shares, and it said so. Wealth concentrates
through asset prices, which need no wage bill behind them: a founder's stake can multiply
without a dollar passing through payroll. Income concentration has to be PAID, out of a
compensation bill of a known size, to a countable number of people. That constraint is
what makes this question answerable at all.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

#: the measured divergence: all-worker compensation per hour sits about 20% above what a
#: uniform production-wage path since 1984 would pay. From premium.py, benefits removed.
GAP = 1.20


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def size():
    gdp = annual("GDP")[2024]
    share = annual("W270RE1A156NBEA")[2024] / 100.0
    bill = gdp * share
    return gdp, bill, bill * (1 - 1 / GAP)


# --------------------------------------------------------------------------- 1
def how_big():
    print("=" * 92)
    print("1. HOW BIG THE DIVERGENCE IS, IN DOLLARS")
    print("=" * 92)
    gdp, bill, excess = size()
    print(f"  US GDP 2024                                     ${gdp / 1000:8.1f}tn")
    print(f"  wage and salary share of gross domestic income   {annual('W270RE1A156NBEA')[2024]:8.1f}%")
    print(f"  implied wage and salary bill                    ${bill / 1000:8.2f}tn")
    print(f"\n  All-worker compensation per hour is {GAP - 1:.0%} above a uniform")
    print(f"  production-wage path since 1984, so roughly ${excess / 1000:.2f}tn a year sits")
    print(f"  above that counterfactual -- {excess / gdp * 100:.1f}% of GDP.")
    print("\n  A note on language: this is a DIVERGENCE, not a theft. Production workers")
    print("  received their actual wages and nobody took this from them. It is the size")
    print("  of the gap between what was paid and what a uniform path would have paid,")
    print("  and it is the quantity any explanation has to account for.")
    return excess


# --------------------------------------------------------------------------- 2
def not_ceos(excess):
    print("\n" + "=" * 92)
    print("2. IT IS NOT CHIEF EXECUTIVES, AND IT IS NOT CLOSE")
    print("=" * 92)
    print("  Total pay of every chief executive under three definitions, drawn as")
    print("  generously as the facts allow, against the divergence.\n")
    print(f"  {'definition':>46} {'total pay':>12} {'% of the gap':>14}")
    for n, avg, lab in ((500, 16e6, "S&P 500 chief executives at $16m each"),
                        (4_000, 5e6, "every public-company CEO at $5m each"),
                        (200_000, 250e3, "every BLS 'chief executive' at $250k")):
        t = n * avg
        print(f"  {lab:>46} ${t / 1e9:10.1f}bn {t / excess * 100:13.2f}%")
    print("\n  The most generous definition -- two hundred thousand people, everyone the")
    print("  payroll survey calls a chief executive -- is 2.4% of it. The S&P 500 chief")
    print("  executives, the ones the argument is usually about, are 0.4%.")
    print("\n  CEO pay is a real phenomenon and rose enormously: the ratio to a typical")
    print("  worker went from roughly 30:1 to several hundred to one. But it is two")
    print("  orders of magnitude too small to be the aggregate mechanism. It is the")
    print("  visible top of the distribution, not the mass of it.")


# --------------------------------------------------------------------------- 3
def how_many(excess):
    print("\n" + "=" * 92)
    print("3. HOW MANY PEOPLE THE ARITHMETIC REQUIRES")
    print("=" * 92)
    mgmt = annual("LNU02032201")[2024] * 1000
    print("  Divide the divergence by candidate group sizes. The per-person figure has to")
    print("  be a plausible SALARY EXCESS, not a fantasy.\n")
    print(f"  {'group':>42} {'people':>13} {'excess each':>15}")
    for cnt, lab in ((500, "S&P 500 chief executives"),
                     (200_000, "every BLS chief executive"),
                     (1_600_000, "top 1% of workers"),
                     (16_000_000, "top 10% of workers"),
                     (int(mgmt), "management + professional occupations")):
        print(f"  {lab:>42} {cnt:13,} ${excess / cnt:14,.0f}")
    print("\n  Only the last two are salaries. At the top 10% it is $131,000 each, large")
    print("  but coherent for a group whose earnings start near six figures. Across all")
    print("  management and professional occupations it is $30,000 each, which is an")
    print("  ordinary description of forty years of professional pay growth.")
    print("\n  The income side therefore requires MILLIONS of people. That is the opposite")
    print("  of the wealth side, where whotook.py found the top 0.1% share rising 62% and")
    print("  the concentration continuing at every level examined. Both are true because")
    print("  they are different quantities: wealth can concentrate through asset prices")
    print("  with no payroll behind it, and income cannot.")


# --------------------------------------------------------------------------- 4
def composition():
    """A tension with premium.py that should be reported, not reconciled away."""
    print("\n" + "=" * 92)
    print("4. AND A TENSION WITH premium.py WORTH REPORTING")
    print("=" * 92)
    mgmt = annual("LNU02032201")
    emp = annual("CE16OV")
    print("  premium.py found NO composition effect: the supervisory share of private")
    print("  employment fell from 19.2% to 18.6%. But that is an establishment survey's")
    print("  supervisory flag. The household survey's OCCUPATIONAL classification says")
    print("  something quite different:\n")
    print(f"  {'year':>6} {'management + professional':>27} {'all employed':>15} "
          f"{'share':>8}")
    for y in (2000, 2010, 2019, 2024):
        print(f"  {y:6d} {mgmt[y]:26,.0f}k {emp[y]:14,.0f}k "
              f"{mgmt[y] / emp[y] * 100:7.1f}%")
    print("\n  From 33.8% of employment to 43.8% -- twenty-four million more people in")
    print("  management and professional occupations. That IS a composition shift, and a")
    print("  large one.")
    print("\n  The two are not contradictory. A registered nurse, an engineer and a data")
    print("  analyst are professional and NONsupervisory, so the professional share can")
    print("  climb while the supervisory share does not move. But it means premium.py's")
    print("  'composition is zero' was true only of the classification it used, and the")
    print("  broader statement it implied -- that nothing about the gap is headcount -- is")
    print("  not supported. A material part of the divergence is more people doing")
    print("  better-paid work rather than the same people being paid more.")


# --------------------------------------------------------------------------- 5
def verdict():
    print("\n" + "=" * 92)
    print("5. VERDICT")
    print("=" * 92)
    print("  NO. CEO pay cannot explain the distribution inside labour's share, and the")
    print("  refutation is arithmetic: every chief executive in the country, on the")
    print("  broadest definition the payroll survey allows, accounts for 2.4% of the")
    print("  divergence. The five hundred whose pay packages are actually discussed")
    print("  account for 0.4%.")
    print("\n  WHAT DOES CARRY IT is a professional and managerial workforce of tens of")
    print("  millions, which both grew as a share of employment -- 33.8% to 43.8% -- and")
    print("  was paid relatively more. Neither of those alone is enough and together they")
    print("  are the right order of magnitude.")
    print("\n  WHICH RESOLVES THE APPARENT CONFLICT with whotook.py rather than")
    print("  contradicting it. Wealth concentrated ferociously at the very top because")
    print("  asset prices need no payroll. Income concentrated much more broadly because")
    print("  it has to be paid to countable people out of a bill of known size. Both")
    print("  files are right about their own quantity, and the CEO is the symbol of the")
    print("  first rather than the mechanism of the second.")
    print("\n  THE UNCOMFORTABLE PART, for anyone who wanted a villain. The group that")
    print("  gained on the income side is large, credentialed, and includes most people")
    print("  who would read an analysis like this one. It is not a boardroom. That does")
    print("  not make the divergence acceptable, and it does change what would reverse it")
    print("  -- executive pay caps reach 0.4% of the problem.")


def main():
    excess = how_big()
    not_ceos(excess)
    how_many(excess)
    composition()
    verdict()


if __name__ == "__main__":
    main()
