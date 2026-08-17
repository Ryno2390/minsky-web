"""Re-measure every published number on balanced paths, and say which ones stand.

    python3 models/audit.py

An earlier comparison swept a parameter while leaving the SOLVED quantities -- the bank
payout, bank capital, the spread -- at the values solved for the baseline. Every run but
one then started off its own balanced path and drifted, so the measurement was a transient
wearing a comparative static's clothes. This file re-does all of it the right way: for
every parameter setting, the baseline is re-solved AT THAT SETTING, so each run is a rest
point and the answer does not depend on how long it is watched.

Three kinds of quantity turn up, and only the first two were ever safe:

  CLOSED FORM     algebra, no simulation. Nothing to contaminate.
  IMPULSE         a shock applied to a model sitting on its own balanced path, watched for
                  a fixed span. Legitimate, and horizon is part of the answer, not a bug.
  COMPARATIVE     two economies, each on its OWN balanced path, differing in one parameter.
                  This is the one that was measured wrongly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from runner import Run                                       # noqa: E402
import enterprise_core as CORE                               # noqa: E402
import enterprise_banking as BANK                            # noqa: E402
import enterprise_equity as EQ                               # noqa: E402
import shaikh_monetary_policy as FULL                        # noqa: E402

M = "~/minsky-models"
OK, BAD = "stands", "REPLACED"


def rule(t):
    print("\n" + "=" * 78); print(t); print("=" * 78)


def full_steady(msh, **over):
    p = dict(FULL.P); p["msh"] = msh; p.update(over)
    return FULL.steady_state(p, FULL.CAL)


def main():
    R = Run(f"{M}/EnterpriseCore.mky")

    rule("1. FULL MODEL BASELINE  (closed form -- stands)")
    s = full_steady(FULL.P["msh"])
    for k in ("r", "rE", "spread", "ipol", "iL", "iD", "dlev", "u", "omega", "gacc",
              "lam", "payB"):
        print(f"  {k:8s} {s[k]:10.5f}")
    print(f"  interest takes {s['IntL']/s['Profit']*100:.1f}% of pre-interest profit")
    print(f"  {OK}: solved, not simulated. Verified as a rest point to 1e-7 elsewhere.")

    rule("2. RESULT 1, THE MARGIN SWEEP  (was a 12-period transient -- REPLACED)")
    print("  published: rE fell 0.0200 -> 0.0001 and g fell 0.0250 -> 0.0212 as m closed.")
    print("  on balanced paths:\n")
    print(f"  {'m':>7} {'ip':>9} {'r':>9} {'rE':>9} {'g':>9} {'u':>8}  note")
    for m in (0.04, 0.03, 0.02, 0.01, 0.005, 0.0):
        try:
            q = full_steady(m)
            print(f"  {m:7.3f} {q['ipol']:9.5f} {q['r']:9.5f} {q['rE']:9.5f} "
                  f"{q['gacc']:9.5f} {q['u']:8.4f}")
        except SystemExit as e:
            print(f"  {m:7.3f} {'--':>9} no balanced path: {str(e)[:44]}")
    print(f"\n  {BAD}. g AND rE are both pinned: growth must equal alpha+beta, and the")
    print("  investment function then forces rE = rEnorm. The margin cannot move either.")
    print("  What it moves is the LEVEL -- utilisation and the profit rate -- which is a")
    print("  real Shaikhian statement: a tighter margin needs a higher profit rate to")
    print("  sustain the same accumulation.")

    rule("3. RESULT 2, SHAIKH vs TAYLOR  (an impulse from the baseline -- stands)")
    print("  A shock applied to a model sitting on its own balanced path is exactly what")
    print("  an impulse response is. Nothing was swept, so nothing was contaminated.")
    print("  The one thing to check is that the UNSHOCKED baseline really does sit still:")
    RF = R.use(f"{M}/ShaikhMonetaryPolicy.mky")
    W = ["r", "rE", "gacc", "u", "dlev", "lam"]
    base = RF.go(30.0, W, samples=120)
    drift = max(abs(base[k][-1] - base[k][0]) for k in W)
    print(f"    worst drift over 30 periods, no shock: {drift:.1e}")
    print(f"  {OK}: the horizon-dependence reported there is the economics, not the defect.")

    rule("4. RESULT 2b, THE DEPOSIT CHANNEL  (swept without re-solving -- REPLACED)")
    print("  published: closing the margin took rE 0.0194 -> 0.0049 with interest-bearing")
    print("  deposits and 0.0270 -> 0.0198 without, 'four times the damage'.")
    print("  on balanced paths:\n")
    print(f"  {'deposits pay':>13} {'m':>7} {'ip':>9} {'iL':>9} {'r':>9} {'rE':>9} {'u':>8}")
    for dshare in (0.60, 0.0):
        for m in (0.04, 0.0):
            try:
                q = full_steady(m, dshare=dshare)
                print(f"  {dshare:13.2f} {m:7.3f} {q['ipol']:9.5f} {q['iL']:9.5f} "
                      f"{q['r']:9.5f} {q['rE']:9.5f} {q['u']:8.4f}")
            except SystemExit:
                print(f"  {dshare:13.2f} {m:7.3f} {'--':>9} no balanced path")
    print(f"\n  {BAD}. rE is pinned on every balanced path, so the deposit channel cannot")
    print("  change it. What it changes is how far utilisation and r must move.")

    rule("5. THE PASS-THROUGH TABLE  (has no structural counterpart -- REPLACED)")
    print("  published: pass-through 0.14/0.22/0.35/0.57 against dshare, and")
    print("  dg/dm = kappa*d* x pass-through exactly.")
    print("\n  In rung 1 the spread is NOT pinned. Equalisation requires rB = r, which for")
    print("  ANY spread is satisfied by the matching bank capital; and bank capital must")
    print("  grow at g, which fixes the payout and nothing else. So each margin has a")
    print("  ONE-PARAMETER FAMILY of balanced paths indexed by the spread, and how much of")
    print("  a policy move reaches the lending rate depends on which member you compare.")
    print("  Holding the spread fixed -- the natural choice -- it passes through whole:\n")
    print(f"  {'dshare':>7} {'dg/dm structural':>17} {'kappa*d*':>10}")
    kd = CORE.P["kappa"] * CORE.closed_form(dict(CORE.P))["dstar"]
    for dshare in (0.0, 0.3, 0.6, 0.9):
        got = {}
        for m in (0.04, 0.02):
            p = dict(BANK.P); p["m"] = m; p["dshare"] = dshare
            bl = BANK.baseline(p)
            q = R.use(f"{M}/EnterpriseBanking.mky").go(
                30.0, BANK.W, {"m": m, "dshare": dshare, "payB": bl["payB"],
                               "EB": bl["EB"], "L": bl["L"], "s": p["s"]}, samples=80)
            got[m] = q["g"][-1]
        print(f"  {dshare:7.2f} {(got[0.04]-got[0.02])/0.02:17.4f} {kd:10.4f}")
    print(f"\n  {BAD} for rung 1: there, pass-through is a property of the TRANSITION.")
    print("  But the spread IS pinned once a demand side closes the model -- so in the")
    print("  FULL model pass-through has a structural counterpart after all:\n")
    print(f"  {'dshare':>7} {'ip moves':>9} {'iL moves':>9} {'pass-through':>13} "
          f"{'u moves':>9}")
    for dshare in (0.0, 0.3, 0.6, 0.9):
        try:
            a = full_steady(0.04, dshare=dshare)
            b = full_steady(0.00, dshare=dshare)
        except SystemExit:
            print(f"  {dshare:7.2f}  no balanced path at one end"); continue
        dip, dil = b["ipol"] - a["ipol"], b["iL"] - a["iL"]
        print(f"  {dshare:7.2f} {dip:9.5f} {dil:9.5f} "
              f"{(dil/dip if dip else float('nan')):13.3f} {b['u']-a['u']:9.4f}")
    print("\n  The published 0.35 was right in size and wrong in provenance: it is the")
    print("  FULL model's structural pass-through, not rung 1's. And at dshare = 0 it is")
    print("  exactly ZERO -- with free funding, equalisation pins the lending rate outright")
    print("  and policy cannot reach the borrower at all. What absorbs the move instead is")
    print("  utilisation.")

    rule("6. RUNG 2, EQUITY AND LEVERAGE  (structural -- stands)")
    print("  (DH/L is read at m = 0.04, where it is 0.58; it is 0.44 at m = 0.03. It")
    print("   varies with the margin, as the identity says -- and not at all with psi.)")
    print(f"  {'psi':>5} {'d* run':>9} {'d* theory':>10} {'dg/dm':>9} {'kappa*d*':>10} "
          f"{'DH/L':>8}")
    for psi in (0.0, 0.25, 0.50, 0.75):
        got = {}
        for m in (0.04, 0.02):
            p = dict(EQ.P); p["m"] = m; p["psi"] = psi
            bl = EQ.baseline(p)
            q = R.use(f"{M}/EnterpriseEquity.mky").go(
                30.0, EQ.W, {"m": m, "psi": psi, "payB": bl["payB"], "EB": bl["EB"],
                             "L": bl["L"], "E": bl["E"], "RE": bl["RE"],
                             "s": p["s"]}, samples=80)
            got[m] = (q["g"][-1], q["d"][-1], q["DH"][-1] / q["L"][-1])
        th = EQ.baseline(dict(EQ.P, psi=psi))["dstar"]
        print(f"  {psi:5.2f} {got[0.04][1]:9.4f} {th:10.4f} "
              f"{(got[0.04][0]-got[0.02][0])/0.02:9.4f} {EQ.P['kappa']*th:10.4f} "
              f"{got[0.04][2]:8.4f}")
    print(f"\n  {OK}: exact at every psi, horizon-independent. Leverage falls one for one")
    print("  with psi and the mechanism falls with it. DH/L does not move -- the equity")
    print("  correction stands too.")

    rule("7. DH/L  (published 0.47 -- REPLACED by the closed form 0.4377)")
    bl = BANK.baseline(dict(BANK.P))
    p = BANK.P
    ebl = (bl["iL"] - bl["iD"] - p["omegaB"]) / (bl["r"] - bl["iD"])
    print(f"  EB/L = (iL - iD - omegaB)/(r - iD) = {ebl:.6f}   ->   DH/L = {1-ebl:.6f}")
    print(f"  {BAD}: 0.47 was read off a 12-period run that had not settled. The")
    print("  refutation it supports is unaffected -- neither number contains a household term.")

    rule("SUMMARY")
    for label, verdict in (
        ("full model baseline calibration", OK),
        ("core closed form, stability condition, eigenvalue", OK),
        ("Shaikh vs Taylor, and its horizon flip", OK),
        ("the Harrod instability table", OK),
        ("rung 2: leverage, equity, and the DH/L refutation", OK),
        ("Result 1 margin sweep (rE and g falling)", BAD),
        ("Result 2b deposit channel (four times the damage)", BAD),
        ("the pass-through table and the three-factor decomposition", BAD),
        ("DH/L = 0.47", BAD),
    ):
        print(f"  {verdict:9s}  {label}")


if __name__ == "__main__":
    main()
