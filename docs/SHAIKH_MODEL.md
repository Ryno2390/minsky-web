# A monetary policy model on Shaikh's profit-rate-of-enterprise principle

    python3 models/shaikh_monetary_policy.py                 # build and save
    python3 models/shaikh_monetary_policy.py --run           # the experiments
    python3 models/shaikh_monetary_policy.py --stability     # how long the path lasts

Built through the HTTP API against a server on 8800; saved as
`~/minsky-models/ShaikhMonetaryPolicy.mky`. 215 items, 220 wires, three Godley tables.

## The argument

What drives accumulation is not the profit rate but the profit rate **net of interest** —
Shaikh's rate of profit of enterprise:

    rE = r − iL·d          r  pre-interest profit rate, Π/pK
                           iL the rate firms borrow at
                           d  leverage, L/pK

Net investment is financed out of what is left after the creditor is paid, so
accumulation keys off `rE`. That gives policy an observable anchor, and two rules to
compare:

    SHAIKH   ip = r − m                                    keyed to the profit rate
    TAYLOR   ip = r* + π + aπ(π − π*) + aU(u − u*)         keyed to inflation and slack

Shaikh's second condition is that banking is a business, so competition equalises **its**
profit rate with the general rate. That pins the spread rather than the level, and it is
written as a tendency, not an identity, because that is the actual claim — rates are
equalised by capital moving in and out, always overshooting:

    rB = (iL·L − iD·DH − OpC) / EB          d(spread)/dt = ths·(r − rB)

The two rules are calibrated to **agree at the baseline** (`r*` = the baseline policy
rate, `π*` = 0, `u*` = the baseline utilisation), so any later difference is a difference
in how they respond, not in where they start.

## The accounting

Three Godley tables — banks, firms, households — sharing the stocks they hold against
each other. Every payment appears twice and every row nets to zero
(assets − liabilities − equity).

Real capital K is deliberately **not** in a table: it is not a financial claim on anybody,
so it has no counterparty and no place on a balance sheet of claims. It is an ordinary
integral, which is what Keen's own Minsky models do.

Two identities fall out of the accounting and are **imposed nowhere**, so they are real
tests. Both are checked against every run:

| identity | why it holds | worst observed |
|---|---|---|
| `Res + Loans = DF + DH + EB` | the banking balance sheet closes | 3.7e-15 |
| `DF` constant | firms borrow exactly their financing gap | 2.3e-13 |

## Calibration

The baseline is **solved**, not guessed, so the model starts on a balanced growth path.
Three things are solved rather than chosen, because the theory decides them:

- **the spread**, from banking's profit rate equalising on to `r`. Choosing it by hand
  would have thrown Shaikh's second condition away and then quietly assumed it back.
- **`payB`**, the bank payout ratio that leaves bank capital growing at `g` rather than
  at `r`, so leverage does not drift.
- **`rEnorm`**, the enterprise profit rate consistent with the target leverage.

| | | | |
|---|---|---|---|
| `r` 0.0685 | `rE` 0.0200 | `rB` 0.0685 | `spread` 0.0221 |
| `ip` 0.0385 | `iL` 0.0606 | `iD` 0.0231 | leverage 0.800 |
| `u` 0.793 | `ω` 0.7407 | `g` 0.0250 | `λ` 0.875 |

Interest takes **70.8%** of pre-interest profit. Opening balance sheet residual: exactly 0.

Verified as a rest point: every derivative sits on its balanced-growth value to 1e-7, and
over 30 periods no rate moves by more than 3.7e-04.

## Result 1 — the claim itself

Squeeze the margin the central bank holds below `r`. Nothing is assumed: accumulation is
driven by `rE`, and `rE` is whatever `r` minus the interest bill turns out to be.

| margin m | ip | r | rE | g |
|---|---|---|---|---|
| 0.040 | 0.0117 | 0.0469 | 0.0194 | 0.0252 |
| 0.030 | 0.0385 | 0.0685 | 0.0200 | 0.0250 |
| 0.020 | 0.0524 | 0.0725 | 0.0148 | 0.0240 |
| 0.010 | 0.0645 | 0.0748 | 0.0097 | 0.0230 |
| 0.005 | 0.0703 | 0.0756 | 0.0073 | 0.0226 |
| 0.000 | 0.0760 | 0.0763 | 0.0049 | 0.0221 |
| −0.010 | 0.0871 | 0.0774 | 0.0001 | 0.0212 |

As policy is pushed up towards and past the pre-interest profit rate, the profit of
enterprise is squeezed to nothing and accumulation falls with it. The claim holds.

One refinement the model insists on: the threshold is **not** `ip = r`. At `m = 0` the
policy rate equals `r` and `rE` is still 0.0049, because what matters is the interest
*bill* against profit, `iL·d` against `r`, and leverage here is 0.8 rather than 1. The
condition is `iL < r/d`. Only at `m = −0.01` is enterprise profit gone.

## Result 2 — protecting the margin and stabilising are different jobs

A money-wage shock. It cuts the profit rate and raises inflation at once, so the rules
pull in opposite directions: Shaikh follows `r` down, Taylor tightens into a falling
profit rate. **Which rule looks better depends on how long you watch.**

| shock | horizon | Shaikh K | lowest rE | Taylor K | lowest rE | better |
|---|---|---|---|---|---|---|
| +0.5% | 20 | 1.656 | +0.0193 | 1.650 | +0.0172 | Shaikh |
| +1% | 20 | 1.660 | +0.0187 | 1.648 | +0.0144 | Shaikh |
| +2% | 20 | 1.652 | −0.0029 | 1.646 | +0.0087 | Shaikh |
| +0.5% | 30 | 2.105 | −0.0126 | 2.118 | +0.0172 | Taylor |
| +1% | 30 | 1.973 | −0.1465 | 2.116 | +0.0144 | Taylor |
| +2% | 30 | 1.856 | −0.2046 | 2.112 | +0.0087 | Taylor |

Over twenty periods the rule does what it claims: the enterprise margin holds up better
than under Taylor. Over thirty it has lost — and **not because the shock got worse**.
Taylor's worst reading is identical at both horizons; Shaikh's keeps deepening. That is
the balanced path being left, not the shock being absorbed.

The cause is the same insulation that makes the rule work on impact. A fixed interest bill
squeezes `rE` when `r` falls, which cuts investment back; that is stabilising, and a rule
that moves `ip` with `r` takes it away. So the mechanism in Result 1 is right and the
policy conclusion does not follow from it. Protecting the enterprise margin and
stabilising accumulation are two objectives, and here they conflict.

A pure policy disturbance separates them: start the policy rate a point high and change
nothing else, and both rules bring it back with the same worst-case margin (+0.0118) and
the same growth. The disagreement is about **distributive** shocks, not the level of rates.

## Result 2b — what a tightening costs enterprise depends on bank funding

Shaikh's second condition does quantitative work, not just closure. Because banking's
profit rate is equalised on to `r`, the spread must widen when the banks' own funding cost
rises — so the lending rate climbs by more than the policy rate.

| deposits pay | m | ip | r | rE | g |
|---|---|---|---|---|---|
| 0.6 × policy | 0.040 | 0.0117 | 0.0469 | 0.0194 | 0.0252 |
| 0.6 × policy | 0.000 | 0.0760 | 0.0763 | **0.0049** | 0.0221 |
| nothing | 0.040 | 0.0286 | 0.0683 | 0.0270 | 0.0264 |
| nothing | 0.000 | 0.0762 | 0.0763 | **0.0198** | 0.0251 |

Closing the margin costs four times as much enterprise profit when deposits bear interest.
Transmission from policy to enterprise runs through the banking sector's balance sheet,
not just through the policy rate.

## Result 3 — the balanced path is unstable

The baseline is a genuine rest point and **not** a stable one. The initial conditions are
snapped to multiples of 1/1024 so the opening balance sheet cancels exactly in binary,
and that 5e-4 nudge is enough to start a departure.

Not numerical: the departure time scales as 1/kappa, which is what an unstable eigenvalue
proportional to kappa looks like.

Leverage is 10% away from where it started at t =

| kappa | gam=0.6 | gam=0.3 |
|---|---|---|
| 0.40 | 52.5 | 63.0 |
| 0.30 | 59.5 | 73.5 |
| 0.20 | 73.5 | 96.2 |
| 0.10 | 115.5 | 154.0 |
| 0.05 | 183.7 | never |

The loop is the **accelerator running through the wage-price spiral**. Setting either
`etap` (price adjustment) or `kappa` (investment response) to zero removes it outright;
damping wage indexation only delays it. Measured directly: with the level and the response
tied together as `g = kappa·rE`, leverage forced `kappa = 1.2` and the accelerator gain
`kappa·d(rE)/d(g)` was **1.76** — a Harrod knife-edge. Separating the level from the
response (`g_target = gnorm + kappa·(rE − rEnorm)`) is what made a stable baseline
possible at all.

The experiments run at `kappa = 0.20` over 30 periods, comfortably inside the window where
the baseline is still flat.

## The core on its own

`models/enterprise_core.py` is the same mechanism with everything else taken out: two
stocks, capital and debt, and the profit rate taken as given. No employment, no prices, no
demand, no banking sector, no Godley table. 40 items against 218.

It is small enough to solve, and what falls out is the claim as a **stability condition**
rather than a simulation. In leverage alone,

    d' = (r - iL*d) * (A - kappa*d)          A = kappa - 1 + payF

with two rest points: `d* = A/kappa`, where leverage settles, and `d = r/iL`, where the
enterprise profit rate is nothing. Linearising at the first gives `f'(d*) = -kappa*rE*`,
so **the growth equilibrium is stable exactly while rE* > 0**. Push the lending rate past
`r/d*` and the only rest point left is the one with no accumulation.

Measured against that, by nudging leverage 1% off `d*`:

| m | rE* | deviation after 80 periods | predicted `exp(-kappa*rE* t)` |
|---|---|---|---|
| 0.040 | +0.02842 | 0.066 | 0.065 |
| 0.030 | +0.02051 | 0.142 | 0.140 |
| 0.006 | +0.00158 | 0.913 | 0.859 |
| 0.000 | −0.00317 | **1.474** | 1.355 |

And growth is linear in the margin, so the elasticity is a number rather than a table:

    g* = kappa * (r*(1 - d*) + (m - s)*d*)        dg*/dm = kappa * d*  =  0.95

The diagram agrees with the paper to **6.6e-17**, and leverage settles on `d*` to 9e-16.

### What the comparison shows

The same sweep in both models, over the same twelve periods:

| m | core g | core r | full g | full r |
|---|---|---|---|---|
| 0.040 | 0.03411 | 0.06851 | 0.02524 | 0.04685 |
| 0.030 | 0.02461 | 0.06851 | 0.02500 | 0.06851 |
| 0.020 | 0.01511 | 0.06851 | 0.02401 | 0.07252 |
| 0.010 | 0.00561 | 0.06851 | 0.02304 | 0.07476 |
| 0.000 | −0.00389 | 0.06851 | 0.02211 | 0.07627 |

**dg/dm: 0.95 in the core, 0.078 in the full model — a factor of twelve.**

The reason is in the last column. In the core, `r` is given and the margin does all the
work. In the full model `r` is not given: it rises as policy tightens, from 0.0469 to
0.0763 across the same sweep, and that rise offsets most of the squeeze. Whether that
offset is a real feature of a monetary economy or an artefact of this model's demand side
is the obvious next question, and it is answerable now that the two can be run side by
side.

## Limits worth knowing

- **Bank leverage is low** (loans ≈ 1.8× bank capital). Households hold no equity claim on
  firms' capital, so deposits are the only financial asset and the deposit base is small
  relative to the loan book. With `rB = r` forced by equalisation, thin funding costs mean
  large bank capital. Adding corporate equity is the obvious next step.
- **`u` is unbounded above.** Output is demand-determined with no capacity ceiling, so
  utilisation can exceed 1.
- **No government, no central bank balance sheet, no default.** Reserves are fixed.
- **One household sector.** Workers and rentiers are not separated, so there is no
  differential saving propensity — which Shaikh would want.
