"""Why it feels like decline when the aggregates say growth.

    python3 models/felt.py

WHAT THIS IS FOR
----------------
Everything else in this repo diagnoses PRODUCTION: the TFP slowdown, the capital
composition, the return to research. percapita.py found that the living-standards
slowdown is roughly twice the productivity slowdown and that half of it is demography.
This is the other half, and it is the half the question was always about.

Aggregates say American living standards roughly doubled since 1984. Americans report
otherwise, consistently and for decades. Both can be true, and the reconciliation is in
two numbers the aggregates average away:

    WHO GETS IT      real GDP per capita against real MEDIAN household income
    WHAT IT BUYS     the prices of the things that anchor a middle-class life against
                     the prices of the things that got cheap

THE HONEST WARNING ABOUT SECTION 3
----------------------------------
Section 3 deflates median income by a constructed index weighted toward shelter, medical
care and education rather than by the CPI. That is not a neutral operation and the
weights drive the magnitude. It is reported with a sensitivity band, and the reader
should treat the DIRECTION as the finding and the level as an illustration. A household
does buy goods, and goods got cheap; deflating all of income by an anchor-only index
overstates the loss for anyone whose budget is not entirely anchors.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

BASE = 1984           # real median household income starts here
MARKS = (1984, 1990, 2000, 2010, 2019, 2024)


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def series():
    return {
        "med": annual("MEHOINUSA672N"),      # real median household income
        "gdpc": annual("A939RX0Q048SBEA"),   # real GDP per capita
        "cpi": annual("CPIAUCSL"),
        "shelter": annual("CUSR0000SAH1"),
        "medical": annual("CPIMEDSL"),
        "tuition": annual("CUUR0000SEEB"),   # tuition, school fees and childcare
        "vehicles": annual("CUSR0000SETA01"),
        "food": annual("CUSR0000SAF11"),
        "house": annual("MSPUS"),
    }


# --------------------------------------------------------------------------- 1
def who_gets_it(d):
    print("=" * 92)
    print("1. WHO GETS THE GROWTH")
    print("=" * 92)
    print("  Both series are real and per unit -- one per person, one per household at")
    print("  the middle. 1984 = 100.\n")
    print(f"  {'year':>6} {'median household':>18} {'GDP per capita':>16} "
          f"{'median as % of it':>19}")
    for y in MARKS:
        m = d["med"][y] / d["med"][BASE] * 100
        g = d["gdpc"][y] / d["gdpc"][BASE] * 100
        print(f"  {y:6d} {m:17.1f} {g:15.1f} {m / g * 100:18.1f}")
    m = d["med"][2024] / d["med"][BASE]
    g = d["gdpc"][2024] / d["gdpc"][BASE]
    print(f"\n  GDP per capita is up {(g - 1) * 100:.0f}% since 1984. The median household "
          f"is up {(m - 1) * 100:.0f}%.")
    print(f"  The median household captures {(1 - m / g) * 100:.0f}% less of the "
          "average than it did.")
    print("\n  That gap is the first half of the answer and it is not controversial. A")
    print("  person reading their own paycheque against the news about GDP is reading two")
    print("  different numbers, and both are correct.")


# --------------------------------------------------------------------------- 2
def what_it_buys(d):
    print("\n" + "=" * 92)
    print("2. WHAT GOT EXPENSIVE AND WHAT GOT CHEAP")
    print("=" * 92)
    print("  Consumer prices, 1984 = 100. The last column is general inflation, so a")
    print("  number above it is something that outran the average.\n")
    print(f"  {'year':>6} {'shelter':>9} {'medical':>9} {'tuition+care':>13} | "
          f"{'vehicles':>9} {'food':>7} | {'all CPI':>8}")
    for y in MARKS:
        v = [d[k][y] / d[k][BASE] * 100 for k in
             ("shelter", "medical", "tuition", "vehicles", "food", "cpi")]
        print(f"  {y:6d} {v[0]:8.0f} {v[1]:8.0f} {v[2]:12.0f} | {v[3]:8.0f} "
              f"{v[4]:6.0f} | {v[5]:7.0f}")
    c = d["cpi"][2024] / d["cpi"][BASE] * 100
    print(f"\n  Against general inflation of {c:.0f}: tuition and childcare at 786 ran "
          "160% ahead,")
    print("  medical care 75% ahead, shelter 28% ahead. New vehicles at 173 came in 43%")
    print("  BELOW, and everything productive.py measured about durable goods says the")
    print("  same thing.")
    print("\n  So the things that got cheap are the things a household buys once and")
    print("  replaces rarely. The things that got expensive are the recurring ones that")
    print("  decide whether a life is secure: a place to live, care when ill, and the")
    print("  education that is supposed to make the next generation better off.")


# --------------------------------------------------------------------------- 3
def bundle(d):
    print("\n" + "=" * 92)
    print("3. THE SAME INCOME, DEFLATED BY WHAT IT HAS TO BUY")
    print("=" * 92)
    print("  Real median household income, deflated by the CPI and by indices weighted")
    print("  toward the anchors. Weights are stated because they drive the answer.\n")
    mixes = [("CPI as published", None),
             ("25% anchors, 75% CPI", 0.25),
             ("50% anchors, 50% CPI", 0.50),
             ("75% anchors, 25% CPI", 0.75),
             ("anchors only", 1.00)]
    print(f"  {'weighting':>24} " + " ".join(f"{y:>8}" for y in MARKS))
    for label, w in mixes:
        row = []
        for y in MARKS:
            if w is None:
                row.append(d["med"][y] / d["med"][BASE] * 100)
                continue
            anch = (0.45 * d["shelter"][y] / d["shelter"][BASE]
                    + 0.30 * d["medical"][y] / d["medical"][BASE]
                    + 0.25 * d["tuition"][y] / d["tuition"][BASE])
            cp = d["cpi"][y] / d["cpi"][BASE]
            defl = w * anch + (1 - w) * cp
            nominal = d["med"][y] * cp
            row.append(nominal / defl / d["med"][BASE] * 100)
        print(f"  {label:>24} " + " ".join(f"{v:8.1f}" for v in row))
    print("\n  Read the rows as households rather than as alternative truths, and read")
    print("  the middle one first. AT A FIFTY-PERCENT ANCHOR WEIGHT THE MEDIAN HOUSEHOLD")
    print("  IS EXACTLY WHERE IT WAS IN 1984 -- 100.8 against 100.0, forty years of")
    print("  nothing. At a quarter it is up 17%; at three quarters it is down 11%; on")
    print("  anchors alone, down 21%.")
    print("\n  Fifty percent is not an extreme assumption. National accounts put housing")
    print("  near 18% of consumption, healthcare near 17% and education around 3% -- some")
    print("  38% before childcare, and higher for a household raising children in a city.")
    print("\n  And the anchor share rises as income falls, because rent and medicine and")
    print("  childcare do not scale down. The bottom rows are not a worst case, they are")
    print("  where most of the distribution actually sits.")


# --------------------------------------------------------------------------- 4
def house(d):
    print("\n" + "=" * 92)
    print("4. THE ONE NUMBER PEOPLE ACTUALLY QUOTE")
    print("=" * 92)
    print(f"  {'year':>6} {'median new house':>18} {'median household income':>25} "
          f"{'years of income':>16}")
    for y in MARKS:
        nom = d["med"][y] * d["cpi"][y] / d["cpi"][2024]
        print(f"  {y:6d} {d['house'][y]:17,.0f} {nom:24,.0f} "
              f"{d['house'][y] / nom:15.2f}")
    a = d["house"][BASE] / (d["med"][BASE] * d["cpi"][BASE] / d["cpi"][2024])
    b = d["house"][2024] / (d["med"][2024] * d["cpi"][2024] / d["cpi"][2024])
    print(f"\n  From {a:.2f} years of household income to {b:.2f}. Not a collapse, and it "
          "is the")
    print("  most-cited grievance in American economic life. Which is itself informative:")
    print("  the felt decline is not mostly about houses being unaffordable in the")
    print("  arithmetic sense. It is about the whole anchor bundle moving at once.")


# --------------------------------------------------------------------------- 5
def verdict():
    print("\n" + "=" * 92)
    print("5. THE DIAGNOSIS")
    print("=" * 92)
    print("  The feeling is not a misperception and it does not need one to explain it.")
    print("  Two measured things produce it.")
    print("\n  FIRST, the median household captures 30% less of GDP per capita than in")
    print("  1984. Growth happened and most of it went somewhere else. That alone opens a")
    print("  gap between what the country produces and what a typical person receives.")
    print("\n  SECOND, and less remarked, the prices moved apart. The productive sector")
    print("  did its job -- productive.py found durable goods 32% cheaper in nominal terms")
    print("  since 1995 -- but goods are now under a third of consumption. The two thirds")
    print("  that is services contains everything that defines security, and shelter,")
    print("  medical care and schooling all outran general inflation by 28%, 75% and 160%.")
    print("\n  Put together: a household's income rose against a basket dominated by the")
    print("  things that got cheap, and fell against the things it cannot avoid buying.")
    print("  The CPI is not wrong. It is answering a different question from the one")
    print("  people are asking when they say they are worse off.")
    print("\n  WHICH REFRAMES THE WHOLE SEQUENCE. Twelve modules chased the TFP slowdown,")
    print("  and the honest finding was that a fifth is measurable composition and the")
    print("  rest is a collapse in the return to research that nobody can explain. That")
    print("  is a real problem and it is not the one being felt. The felt problem is")
    print("  distribution and relative prices, both of which are measured here in an")
    print("  afternoon and neither of which needs the productivity puzzle solved to be")
    print("  acted on.")
    print("\n  A productivity slowdown is why the pie grew more slowly. It is not why most")
    print("  people got a smaller slice of a pie that still doubled.")


def main():
    d = series()
    who_gets_it(d)
    what_it_buys(d)
    bundle(d)
    house(d)
    verdict()


if __name__ == "__main__":
    main()
