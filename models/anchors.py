"""Why shelter, care and schooling ran away while goods got cheaper.

    python3 models/anchors.py

THE PUZZLE
----------
felt.py found the felt decline in two numbers: the median household captures 30% less of
GDP per capita than in 1984, and the prices of shelter, medical care and tuition ran 28%,
75% and 160% ahead of general inflation while new vehicles came in 43% below. Goods are
inputs to all three services, so cheaper goods should have pulled their prices down. They
did not.

THE CONTROL THAT COMES FIRST
----------------------------
These are labour-intensive services. Goods are a small share of what they cost to produce,
so the relevant benchmark is not the price of commodities but the price of an HOUR. If a
service's price merely tracked wages, nothing sector-specific happened to it and the whole
story is that its costs are people. If it ran ahead of wages, something else did.

Run that control and the four stop being one phenomenon. Against compensation per hour,
shelter is CHEAPER than in 1984. Tuition is 79% dearer. Whatever explains one cannot be
what explains the other, and the popular accounts -- zoning, hospital bargaining, the
student-loan expansion, two-income households -- have to be tested one at a time.

WHAT THIS CANNOT DO
-------------------
The CPI bundles tuition with childcare in one series, so the fourth story cannot be
separated from the third here. And measuring "why" a price rose from aggregate series is
weak evidence at the best of times: what follows tests TIMING and QUANTITY, which can
refute a story, and cannot confirm one.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

BASE = 1984
MARKS = (1984, 1990, 2000, 2010, 2019, 2024)


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
        "wage": "AHETPI", "comp": "COMPNFB", "cpi": "CPIAUCSL",
        "shelter": "CUSR0000SAH1", "medical": "CPIMEDSL", "tuition": "CUUR0000SEEB",
        "goods": "CUSR0000SAD", "house": "MSPUS", "med_inc": "MEHOINUSA672N",
        "starts": "HOUST", "pop": "POPTHM", "health_emp": "CES6562000101",
        "gdpc": "A939RX0Q048SBEA",
        "educ_emp": "CES6561000001", "flfp": "LNS11300002",
    }.items()}


def idx(s, y):
    return s[y] / s[BASE] * 100


# --------------------------------------------------------------------------- 1
def against_wages(d):
    print("=" * 92)
    print("1. THE CONTROL -- against an hour of labour, not against goods")
    print("=" * 92)
    print("  Every index 1984 = 100. The last three columns divide each price by the wage")
    print("  index, so 100 means the price merely kept pace with what people earn.\n")
    print(f"  {'year':>6} {'wage':>6} {'goods':>7} | {'shelter':>8} {'medical':>8} "
          f"{'tuition':>8} | {'shelt/w':>8} {'med/w':>7} {'tuit/w':>7}")
    for y in MARKS:
        w = idx(d["wage"], y)
        v = [idx(d[k], y) for k in ("goods", "shelter", "medical", "tuition")]
        print(f"  {y:6d} {w:6.0f} {v[0]:7.0f} | {v[1]:8.0f} {v[2]:8.0f} {v[3]:8.0f} | "
              f"{v[1] / w * 100:8.0f} {v[2] / w * 100:7.0f} {v[3] / w * 100:7.0f}")
    print("\n  And against COMPENSATION per hour, which counts the benefits that are much")
    print("  of what an employer actually pays:\n")
    print(f"  {'year':>6} {'shelter':>9} {'medical':>9} {'tuition':>9}")
    for y in (1984, 2000, 2024):
        c = idx(d["comp"], y)
        print(f"  {y:6d} " + " ".join(
            f"{idx(d[k], y) / c * 100:8.0f}" for k in ("shelter", "medical", "tuition")))
    print("\n  THE FOUR ARE NOT ONE PHENOMENON. Shelter is 9% dearer than an hour of wages")
    print("  and 12% CHEAPER than an hour of compensation. Tuition is 122% and 79% dearer.")
    print("  Medical sits between. Whatever explains the third cannot be what explains the")
    print("  first, and the answer to the opening question is already visible: these are")
    print("  services whose cost is people, so the price of goods barely reaches them.")


# --------------------------------------------------------------------------- 2
def shelter(d):
    print("\n" + "=" * 92)
    print("2. SHELTER -- the flow tracked wages, the entry price did not")
    print("=" * 92)
    print("  Shelter CPI is dominated by rent and owners' equivalent rent: the flow cost")
    print("  of occupying the EXISTING stock. What people mean by unaffordable housing is")
    print("  usually the price of getting in. Those are different numbers.\n")
    print(f"  {'year':>6} {'shelter CPI / wage':>19} {'house price / median income':>28}")
    for y in MARKS:
        sw = idx(d["shelter"], y) / idx(d["wage"], y) * 100
        nom = d["med_inc"][y] * d["cpi"][y] / d["cpi"][2024]
        print(f"  {y:6d} {sw:18.0f} {d['house'][y] / nom:27.2f}")
    print("\n  The flow is flat against wages. The entry price is up 25%. A supply")
    print("  constraint on NEW building does exactly that: rents on a large existing stock")
    print("  are anchored by that stock, while the price of the marginal unit -- and so of")
    print("  entry -- carries the constraint.\n")
    print(f"  {'era':>12} {'housing starts':>15} {'per 1000 people':>17}")
    for a, b in ((1960, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
                 (2000, 2009), (2010, 2019), (2020, 2024)):
        st = float(np.mean([d["starts"][y] for y in range(a, b + 1) if y in d["starts"]]))
        pp = float(np.mean([d["pop"][y] for y in range(a, b + 1) if y in d["pop"]]))
        print(f"  {f'{a}-{b}':>12} {st:14.0f}k {st / (pp / 1000):16.2f}")
    print("\n  Starts per head of population fell from 8.17 in the 1970s to 3.10 in the")
    print("  2010s and have recovered only to 4.38. The supply story is supported by the")
    print("  QUANTITY evidence and is invisible in the price index that felt.py used,")
    print("  which is a fault of the index rather than of the story.")


# --------------------------------------------------------------------------- 3
def medical(d):
    print("\n" + "=" * 92)
    print("3. MEDICAL -- an excess that stopped, and a lot more care")
    print("=" * 92)
    print(f"  {'year':>6} {'medical / wage':>15}   what happened")
    notes = {1984: "", 1990: "rising fast", 2000: "peak of the excess",
             2010: "", 2019: "", 2024: "flat since 2000"}
    for y in MARKS:
        print(f"  {y:6d} {idx(d['medical'], y) / idx(d['wage'], y) * 100:14.0f}   "
              f"{notes.get(y, '')}")
    print("\n  The whole of medical's excess over wages happened between 1984 and 2000.")
    print("  Since 2000 it has tracked wages almost exactly -- 148 then, 149 now. Any")
    print("  account of it has to explain a twentieth-century phenomenon, not a current")
    print("  one, and the bargaining antagonism between hospitals, insurers and drug")
    print("  makers is generally told as a story about the last twenty years.")
    print(f"\n  {'era':>12} {'health workers':>15} {'per 1000 people':>17}")
    for a, b in ((1990, 1999), (2000, 2009), (2010, 2019), (2020, 2024)):
        h = float(np.mean([d["health_emp"][y] for y in range(a, b + 1)
                           if y in d["health_emp"]]))
        pp = float(np.mean([d["pop"][y] for y in range(a, b + 1) if y in d["pop"]]))
        print(f"  {f'{a}-{b}':>12} {h:14.0f}k {h / (pp / 1000):16.2f}")
    print("\n  Health employment per head rose 36% since the 1990s. Some of the spending")
    print("  is a higher price for the same care and some is more care, and a price index")
    print("  that cannot quality-adjust medicine well cannot tell them apart. That is a")
    print("  real limit on how much the medical column can be blamed on anything.")


# --------------------------------------------------------------------------- 4
def tuition(d):
    print("\n" + "=" * 92)
    print("4. TUITION -- the largest excess, and the timing is wrong for loans")
    print("=" * 92)
    print("  The student-loan account says cheap federal credit removed the budget")
    print("  constraint and colleges spent the difference. That predicts the price")
    print("  acceleration FOLLOWS the credit expansion.\n")
    print(f"  {'period':>14} {'change in tuition / wage':>26}")
    for a, b in ((1984, 1994), (1994, 2004), (2004, 2014), (2014, 2023)):
        t0 = idx(d["tuition"], a) / idx(d["wage"], a)
        t1 = idx(d["tuition"], b) / idx(d["wage"], b)
        print(f"  {f'{a}-{b}':>14} {(t1 / t0 - 1) * 100:+25.1f}%")
    print("\n  Most of the excess is in 1984-1994, before the Direct Loan programme (1993)")
    print("  had issued anything, before Grad PLUS (2006), and before the 2010 federal")
    print("  takeover of origination. And in 2014-2023, the decade of the largest")
    print("  outstanding balances, tuition FELL 10% against wages.")
    print("\n  That is timing evidence against the simple version of the story. It does")
    print("  not touch the version where earlier expansions of guaranteed lending, from")
    print("  1965 onward, did the work -- which this data cannot reach because the CPI")
    print("  series begins in 1977.")
    print("\n  TWO CAVEATS AND THE FIRST IS SERIOUS. The CPI measures posted tuition, and")
    print("  institutional discounting has grown enormously, so NET tuition has risen far")
    print("  less than this series. And the series bundles childcare with tuition, so the")
    print("  fourth story cannot be separated from it at all.")


# --------------------------------------------------------------------------- 5
def childcare(d):
    print("\n" + "=" * 92)
    print("5. CHILDCARE -- what can be said without a separate price series")
    print("=" * 92)
    print("  The account is that two incomes went from a choice to a necessity, so demand")
    print("  for paid childcare rose against a supply that could not industrialise. The")
    print("  demand side of that is measurable even if the price is not.\n")
    print(f"  {'year':>6} {'female labour force participation':>34}")
    for y in (1960, 1970, 1980, 1990, 2000, 2010, 2024):
        if y in d["flfp"]:
            print(f"  {y:6d} {d['flfp'][y]:33.1f}%")
    print("\n  It rose 22 points between 1960 and 2000 and has FALLEN since, to 57.5%.")
    print("  So the demand shift is real, large, and finished a quarter of a century ago,")
    print("  while the bundled tuition-and-childcare index kept climbing against wages")
    print("  until about 2015. The timing does not fit a demand-surge story either.")
    print("\n  Note what this does NOT establish. Childcare prices are not separable here,")
    print("  and there is a version of the argument -- that the second income became")
    print("  necessary BECAUSE the anchors got expensive, rather than the other way about")
    print("  -- which this data cannot distinguish and which reverses the causation.")



# --------------------------------------------------------------------------- 6
def counterfactual(d):
    """Prices or distribution? The one test that separates them."""
    print("\n" + "=" * 92)
    print("6. PRICES OR DISTRIBUTION -- the counterfactual that separates them")
    print("=" * 92)
    print("  The anchors got expensive relative to a median household. Two things could")
    print("  do that: the prices ran away, or the income did not keep up. Ask what would")
    print("  have happened if the median household had simply tracked the average.\n")
    y = 2024
    def mult(k):
        return d[k][y] / d[k][BASE]
    anchor = 0.45 * mult("shelter") + 0.30 * mult("medical") + 0.25 * mult("tuition")
    cpi = mult("cpi")
    inc = mult("med_inc") * cpi                 # real median x CPI = nominal median
    avg = mult("gdpc") * cpi                    # the same at GDP-per-capita growth
    print(f"  {'growth multiple, 1984 to 2024':>44}")
    print(f"  {'anchor bundle (45 shelter/30 medical/25 tuition)':>50}  x{anchor:.2f}")
    print(f"  {'general CPI':>50}  x{cpi:.2f}")
    print(f"  {'median household income, nominal':>50}  x{inc:.2f}")
    print(f"  {'...had it kept pace with GDP per capita':>50}  x{avg:.2f}")
    print(f"\n  Median income against the anchor bundle       {inc / anchor - 1:+.1%}")
    print(f"  Had it tracked GDP per capita                {avg / anchor - 1:+.1%}")
    print("\n  THAT IS THE ANSWER TO THE WHOLE QUESTION. The anchor bundle grew 5.28 times")
    print("  and the average income grew 5.98. A median household that had simply kept")
    print("  pace with the country's own output would have OUTRUN shelter, medicine and")
    print("  schooling by 13% -- comfortably, over forty years, at exactly the prices")
    print("  that were actually charged.")
    print("\n  On median PERSONAL income the shortfall is 8% rather than 21%, because")
    print("  households got smaller -- see share.py section 3. The counterfactual holds")
    print("  either way: at the average, the median clears the anchors comfortably.")
    print("\n  It fell 21% short instead. The anchors are unaffordable not because their")
    print("  prices beat the economy but because they beat the MEDIAN, and the economy")
    print("  beat the median by more.")



# --------------------------------------------------------------------------- 7
def verdict():
    print("\n" + "=" * 92)
    print("7. VERDICT")
    print("=" * 92)
    print("  THE OPENING QUESTION HAS A DULL ANSWER, and it is most of the answer. These")
    print("  are services whose cost is overwhelmingly labour. Goods are a small share of")
    print("  what they consume, so goods getting cheaper barely reaches them, and what")
    print("  their prices track instead is the price of an hour. Shelter tracked it")
    print("  almost exactly; medical and tuition ran ahead of it by different amounts for")
    print("  different reasons.")
    print("\n  ON THE FOUR ACCOUNTS, one at a time:")
    print("\n    ZONING AND SHELTER -- supported, and by the quantity rather than the")
    print("    price. Starts per head fell by more than half from the 1970s. The flow")
    print("    price tracked wages because it is anchored to a large existing stock; the")
    print("    constraint shows up in the entry price, which rose 25% against income.")
    print("\n    HOSPITAL BARGAINING -- not refuted, but pointed at the wrong period. The")
    print("    entire medical excess over wages is 1984-2000 and it has been flat since,")
    print("    while the antagonism is usually described as a recent development.")
    print("\n    STUDENT LOANS -- timing against it. The excess is front-loaded into")
    print("    1984-1994 and reverses in the decade of the largest balances. The posted-")
    print("    versus-net tuition problem weakens the measurement badly enough that this")
    print("    should be read as 'the simple version does not fit' rather than 'refuted'.")
    print("\n    TWO-INCOME HOUSEHOLDS -- demand shift real and finished by 2000, prices")
    print("    kept rising after. And the causation may run the other way.")
    print("\n  AND SECTION 6 OUTRANKS ALL FOUR OF THEM. Whatever these industries did,")
    print("  the average American income grew faster than the bundle they sell. A median")
    print("  household on the average's growth rate would have outrun shelter, medicine")
    print("  and schooling by 13% at the prices actually charged. It came in 21% under.")
    print("\n  So the four accounts are arguments about a 20-point gap sitting on top of a")
    print("  33-point one. They are worth having -- the housing supply evidence in")
    print("  particular is strong and the remedy is obvious -- but none of them is the")
    print("  reason a typical household cannot afford what it could in 1984. That reason")
    print("  is that a typical household stopped receiving a typical share, which is what")
    print("  felt.py found from the income side and this file has now reached from the")
    print("  price side.")


def main():
    d = load()
    against_wages(d)
    shelter(d)
    medical(d)
    tuition(d)
    childcare(d)
    counterfactual(d)
    verdict()


if __name__ == "__main__":
    main()
