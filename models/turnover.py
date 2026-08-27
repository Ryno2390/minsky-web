"""Turnover time and fixed capital -- Volume II Parts I and II, which Part III assumes away.

    python3 models/turnover.py

WHY THIS IS NOT A DETAIL
------------------------
The reproduction schemes write each department's year as c + v + s and say nothing about
how many times the capital went round to produce it. Marx spends two entire Parts on
exactly that before he writes a single scheme, and the reason is in ch.16: the same
capital advanced yields a different annual surplus depending on how fast it turns over.

    annual rate of surplus value = e * n           e the real rate, n the turnovers

Two capitals of 2500 with identical rates of exploitation return 1000% and 100% a year if
one turns over ten times and the other once. Nothing in c + v + s shows that, because c,
v and s are annual FLOWS and the capital advanced is a STOCK -- and the ratio between
them is the turnover number, which the schemes silently set to one.

WHAT CHANGES, AND WHAT DOES NOT
-------------------------------
Both balance conditions from reproduction.py generalise rather than break:

    alpha2* = alpha1 * n1 (1 + q2) / (n2 (1 + q1))
    C2/V1   = (n1 (1 + (1 - alpha1) e) + g) / (n2 + g)

and both collapse to the ch.21 values at n1 = n2 = 1, which is the check that they are
the same conditions and not new ones. The substantive change is that a department's
growth rate now depends on its turnover:  g_i = alpha_i * e * n_i / (1 + q_i). A
department that turns over slowly grows slowly on the same accumulation rate, and the
other department has to match it.

FIXED CAPITAL, WHICH IS THE HARDER HALF
---------------------------------------
Circulating capital is advanced and recovered every turnover. Fixed capital transfers its
value piecemeal over L years but is replaced IN KIND all at once, and the gap between the
two is money sitting idle -- a depreciation hoard. So constant capital consumed is

    c = F/L + Cc*n            value transferred, not money spent

while the money actually spent on fixed capital is rho*F, with rho the rate at which the
stock is physically replaced. Simple reproduction needs those equal, rho = 1/L, and that
is a statement about the AGE DISTRIBUTION of the capital stock, not about anyone's
intentions. Marx says as much in ch.20 sec.11 and calls the balance a matter of chance.

Section 4 is where an ODE model has to hand back to arithmetic: an age distribution is an
array, and Minsky integrates scalars.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import reproduction as ref                                       # noqa: E402


# --------------------------------------------------------------------------- 1
def annual_rate():
    """Marx ch.16's two capitals, which is the whole of the turnover argument."""
    print("=" * 92)
    print("1. THE ANNUAL RATE OF SURPLUS VALUE -- Volume II, chapter 16")
    print("=" * 92)
    print("  Two capitals, same size, same rate of exploitation, different turnover.\n")
    print(f"  {'capital':>9} {'V advanced':>11} {'weeks':>7} {'turnovers':>10} "
          f"{'V employed':>12} {'surplus':>9} {'annual rate':>12}")
    e = 1.0
    for nm, V, weeks in (("A", 2500.0, 5.0), ("B", 2500.0, 50.0)):
        n = 50.0 / weeks
        emp = V * n
        s = e * emp
        print(f"  {nm:>9} {V:11.0f} {weeks:7.0f} {n:10.1f} {emp:12.0f} {s:9.0f} "
              f"{s / V * 100:11.0f}%")
    print("\n  Marx's own figures: 1000% against 100%, on identical capitals at an")
    print("  identical 100% rate of exploitation. The annual rate is e*n, and n is the")
    print("  number the reproduction schemes set to one without saying so.")
    print("\n  The reason this matters for Part III is that c, v and s are annual FLOWS")
    print("  while the capital advanced is a STOCK. Every scheme in ch.20 and ch.21 is")
    print("  written in flows, so it fixes the flows and leaves the stocks free -- and")
    print("  the turnover number is exactly the ratio between them.")


# --------------------------------------------------------------------------- 2
def conditions(alpha1=0.5, e=1.0):
    """The two balance conditions, generalised, and checked against the n = 1 case."""
    print("\n" + "=" * 92)
    print("2. THE BALANCE CONDITIONS WITH TURNOVER")
    print("=" * 92)
    q1, q2 = 4.0, 2.0
    print(f"  q1 = {q1:.0f}, q2 = {q2:.0f}, e = {e:.0f}, alpha1 = {alpha1:.2f}\n")
    print(f"  {'n1':>5} {'n2':>5} | {'g':>8} {'alpha2*':>9} {'C2/V1':>9}   note")
    for n1, n2, note in ((1.0, 1.0, "ch.21, both annual"),
                         (0.5, 1.0, "Dept I turns over every 2 years"),
                         (2.0, 1.0, "Dept I twice a year"),
                         (1.0, 0.5, "Dept II every 2 years"),
                         (1.0, 2.0, "Dept II twice a year"),
                         (2.0, 2.0, "both twice a year")):
        g = alpha1 * e * n1 / (1.0 + q1)
        a2 = alpha1 * n1 * (1.0 + q2) / (n2 * (1.0 + q1))
        cv = (n1 * (1.0 + (1.0 - alpha1) * e) + g) / (n2 + g)
        print(f"  {n1:5.1f} {n2:5.1f} | {g * 100:7.1f}% {a2:9.3f} {cv:9.4f}   {note}")
    g0 = alpha1 * e / (1.0 + q1)
    a20 = alpha1 * (1.0 + q2) / (1.0 + q1)
    cv0 = (1.0 + (1.0 - alpha1) * e + g0) / (1.0 + g0)
    print(f"\n  The first row must reproduce reproduction.py section 5, and does:")
    print(f"    g = {g0:.4f} (was 0.1000), alpha2* = {a20:.4f} (was 0.3000), "
          f"C2/V1 = {cv0:.4f} (was 1.4545)")
    print("\n  Read the second row. If Dept I takes two years to turn over, it produces")
    print("  half the annual surplus on the same advanced capital, grows at 5% instead of")
    print("  10%, and Dept II must HALVE its accumulation rate to 0.150 to keep step.")
    print("  Turnover is not a correction to the schemes. It moves the balanced path.")
    print("\n  Now compare rows 3 and 4, and rows 1 and 6. Doubling n1 while halving n2")
    print("  gives IDENTICAL alpha2* and C2/V1; doubling both leaves them untouched and")
    print("  only moves g. So the split is clean and worth stating:")
    print("\n    g depends on n1 ALONE.   Both balance conditions depend only on n1/n2.")
    print("\n  Speeding the whole economy up accelerates accumulation without changing")
    print("  any required proportion. Only a change in the RELATIVE speed of the two")
    print("  departments moves the balanced path -- which is the same lesson as the rest")
    print("  of Part III, that what has to be got right is a ratio between departments.")


# --------------------------------------------------------------------------- 3
def fixed_capital(L=10.0, F=4000.0, Cc=1000.0, V=1100.0, n=1.0, e=1.0):
    """Decomposing c, and the condition that the schemes cannot see."""
    print("\n" + "=" * 92)
    print("3. FIXED CAPITAL -- value transferred is not money spent")
    print("=" * 92)
    dep = F / L
    circ = Cc * n
    c = dep + circ
    v = V * n
    s = e * v
    K = F + Cc + V
    print(f"  A department with F = {F:.0f} lasting {L:.0f} years, circulating "
          f"Cc = {Cc:.0f}, V = {V:.0f}, n = {n:.0f}:\n")
    print(f"    {'depreciation F/L':>26} {dep:9.1f}")
    print(f"    {'circulating consumed Cc*n':>26} {circ:9.1f}")
    print(f"    {'c, constant capital consumed':>26} {c:9.1f}   <- all the schemes see")
    print(f"    {'v = V*n':>26} {v:9.1f}")
    print(f"    {'s = e*V*n':>26} {s:9.1f}")
    print(f"    {'annual product':>26} {c + v + s:9.1f}")
    print(f"    {'capital ADVANCED':>26} {K:9.1f}   <- what the schemes never write")
    print(f"\n  The scheme reports c = {c:.0f}. Two quite different capitals give that "
          "same c:")
    print(f"    {'F':>8} {'L':>6} {'Cc':>8} {'n':>5} {'F/L':>8} {'Cc*n':>8} {'c':>8} "
          f"{'K advanced':>11}")
    for FF, LL, CC, nn in ((4000.0, 10.0, 1000.0, 1.0), (14000.0, 10.0, 0.0, 0.0),
                           (0.0, 1.0, 1400.0, 1.0), (7000.0, 10.0, 350.0, 2.0)):
        cc = (FF / LL if LL else 0.0) + CC * nn
        print(f"    {FF:8.0f} {LL:6.0f} {CC:8.0f} {nn:5.1f} {FF / LL if LL else 0:8.1f} "
              f"{CC * nn:8.1f} {cc:8.1f} {FF + CC + V:11.0f}")
    print("\n  Same c, capital advanced from 1400 to 15100. The reproduction schemes are")
    print("  blind to the difference, and it is the difference that decides how much")
    print("  money has to sit idle and for how long.")

    print("\n  THE CONDITION THE SCHEMES CANNOT STATE. Value transferred is F/L a year.")
    print("  Money spent replacing fixed capital is rho*F, with rho set by the AGE")
    print("  DISTRIBUTION of the stock. Simple reproduction needs them equal:")
    print(f"\n    rho = 1/L = {1 / L:.3f}     replacement {F / L:.0f} a year against "
          f"depreciation {dep:.0f} a year")
    print("\n  That is not an assumption about behaviour. It says the capital stock is")
    print("  spread evenly across its ages, so that a constant fraction falls due every")
    print("  year. Marx puts it in ch.20 sec.11 and does not pretend it is more than a")
    print("  matter of chance.")
    return dict(F=F, L=L, Cc=Cc, V=V, n=n, e=e, dep=dep, c=c)


# --------------------------------------------------------------------------- 4
def echo(L=10, years=80, F=4000.0):
    """The replacement cycle -- and where a scalar ODE has to hand back to an array.

    rho is not a parameter of anyone's choosing, it is a moment of the age distribution.
    Install a stock all at once and rho is zero for L years and then a spike. Minsky
    integrates scalars and cannot hold a distribution, so this stays in Python and the
    built model takes rho as given -- a real limit of the model, stated rather than
    discovered later.

    Reported as AMPLITUDE over a window, not as point samples. The first version of this
    sampled years 5, 10, 15, 30, 60 against a ten-year life, which are the years the
    oscillation passes through zero, so two of the three rows read flat when they were
    swinging by half the stock.
    """
    print("\n" + "=" * 92)
    print("4. THE REPLACEMENT ECHO -- what rho actually is")
    print("=" * 92)
    print(f"  A stock of {F:.0f}. Depreciation is set aside every year; replacement is")
    print("  bought when a cohort falls due. The hoard is the difference, accumulated.\n")

    def path(cohorts):
        """cohorts: [value, age, life]. Depreciation is each cohort over its OWN life."""
        dep = sum(v / lv for v, _a, lv in cohorts)
        h, out = 0.0, []
        cc = [[v, a, lv] for v, a, lv in cohorts]
        for _y in range(years):
            h += dep
            for k in cc:
                k[1] += 1
                if k[1] >= k[2]:
                    h -= k[0]
                    k[1] = 0
            out.append(h)
        return out

    def amp(pth, a, b):
        w = pth[a:b]
        return max(w) - min(w)

    print(f"  {'age distribution':>28} | {'swing yr 1-20':>14} {'swing yr 61-80':>15}"
          f"   verdict")
    cases = [
        ("all installed together", [[F, 0, L]]),
        ("evenly spread over ages", [[F / L, a, L] for a in range(L)]),
        ("two equal cohorts", [[F / 2, 0, L], [F / 2, L // 2, L]]),
        ("three cohorts, uneven", [[F * 0.5, 0, L], [F * 0.3, 3, L], [F * 0.2, 7, L]]),
    ]
    for label, co in cases:
        pth = path(co)
        a1, a2 = amp(pth, 0, 20), amp(pth, 60, 80)
        verdict = ("flat" if a1 < 1e-9 else
                   ("DOES NOT DAMP" if a2 > a1 * 0.99 else f"damps to {a2 / a1:.0%}"))
        print(f"  {label:>28} | {a1:14.1f} {a2:15.1f}   {verdict}")
    print("\n  Only the even spread is flat, and it is flat because depreciation set aside")
    print("  equals replacement bought in every single year -- which IS rho = 1/L. Every")
    print("  other distribution swings by a large fraction of the stock and keeps swinging")
    print("  to the end of the run. A cohort installed together comes due together, and")
    print("  nothing in the accounting pulls it apart.")
    print("\n  That is Marx's claim in ch.9, that the turnover cycle of fixed capital gives")
    print("  the crisis a material periodicity. It survives being written down.")

    print("\n  WHAT DAMPS IT is dispersion in LIVES, not in ages. Same single cohort,")
    print("  installed all at once, with its lives spread symmetrically about "
          f"{L}:")
    print(f"  {'spread of lifetimes':>28} | {'swing yr 1-20':>14} {'swing yr 61-80':>15}"
          f"   verdict")
    for sd in (0, 1, 2, 3, 5):
        lives = list(range(L - sd, L + sd + 1))
        co = [[F / len(lives), 0, lv] for lv in lives]
        pth = path(co)
        a1, a2 = amp(pth, 0, 20), amp(pth, 60, 80)
        verdict = ("DOES NOT DAMP" if a2 > a1 * 0.99 else f"damps to {a2 / a1:.0%}")
        print(f"  {'+/- ' + str(sd) + ' years':>28} | {a1:14.1f} {a2:15.1f}   {verdict}")
    print("\n  Cohorts with different lives drift out of phase and the swing decays -- but")
    print("  NOT monotonically in the spread, and that is worth not smoothing over. A")
    print("  handful of integer lifetimes partially re-align at their common multiples, so")
    print("  the decay is irregular: +/-1 damps further by year 80 than +/-2 does. What")
    print("  gives a clean decay is many lifetimes rather than a wide spread of few.")
    print("  Nobody decides anything here; it is the arithmetic of a population of assets.")
    print("\n  Both dimensions are properties of the capital stock's HISTORY, and neither")
    print("  is available to a model whose state is a handful of scalars. The built model")
    print("  therefore takes rho as a parameter, and this section is what that parameter")
    print("  stands for: a summary of an age distribution the model cannot carry.")


def main():
    annual_rate()
    conditions()
    fixed_capital()
    echo()


if __name__ == "__main__":
    main()
