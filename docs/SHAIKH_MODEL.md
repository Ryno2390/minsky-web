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

## Result 1 — the claim, on balanced paths

**The table first published here was a 12-period transient** (see the ladder section). Each
margin, on its own balanced path:

| m | ip | r | rE | g | u |
|---|---|---|---|---|---|
| 0.040 | 0.02514 | 0.06514 | 0.02000 | 0.02500 | 0.754 |
| 0.030 | 0.03851 | 0.06851 | 0.02000 | 0.02500 | 0.793 |
| 0.020 | 0.05219 | 0.07219 | 0.02000 | 0.02500 | 0.835 |
| 0.010 | 0.06621 | 0.07621 | 0.02000 | 0.02500 | 0.882 |
| 0.005 | 0.07335 | 0.07835 | 0.02000 | 0.02500 | 0.907 |
| 0.000 | 0.08059 | 0.08059 | 0.02000 | 0.02500 | 0.933 |

`g` and `rE` are both **constant**. That is not a failure of the mechanism, it is what a
labour-constrained growth model must say: accumulation has to equal α+β, and the investment
function then forces `rE = rEnorm`. Neither is free to move.

What the margin moves is the **level**: utilisation from 0.754 to 0.933, and the profit rate
with it. Read properly that is a Shaikhian statement, and a sharper one than the original —
**a tighter margin does not slow accumulation, it requires a higher profit rate and a higher
level of activity to sustain the same accumulation.** The burden falls on distribution, not
on growth.

The growth statement survives where growth is accumulation-determined rather than
labour-determined: in the core and rungs 1–2, which have no labour force,
`dg*/dm = κ·d* = 0.95` exactly. Which regime an economy is in is an empirical question.

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

## Result 2b — how much of a policy move reaches the borrower

**The table first published here was also a transient.** On balanced paths `rE` is pinned,
so the deposit channel cannot change it — what it changes is how much of a policy move
reaches the lending rate at all, and how far utilisation must travel to absorb the rest.

| deposits pay | ip moves | iL moves | pass-through | u moves |
|---|---|---|---|---|
| nothing | 0.0400 | 0.0000 | **0.000** | 0.000 |
| 0.3 × policy | 0.0455 | 0.0068 | 0.150 | 0.063 |
| 0.6 × policy | 0.0554 | 0.0193 | **0.348** | 0.179 |
| 0.9 × policy | 0.0833 | 0.0541 | 0.649 | 0.501 |

The 0.35 originally published was right in size and wrong in provenance: it is the **full
model's** structural pass-through, where the demand side pins the spread — not rung 1's,
where the spread is free and nothing pins it.

And the top row is the striking one. **With costless bank funding, monetary policy is
completely neutral here**: equalisation pins the lending rate outright, `iL` does not move
at all, and neither does utilisation. The whole policy change is absorbed into the spread.

So the potency of monetary policy in this model rests entirely on banks having a funding
cost that moves with the policy rate. That is Shaikh's second condition doing real work —
the spread is a distributive variable, and how much of it competition eats decides whether
policy reaches enterprise at all.

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

## The ladder — and a measurement error that invalidated the first version

An earlier version of this section reported `dg/dm` of 0.950 / 0.332 / 0.078 across the
rungs, called it a twelve-fold gap, and attributed 71% of it to banking. **That was wrong.**
The defect is worth recording because it is easy to repeat.

Each rung's `compare()` swept the margin `m` while leaving the SOLVED quantities — the bank
payout `payB` and bank capital `EB` — at the values solved for the *baseline* margin. Every
run except the baseline therefore started off its own balanced path and drifted. The slope
measured a transient, and it grew without bound with the horizon:

| horizon | rung 1 `dg/dm` | full model `dg/dm` |
|---|---|---|
| 12 | 0.36 | 0.062 |
| 30 | 0.55 | 0.634 |
| 60 | 1.08 | 3.916 |

Re-solving the baseline at each margin — so every run sits on **its own** balanced path —
gives an exact rest point every time (`rE` drifts by 7e-18, bank capital per unit of capital
by zero) and a slope that does not move with the horizon at all.

### The structural answer

| model | `dg/dm` | theory |
|---|---|---|
| core | **0.9500** | `κ·d*` |
| + banking | **0.9500** | `κ·d*` — banking changes nothing |
| + equity, ψ=0.25 | 0.7125 | `κ(1−ψ)d₁` |
| + equity, ψ=0.50 | 0.4750 | `κ(1−ψ)d₁` |
| + equity, ψ=0.75 | 0.2375 | `κ(1−ψ)d₁` |

**Banking does not damp the mechanism. It damps the transition to it.** Equalisation pins a
relation between the spread and bank capital, not the spread itself, so on a balanced path
the spread is free and the margin passes through whole. Over twelve periods from a common
start only about a third of it has arrived — which is a real and interesting fact about
adjustment speed, and not the comparative static I reported it as.

### And the rungs do not all close the same way

| msh | g* | r | u | rE |
|---|---|---|---|---|
| 0.040 | 0.02500 | 0.06514 | 0.754 | 0.02000 |
| 0.030 | 0.02500 | 0.06851 | 0.793 | 0.02000 |
| 0.020 | 0.02500 | 0.07219 | 0.835 | 0.02000 |
| 0.010 | 0.02500 | 0.07621 | 0.882 | 0.02000 |

The core and rungs 1 and 2 have no labour force, so growth is whatever accumulation
delivers and the margin sets it. The full model has productivity and labour-force growth,
so **its balanced growth rate is pinned at α+β and the margin cannot change it at all**.
What the margin moves there is the *level*: utilisation from 0.754 to 0.882, and the profit
rate with it.

So comparing their slopes as though they measured one quantity was a category error. The
mechanism operates on the growth *rate* where growth is accumulation-determined, and on the
*level and distribution* where it is labour-determined. Both are Shaikhian readings; they
are not the same claim.

`models/ladder.py` is the corrected comparison. Read it rather than the per-rung
`--compare` output, which still prints transients.

## Rung 2: corporate equity — and a correction

The write-up above claimed bank deposits were only 0.47 of the loan book "because
households hold no equity claim on firms' capital", and that giving them one would raise
the deposit base and let more of a policy move through. **That was wrong**, and rung 1's
own arithmetic says so. The bank balance sheet there is an identity, `DH = L − EB`, and
bank capital is pinned by equalisation:

    EB/L = (iL − iD − omegaB) / (r − iD)  =  0.562

a function of the lending rate, the deposit rate, operating costs and `r`, **and of nothing
else**. No household portfolio enters it. Bank leverage is high here because banks earn a
fat net margin — 3.9% of the loan book — and equalisation then demands the capital to match.
Getting `EB/L` to a realistic 0.1 needs `iL` near 0.040, not a different asset for
households to hold.

Measured directly, turning the equity dial from 0 to 0.75 moves `DH/L` from 0.465 to 0.451.
It does essentially nothing, exactly as the identity says.

### What corporate equity actually does

Firms meet the gap between what they invest and what they retain by borrowing *or* by
issuing shares. With `psi` the share met by issuance, leverage settles at

    d* = (1 − psi) * (1 − (1−payF)/kappa)

so the external financing requirement is split by `psi`, and **only the debt half carries an
interest bill**. Since the mechanism runs entirely through that bill:

| psi | d* | E/K | DH/L | dg/dm (12-period) | κ·d* (structural) | ratio |
|---|---|---|---|---|---|---|
| 0.00 | 0.7917 | 0.000 | 0.465 | 0.332 | 0.950 | 0.349 |
| 0.25 | 0.5938 | 0.198 | 0.460 | 0.238 | 0.713 | 0.334 |
| 0.50 | 0.3958 | 0.396 | 0.456 | 0.152 | 0.475 | 0.320 |
| 0.75 | 0.1979 | 0.594 | 0.451 | 0.073 | 0.238 | 0.307 |

`d*` falls one for one with `psi` and `E/K` fills the gap — both structural, confirmed on
balanced paths. The `dg/dm` column is a 12-period transient (see the ladder section); the
structural slope is exactly `κ(1−ψ)d₁`, the next column. Either way it falls one for one
with leverage, which is the finding.

**Corporate equity changes the STRENGTH of the mechanism, through leverage. It does not
change the TRANSMISSION, which is the bank's business.** The two factors in
`dg/dm = κ·d* × pass-through` turn out to be governed by different sectors: firms' financing
mix sets the first, banks' funding mix sets the second.

There is a policy statement in it. Growth *rises* with `psi` — 0.028 to 0.069 at the
baseline margin — because equity carries no interest bill. So equity-financed accumulation
is faster and nearly untouchable by policy; debt-financed accumulation is slower and
controllable. **The profit-rate-of-enterprise channel is a channel only to the extent that
firms borrow.**

`models/enterprise_equity.py` → `EnterpriseEquity.mky`, 91 items. At `psi = 0` it
reproduces rung 1 exactly. Real capital is financed by debt, outside equity and retained
earnings, and `K = L + E + RE` is integrated from four separate flows and checked rather
than enforced: it holds to 7e-13.

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
