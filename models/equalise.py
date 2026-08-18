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


QSTART = 2000     # quarterly default: covers the 2004-06 hikes, ZIRP, and 2022-23


def quarterly_panel(start=QSTART):
    """One row per quarter: r, banking's pre-tax profit rate, funding cost, fed funds.

    THE ALIGNMENT. An FDIC report date of 20240331 is the first quarter of 2024, which is
    NIPA's 2024-01-01. The two are matched on (year, quarter) rather than on the raw date,
    which differ by construction -- FDIC stamps the END of the period and NIPA the start.

    THE FLOWS ARE ALREADY ANNUALISED by usbank.quarterly(), which differences the
    year-to-date call-report figures and multiplies by four. Without that the fourth
    quarter of every year would look four times the size of the first.
    """
    import uscorp as _uc                                         # noqa: PLC0415
    D = _uc.load()
    R = _uc.ratios(D)
    rq = {}
    for dt, v in zip(D["date"], R["r"]):
        if v is not None:
            y, m, _ = dt.split("-")
            rq[(int(y), (int(m) - 1) // 3 + 1)] = v
    s = fred.series("FEDFUNDS")
    ffq = {}
    for dt, v in zip(s["date"], s["value"]):
        y, m, _ = dt.split("-")
        ffq.setdefault((int(y), (int(m) - 1) // 3 + 1), []).append(v / 100.0)
    ffq = {k: sum(v) / len(v) for k, v in ffq.items()}

    bank = usbank.quarterly(start=start)
    rows = []
    for rd in sorted(bank):
        t = bank[rd]
        yr, q = int(rd[:4]), (int(rd[4:6]) - 1) // 3 + 1
        if not t.get("EQ") or not t.get("ASSET"):
            continue
        key = (yr, q)
        if key not in rq or key not in ffq:
            continue
        EQ, FUND = t["EQ"], t["ASSET"] - t["EQ"]
        rows.append({
            "rd": rd, "year": yr, "q": q, "label": f"{yr}Q{q}",
            "r": rq[key],
            "rB": (t["NETINC"] + t.get("ITAX", 0.0)) / EQ,     # PRE-TAX, to match r
            "fund": t["EINTEXP"] / FUND,
            "ff": ffq[key], "EQ": EQ, "FUND": FUND, "EINTEXP": t["EINTEXP"],
        })
    return rows


def quarterly_beta(rows):
    """Pass-through, estimated on the quarterly panel rather than the annual one."""
    x = np.array([w["ff"] for w in rows])
    y = np.array([w["fund"] for w in rows])
    A = np.column_stack([np.ones(len(x)), x])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    r2 = 1 - ((y - A @ b) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return b[0], b[1], r2, len(rows)


#: Policy cycles, by their turning points in the fed funds rate. Betas are measured
#: WITHIN a cycle rather than from a panel spanning several, because a long regression
#: lets its intercept absorb regime differences and the slope then means little: the
#: 1990-2025 annual fit returns 0.647, which is higher than any single cycle on record.
CYCLES = [
    ("hike 2004-06", "2004Q2", "2006Q3", "up"),
    ("hike 2015-19", "2015Q4", "2019Q1", "up"),
    ("hike 2021-23", "2021Q4", "2023Q4", "up"),
    ("cut 2000-03", "2000Q3", "2003Q2", "down"),
    ("cut 2007-10", "2007Q3", "2010Q2", "down"),
    ("cut 2019-20", "2019Q1", "2020Q2", "down"),
    ("cut 2024-now", "2024Q2", None, "down"),
]


def cycle_betas(rows, lag=4):
    """Cumulative pass-through within each policy cycle: d(funding cost) / d(policy rate).

    The funding cost LAGS policy, so each cycle is extended up to `lag` quarters past the
    policy turn, to wherever the funding cost itself turns. Scoring a hiking cycle at the
    policy peak would grade it before the deposit repricing has finished arriving -- in
    2021-23 the funds rate plateaued in 2023Q4 and funding cost went on rising to 2024Q3.
    """
    idx = {w["label"]: i for i, w in enumerate(rows)}
    out = []
    for lab, a, b, direction in CYCLES:
        if a not in idx:
            continue
        j = idx[b] if (b and b in idx) else len(rows) - 1
        seg = range(j, min(j + lag + 1, len(rows)))
        pick = max if direction == "up" else min
        j2 = pick(seg, key=lambda k: rows[k]["fund"])
        dff = rows[j2]["ff"] - rows[idx[a]]["ff"]
        dfd = rows[j2]["fund"] - rows[idx[a]]["fund"]
        if abs(dff) < 1e-6:
            continue
        out.append({"label": lab, "dir": direction, "from": a, "to": rows[j2]["label"],
                    "dff": dff, "dfund": dfd, "beta": dfd / dff})
    return out


def implied_from_cycle_beta(w, beta):
    """Policy rate for equalisation, anchored LOCALLY on where the rate actually is.

        ip = ff_now + (fund_eq - fund_now) / beta

    A cycle beta is a slope on CHANGES, so it is applied as a change from the current
    observation. That drops the intercept entirely, and the intercept is exactly where a
    long panel hides its regime shifts. Applied this way the answer stops depending on the
    estimation window: across all seven cycles it moves 0.28pp, against 2.12pp when the
    same question is asked of panel regressions with their intercepts.
    """
    extra = (w["rB"] - w["r"]) * w["EQ"]
    fund_eq = (w["EINTEXP"] + extra) / w["FUND"]
    return w["ff"] + (fund_eq - w["fund"]) / beta, fund_eq


def both_sides_beta(rows, start=QSTART):
    """Pass-through on BOTH sides of the bank balance sheet, and hence on the margin.

    THIS IS THE CHECK THAT BREAKS THE PRESCRIPTION, so it is run every time.

    The equalising calculation holds interest INCOME fixed and solves for the interest
    EXPENSE that would bring rB down to r. That is only a policy prescription if raising
    the policy rate raises expense without raising income. It does not: assets reprice at
    about 0.49 per point of policy and liabilities at about 0.50, so the NET INTEREST
    MARGIN barely moves -- a coefficient of 0.037 with an R-squared of 0.08, which is not
    distinguishable from zero.

    So there is no policy rate at which banking earns only the general rate. The lever
    does not move the target. What the equalising rate measures is how far banking's
    profitability sits above the general rate, expressed in policy-rate units; it is not a
    statement about where the policy rate should be.
    """
    bank = usbank.quarterly(start=start)
    qmap = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}
    ff, yld, fnd, nim = [], [], [], []
    for w in rows:
        t = bank.get(f"{w['year']}{qmap[w['q']]}")
        if not t or not t.get("ASSET"):
            continue
        ff.append(w["ff"])
        yld.append(t["INTINC"] / t["ASSET"])
        fnd.append(w["fund"])
        nim.append((t["INTINC"] - t["EINTEXP"]) / t["ASSET"])

    def slope(x, y):
        A = np.column_stack([np.ones(len(x)), np.array(x)])
        b, *_ = np.linalg.lstsq(A, np.array(y), rcond=None)
        r2 = 1 - ((np.array(y) - A @ b) ** 2).sum() / ((np.array(y) - np.mean(y)) ** 2).sum()
        return b[1], r2

    return {"asset": slope(ff, yld), "liability": slope(ff, fnd), "margin": slope(ff, nim)}


def run_quarterly(start=QSTART):
    """Quarterly panel, with the pass-through measured per CYCLE rather than by panel.

    This supersedes the panel-regression approach the annual path still uses. A regression
    over 1990-2025 returns a beta of 0.647 -- higher than any single policy cycle on
    record -- because its intercept absorbs the regime differences between them, and the
    implied policy rate then divides by that slope. Measuring within cycles and anchoring
    locally removes both problems.
    """
    rows = quarterly_panel(start)
    if not rows:
        raise SystemExit("no quarterly rows -- is the FDIC cache populated?")
    print(f"QUARTERLY PANEL  {rows[0]['label']} to {rows[-1]['label']}  "
          f"({len(rows)} quarters)")
    print("")

    cb = cycle_betas(rows)
    print("PASS-THROUGH, MEASURED WITHIN EACH POLICY CYCLE")
    print(f"  {'cycle':>14} {'from':>8} {'to':>8} {'d ff':>9} {'d fund':>9} {'beta':>7}")
    for c in cb:
        print(f"  {c['label']:>14} {c['from']:>8} {c['to']:>8} {c['dff']*100:+8.2f}pp "
              f"{c['dfund']*100:+8.2f}pp {c['beta']:7.3f}")
    ups = [c["beta"] for c in cb if c["dir"] == "up"]
    dns = [c["beta"] for c in cb if c["dir"] == "down"]
    allb = [c["beta"] for c in cb]
    print(f"  hiking  mean {np.mean(ups):.3f}      cutting mean {np.mean(dns):.3f}")
    print("  Near enough symmetric, which is worth noting: the folk story is that deposit")
    print("  rates are sticky going up and quick coming down. Over these cycles they are")
    print("  not. The 2015-19 hike is the one outlier at 0.303 -- a tightening that began")
    print("  from ZIRP with the system awash in reserves, so banks had no need to compete")
    print("  for deposits at all.")
    print("")

    bs = both_sides_beta(rows, start)
    print("BEFORE READING ANY OF THIS AS A PRESCRIPTION")
    print(f"  pass-through, asset side      {bs['asset'][0]:+.3f}   R2 {bs['asset'][1]:.3f}")
    print(f"  pass-through, liability side  {bs['liability'][0]:+.3f}   R2 {bs['liability'][1]:.3f}")
    print(f"  net interest margin           {bs['margin'][0]:+.3f}   R2 {bs['margin'][1]:.3f}")
    print("  Both sides reprice at about the same speed, so the margin is very nearly")
    print("  INVARIANT to the policy rate. The calculation below holds interest income")
    print("  fixed and solves for the expense that brings rB down to r -- but raising the")
    print("  policy rate raises income too, by about as much. There is no policy rate at")
    print("  which banking earns only the general rate: the lever does not move the target.")
    print("")
    print("  So read what follows as a MEASURE OF HOW FAR BANKING SITS ABOVE THE GENERAL")
    print("  RATE, expressed in policy-rate units. It is not a statement about where the")
    print("  policy rate should be.")
    print("")

    w = rows[-1]
    _ip0, fund_eq = implied_from_cycle_beta(w, allb[0])
    print(f"THE MEASURE  ({w['label']})")
    print(f"  r {w['r']:.4f}   banking rB (pre-tax) {w['rB']:.4f}   "
          f"gap {(w['rB']-w['r'])*100:+.2f}pp")
    print(f"  funding cost {w['fund']*100:.2f}%  ->  needs {fund_eq*100:.2f}% for rB = r")
    print(f"  actual fed funds {w['ff']*100:.2f}%")
    print("")
    print(f"  {'beta source':>26} {'beta':>7} {'implied ip':>11} {'vs actual':>10}")
    named = [("current cycle", cb[-1]["beta"]),
             ("mean, cutting cycles", float(np.mean(dns))),
             ("mean, hiking cycles", float(np.mean(ups))),
             ("mean, all cycles", float(np.mean(allb)))]
    ips = []
    for lab, bta in named:
        ip, _ = implied_from_cycle_beta(w, bta)
        ips.append(ip)
        print(f"  {lab:>26} {bta:7.3f} {ip*100:10.2f}% {(ip-w['ff'])*100:+9.2f}pp")
    print(f"  -> {min(ips)*100:.2f}% to {max(ips)*100:.2f}%, a spread of "
          f"{(max(ips)-min(ips))*100:.2f}pp")
    print("")
    print("  WHY THIS SUPERSEDES THE PANEL VERSION. Asked of panel regressions with their")
    print("  intercepts, the same question spans 2.12pp -- 3.48% on the 1990-2025 annual")
    print("  fit up to 5.79% on a 2010-onward quarterly one -- and the choice of window")
    print("  decides the policy verdict. Measured per cycle and anchored on where the rate")
    print("  actually is, it spans a quarter of a point.")
    print("")

    bcur = cb[-1]["beta"]
    for x in rows:
        x["ip"], _ = implied_from_cycle_beta(x, bcur)
        x["gap"] = x["ip"] - x["ff"]
    print(f"  {'quarter':>8} {'r':>7} {'rB':>7} {'rB-r':>8} {'implied ip':>11} "
          f"{'fed funds':>10} {'gap':>9}")
    for x in rows[-12:]:
        print(f"  {x['label']:>8} {x['r']:7.4f} {x['rB']:7.4f} "
              f"{(x['rB']-x['r'])*100:+7.2f}pp {x['ip']*100:10.2f}% "
              f"{x['ff']*100:9.2f}% {x['gap']*100:+8.2f}pp")
    print(f"  (path uses the current-cycle beta of {bcur:.3f})")
    print("")
    print("  Quarterly is noisier than annual and should be. 2023Q4 shows rB at 0.078")
    print("  against 0.151 the quarter before -- the FDIC special assessment after that")
    print("  year's failures, not a change in banking's normal profitability. Read the")
    print("  level, not the wiggle.")


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
    if "--quarterly" in sys.argv:
        run_quarterly()
    else:
        main()
        print("")
        print("  For the quarterly panel and the pass-through sensitivity it exposes:")
        print("      python3 models/equalise.py --quarterly")
