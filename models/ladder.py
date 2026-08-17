"""The ladder, measured correctly. Read this rather than the per-rung `--compare` output.

    python3 models/ladder.py

WHY THIS FILE EXISTS
--------------------
The first comparison across the rungs was wrong, in a way worth recording because it is
easy to repeat.

Each rung's `compare()` swept the policy margin `m` while leaving the SOLVED parameters --
the bank payout `payB`, bank capital `EB` -- at the values solved for the BASELINE margin.
So every run except the baseline started off its own balanced path and drifted. The
measured slope was therefore a transient, and it grew without bound with the horizon:

    rung 1, dg/dm over m in [0.02, 0.04]:
        12 periods  0.36        60 periods   1.08
        30 periods  0.55       120 periods   8.04

Re-solving the baseline at each margin -- so every run sits on ITS OWN balanced path --
gives a rest point every time (rE drifts by 7e-18, bank capital per unit of capital by
zero) and a slope that does not move with the horizon at all: 0.9500 at 12, 30, 60 and 120
periods, which is exactly the core's kappa*d*.

So banking does not damp the mechanism. It damps the TRANSITION to it.

TWO DIFFERENT QUESTIONS, AND THEY HAVE DIFFERENT ANSWERS
--------------------------------------------------------
STRUCTURAL  compare two economies, each on its own balanced growth path, one holding a
            wider margin than the other. "Does the margin change the growth rate?"
TRANSIENT   take one economy on its balanced path, change the margin, and watch for a
            fixed span. "How much does a policy change move growth over a decade?"

Both are real. Reporting one and calling it the other is what went wrong.

AND THE RUNGS DO NOT ALL CLOSE THE SAME WAY
-------------------------------------------
The core and rungs 1 and 2 have no labour force, so growth is whatever accumulation
delivers and the margin sets it. The full model has productivity and labour force growth,
so its balanced growth rate is pinned at alpha+beta and the margin CANNOT change it --
what the margin changes there is the level of utilisation and the distribution. Comparing
their slopes as though they measured one quantity was a category error; they are answers to
different questions, and the file reports both.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runner import Run                                       # noqa: E402
import enterprise_core as CORE                               # noqa: E402
import enterprise_banking as BANK                            # noqa: E402
import enterprise_equity as EQ                               # noqa: E402
import shaikh_monetary_policy as FULL                        # noqa: E402

MODELS = "~/minsky-models"
LO, HI = 0.02, 0.04          # both comfortably above the core's m_zero = 0.0041


def core_pair(R, m, tmax):
    p = dict(CORE.P); p["m"] = m
    q = R.use(f"{MODELS}/EnterpriseCore.mky").go(
        tmax, ["g", "d", "rE"], {"m": m}, samples=80)
    return q


def bank_pair(R, m, tmax, own_path):
    p = dict(BANK.P); p["m"] = m
    bl = BANK.baseline(p)
    over = {"m": m}
    if own_path:                       # solve the baseline AT THIS MARGIN
        over.update(payB=bl["payB"], EB=bl["EB"], L=bl["L"], s=p["s"])
    return R.use(f"{MODELS}/EnterpriseBanking.mky").go(tmax, BANK.W, over, samples=80)


def equity_pair(R, m, psi, tmax, own_path):
    p = dict(EQ.P); p["m"] = m; p["psi"] = psi
    bl = EQ.baseline(p)
    over = {"m": m, "psi": psi}
    if own_path:
        over.update(payB=bl["payB"], EB=bl["EB"], L=bl["L"], E=bl["E"], RE=bl["RE"],
                    s=p["s"])
    return R.use(f"{MODELS}/EnterpriseEquity.mky").go(tmax, EQ.W, over, samples=80)


def full_pair(R, m, tmax):
    return R.use(f"{MODELS}/ShaikhMonetaryPolicy.mky").go(
        tmax, ["gacc", "r", "u", "rE", "ipol"], {"rule": 1.0, "msh": m}, samples=80)


def slope(hi, lo, key="g"):
    return (hi[key][-1] - lo[key][-1]) / (HI - LO)


def main():
    R = Run(f"{MODELS}/EnterpriseCore.mky")

    print("=" * 78)
    print("1. STRUCTURAL: each economy on its own balanced path. Does the margin change g?")
    print("=" * 78)
    print(f"  {'model':>22} {'dg/dm':>9} {'theory':>9}  note")
    c = (core_pair(R, HI, 60.0), core_pair(R, LO, 60.0))
    kd = CORE.P["kappa"] * CORE.closed_form(dict(CORE.P))["dstar"]
    print(f"  {'core':>22} {slope(*c):9.4f} {kd:9.4f}  kappa*d*, exactly")
    b = (bank_pair(R, HI, 60.0, True), bank_pair(R, LO, 60.0, True))
    print(f"  {'+ banking':>22} {slope(*b):9.4f} {kd:9.4f}  banking changes NOTHING here")
    for psi in (0.25, 0.50, 0.75):
        e = (equity_pair(R, HI, psi, 60.0, True), equity_pair(R, LO, psi, 60.0, True))
        kdp = EQ.P["kappa"] * EQ.baseline(dict(EQ.P, psi=psi))["dstar"]
        print(f"  {f'+ equity psi={psi:.2f}':>22} {slope(*e):9.4f} {kdp:9.4f}  "
              f"kappa*(1-psi)*d1")

    print("\n  the full model closes differently -- labour and productivity growth pin g:")
    print(f"  {'msh':>6} {'g*':>9} {'r':>9} {'u':>9} {'rE':>9}")
    for m in (0.04, 0.03, 0.02, 0.01):
        p = dict(FULL.P); p["msh"] = m
        s = FULL.steady_state(p, FULL.CAL)
        print(f"  {m:6.3f} {s['gacc']:9.5f} {s['r']:9.5f} {s['u']:9.5f} {s['rE']:9.5f}")
    print("  g* is alpha+beta at every margin, so dg*/dm = 0 BY CONSTRUCTION. What the")
    print("  margin moves is utilisation, 0.754 to 0.882, and the profit rate with it.")

    print("\n" + "=" * 78)
    print("2. TRANSIENT: one economy, margin changed, watched for a fixed span")
    print("=" * 78)
    print(f"  {'model':>22} {'12 periods':>11} {'30 periods':>11} {'60 periods':>11}")
    for label, fn in (("core", lambda t: (core_pair(R, HI, t), core_pair(R, LO, t))),
                      ("+ banking", lambda t: (bank_pair(R, HI, t, False),
                                               bank_pair(R, LO, t, False))),
                      ("+ equity psi=0.50", lambda t: (equity_pair(R, HI, 0.50, t, False),
                                                       equity_pair(R, LO, 0.50, t, False)))):
        vals = [slope(*fn(t)) for t in (12.0, 30.0, 60.0)]
        print(f"  {label:>22} {vals[0]:11.4f} {vals[1]:11.4f} {vals[2]:11.4f}")
    vals = [slope(full_pair(R, HI, t), full_pair(R, LO, t), "gacc")
            for t in (12.0, 30.0, 60.0)]
    print(f"  {'full':>22} {vals[0]:11.4f} {vals[1]:11.4f} {vals[2]:11.4f}")
    print("\n  The core is horizon-independent because it has nothing to adjust. Every")
    print("  other rung drifts, because holding payB at the baseline leaves the run off")
    print("  its own balanced path -- which is the defect this file exists to record.")
    print("  Read the transient column as 'how fast does the economy get there', and")
    print("  only the structural table as 'where does it get to'.")


if __name__ == "__main__":
    main()
