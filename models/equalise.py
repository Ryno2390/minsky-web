"""The policy rate at which banking earns what the rest of the economy earns.

    python3 models/equalise.py

THE ARGUMENT
------------
Shaikh's second condition is that banking is a business like any other, so competition
between sectors drags its profit rate toward the general rate. Banking's profit is what is
left after it pays for its funds and runs itself, over its own capital. So given

    r        the general PRE-INTEREST profit rate, from the nonfinancial corporate sector
    income   what banks earn on their assets
    opex     what they cost to run, net of fee income
    EQ       their own capital

there is exactly one interest expense consistent with `rB = r`, and therefore one average
funding cost. Map that back through the measured pass-through from the policy rate into
what banks actually pay, and the policy rate falls out. Nothing is fitted: every input is a
reported accounting quantity, and the only estimated object is the pass-through itself,
which is a two-parameter regression with an R-squared of 0.84 over thirty-six years.

That is the one construction in this repo that yields a policy rate with NO model
parameters at all. Compare models/shaikh_rate.py, where the level of the classical normal
rate i_N = c + lam*r is persistently 2.5 points below the actual loan rate and tracks it at
an R-squared of 0.004. This does better because it uses the balance sheet that exists
rather than a coefficient that has to be assumed.

TWO MISTAKES WORTH NOT REPEATING
--------------------------------
1. DO NOT feed the actual interest expense in as a cost and then solve for the rate. The
   interest expense IS the policy rate acting on the balance sheet, so doing that makes the
   calculation partly circular and the answer lands near wherever the policy rate already
   is, whatever it is.

2. COMPARE LIKE WITH LIKE. `r` is NOS/K: pre-tax and pre-interest. `NETINC/EQ` is after
   tax. Comparing them understates banking's profit rate by the tax rate -- about a fifth --
   and biases the implied policy rate down by roughly a third of a point. Use NETINC + ITAX.

WHAT IT DOES NOT SETTLE
-----------------------
This is a REPRODUCTION condition, not a welfare optimum. It says where the rate would sit
if banking earned what everyone else earns; it does not say that is the rate a central bank
with a dual mandate should choose, because nothing here prices inflation or employment.

And the premise is persistently violated. Banking's pre-tax profit rate has averaged about
six points ABOVE the general rate since 1990. Equalization is a tendency in Shaikh, not a
fact, and on this evidence it is a tendency US banking has spent thirty-five years not
obeying. `history()` prints the whole record rather than the one comfortable year.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402
import usbank                                                    # noqa: E402
import uscorp                                                    # noqa: E402

BETA_FROM = 1990          # the pass-through is estimated from here; deposit pricing before
#                           the 1980s deregulation is a different regime


def annual_r():
    """The general pre-interest profit rate, US nonfinancial corporate, by year."""
    D = uscorp.load()
    R = uscorp.ratios(D)
    out = {}
    for dt, v in zip(D["date"], R["r"]):
        if v is not None:
            out.setdefault(int(dt[:4]), []).append(v)
    return {y: sum(v) / len(v) for y, v in out.items()}


def annual_ff():
    s = fred.series("FEDFUNDS")
    out = {}
    for dt, v in zip(s["date"], s["value"]):
        out.setdefault(int(dt[:4]), []).append(v / 100.0)
    return {y: sum(v) / len(v) for y, v in out.items()}


def pass_through(nat, ff, since=BETA_FROM):
    """avg funding cost = a + b * policy rate. The 'deposit beta', measured not assumed.

    Banks pay far less than the policy rate on average, because much of their funding is
    cheap or non-interest-bearing deposits. That wedge is what makes the implied FUNDING
    cost and the implied POLICY rate different numbers, and it has to be estimated before
    one can be turned into the other.
    """
    ys = [y for y in sorted(nat)
          if y >= since and nat[y].get("EQ") and y in ff and nat[y].get("ASSET")]
    x = np.array([ff[y] for y in ys])
    y_ = np.array([nat[y]["EINTEXP"] / (nat[y]["ASSET"] - nat[y]["EQ"]) for y in ys])
    A = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(A, y_, rcond=None)
    r2 = 1 - ((y_ - A @ b) ** 2).sum() / ((y_ - y_.mean()) ** 2).sum()
    return b[0], b[1], r2, len(ys)


def bank_profit_rate(a, pretax=True):
    """Banking's own profit rate on its own capital. PRE-TAX by default, to compare with r."""
    num = a["NETINC"] + (a.get("ITAX", 0.0) if pretax else 0.0)
    return num / a["EQ"] if a.get("EQ") else float("nan")


def equalising_policy_rate(a, r, beta):
    """The policy rate at which this bank sector would earn exactly `r`.

    Returns (implied policy rate, implied average funding cost, current funding cost).
    """
    a0, b1, *_ = beta
    EQ = a["EQ"]
    fund_base = a["ASSET"] - EQ
    rB = bank_profit_rate(a)
    extra_expense = (rB - r) * EQ          # what must be handed over to bring rB down to r
    fund_now = a["EINTEXP"] / fund_base
    fund_eq = (a["EINTEXP"] + extra_expense) / fund_base
    return (fund_eq - a0) / b1, fund_eq, fund_now


def history(nat, prof, ff, beta):
    """The whole record of rB - r, because one year is not evidence of a tendency."""
    rows = []
    for y in sorted(nat):
        a = nat[y]
        if not a.get("EQ") or y not in prof:
            continue
        rB = bank_profit_rate(a)
        ip, fq, fn = equalising_policy_rate(a, prof[y], beta)
        rows.append((y, rB, prof[y], rB - prof[y], fn, fq, ip, ff.get(y)))
    return rows


def main():
    nat = usbank.national()
    prof, ff = annual_r(), annual_ff()
    beta = pass_through(nat, ff)
    a0, b1, r2, n = beta
    y = max(k for k in nat if nat[k].get("EQ"))
    a = nat[y]
    r_now = prof[max(prof)]
    ff_now = ff[max(ff)]

    print("PASS-THROUGH FROM THE POLICY RATE INTO WHAT BANKS PAY")
    print(f"  avg funding cost = {a0*100:.2f}% + {b1:.3f} x fed funds"
          f"   (R2 {r2:.3f}, n = {n}, from {BETA_FROM})")
    print(f"  banks pass through {b1*100:.0f}% of a policy move. The rest is the deposit")
    print("  franchise: funding that is cheap or pays nothing at all.")

    print(f"\nTHE TWO PROFIT RATES  ({y} call reports, r from {max(prof)})")
    rB = bank_profit_rate(a)
    print(f"  general pre-interest profit rate, nonfinancial corporate   r  = {r_now:.4f}")
    print(f"  banking's PRE-TAX profit rate on its own capital           rB = {rB:.4f}")
    print(f"  after tax, for reference                                        "
          f"{bank_profit_rate(a, pretax=False):.4f}")
    print(f"  gap                                                        "
          f"{(rB - r_now)*100:+.2f}pp")

    ip, fq, fn = equalising_policy_rate(a, r_now, beta)
    print("\nEQUALISATION")
    print(f"  average funding cost now                {fn*100:6.2f}%")
    print(f"  ...and what it must be for rB = r       {fq*100:6.2f}%")
    print(f"  -> POLICY RATE for equalisation         {ip*100:6.2f}%")
    print(f"  actual fed funds                        {ff_now*100:6.2f}%")
    print(f"  -> gap                                  {(ip-ff_now)*100:+6.2f}pp")

    print("\nHOW MUCH DOES THE ANSWER DEPEND ON WHICH r?")
    print(f"  {'r used':>28} {'r':>8} {'policy rate':>12} {'vs actual':>10}")
    cands = [("latest, nonfinancial corporate", r_now),
             ("2000-2019 mean", float(np.mean([prof[k] for k in prof if 2000 <= k <= 2019]))),
             ("1947-latest mean", float(np.mean(list(prof.values())))),
             ("lowest year on record", min(prof.values())),
             ("highest year on record", max(prof.values()))]
    for lab, rr in cands:
        p, _f, _n = equalising_policy_rate(a, rr, beta)
        print(f"  {lab:>28} {rr:8.4f} {p*100:11.2f}% {(p-ff_now)*100:+9.2f}pp")
    span = [equalising_policy_rate(a, rr, beta)[0] for _l, rr in cands[:3]]
    print(f"\n  Across the three central choices the answer spans "
          f"{min(span)*100:.2f}% to {max(span)*100:.2f}% -- a "
          f"{(max(span)-min(span))*100:.2f}pp range. It is that tight because the gap closes")
    print("  across the whole funding base, so even a large move in rB - r is a small move")
    print("  in the funding rate. The extreme rows show what it takes to break that.")

    print("\nIS THE PREMISE ACTUALLY SATISFIED? the record, not the one comfortable year")
    rows = history(nat, prof, ff, beta)
    gaps = [g for _y, _b, _r, g, *_ in rows]
    print(f"  rB - r over {rows[0][0]}-{rows[-1][0]}: mean {np.mean(gaps)*100:+.2f}pp, "
          f"range {min(gaps)*100:+.1f} to {max(gaps)*100:+.1f}pp")
    above = sum(1 for g in gaps if g > 0)
    print(f"  banking earned MORE than the general rate in {above} of {len(gaps)} years")
    print(f"\n  {'year':>6} {'rB':>8} {'r':>8} {'rB-r':>8} {'implied ip':>11} "
          f"{'actual ff':>10} {'gap':>8}")
    for yy, rB_, rr_, g, _fn, _fq, ip_, ffy in rows[-12:]:
        fs = f"{ffy*100:9.2f}%" if ffy is not None else f"{'--':>10}"
        gs = f"{(ip_-ffy)*100:+7.2f}pp" if ffy is not None else f"{'--':>8}"
        print(f"  {yy:6d} {rB_:8.4f} {rr_:8.4f} {g*100:+7.2f}pp {ip_*100:10.2f}% {fs} {gs}")
    print("\n  Equalization is a TENDENCY in Shaikh, not a fact, and the mean above says US")
    print("  banking has spent this whole sample not obeying it. Read the implied rate as")
    print("  'where the policy rate would be if banking earned what everyone else earns' --")
    print("  a reproduction condition, not a welfare optimum, and not a state the system")
    print("  has often been in.")


if __name__ == "__main__":
    main()
