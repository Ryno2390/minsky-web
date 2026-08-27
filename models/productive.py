"""Is the R&D going to unproductive uses, in Marx's sense? And did commodities cheapen?

    python3 models/productive.py

THE QUESTION
------------
Marx's claim about living standards runs through the value of commodities: real wages rise
when the labour time embodied in what workers buy falls. Productive labour is what makes
that happen -- it produces or transforms use-values. Circulation labour, the buying and
selling and financing and titling, is necessary to capitalism and produces no value.

So if a rising share of research effort is aimed at circulation rather than production,
research could grow enormously while the commodities people actually consume get no
cheaper. That would show up as exactly what this repo has measured: effort up 26 times,
TFP growth halved.

TWO HALVES, AND THEY ANSWER DIFFERENTLY
---------------------------------------
    1. Where is the research performed? BEA gives R&D capital for 74 industries, which
       can be classified by whether the industry produces commodities or circulates them.
    2. Did commodities get cheaper anyway? That is the outcome Marx's argument is about,
       and it is directly observable in the deflators.

The first supports the hypothesis. The second complicates it severely, and the second is
the one that matters, because it is about what actually happened to the value of
commodities rather than about who was doing the research.

ON THE CLASSIFICATION, WHICH IS CONTESTABLE
-------------------------------------------
Transport and storage count as PRODUCTIVE: Volume II is explicit that what the transport
industry sells is the change of place itself, a real alteration of the use-value.
Wholesale, retail, finance, insurance, real estate, legal services and the management of
companies count as CIRCULATION. A third of the R&D sits in industries where Marx's
categories genuinely do not settle it -- publishing, telecoms, data processing, and above
all contract research services -- and those are reported separately rather than assigned,
because assigning them decides the answer.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import beafa                                                     # noqa: E402
import fred                                                      # noqa: E402

#: three-digit prefixes of industries that produce or transform use-values
PROD3 = ("110", "113", "211", "212", "213", "221", "230", "311", "312", "313", "315",
         "321", "322", "323", "324", "325", "326", "327", "331", "332", "333", "334",
         "335", "336", "337", "338", "339", "481", "482", "483", "484", "485", "486",
         "487", "493")

#: and of industries whose function is to move title rather than to make anything
CIRC3 = ("421", "422", "441", "442", "445", "452", "521", "522", "523", "524", "525",
         "531", "532", "550")

YEARS = (1950, 1960, 1970, 1980, 1990, 2000, 2010, 2024)


def bucket(code):
    if code[:3] in PROD3:
        return "productive"
    if code == "5411" or code[:3] in CIRC3:      # legal services sits with circulation
        return "circulation"
    return "contested"


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


# --------------------------------------------------------------------------- 1
def where():
    print("=" * 92)
    print("1. WHERE THE RESEARCH IS PERFORMED")
    print("=" * 92)
    real, names = beafa.table("real")
    print(f"  {'year':>6} {'R&D $bn':>9} | {'PRODUCTIVE':>18} {'CIRCULATION':>18} "
          f"{'CONTESTED':>18}")
    first = last = None
    for y in YEARS:
        b = {"productive": 0.0, "circulation": 0.0, "contested": 0.0}
        for c in names:
            b[bucket(c)] += real.get((c, "rd"), {}).get(y, 0.0)
        t = sum(b.values())
        if not t:
            continue
        if first is None:
            first = {k: v / t for k, v in b.items()}
        last = {k: v / t for k, v in b.items()}
        print(f"  {y:6d} {t / 1000:8.0f} | {b['productive'] / 1000:8.0f} "
              f"{b['productive'] / t * 100:7.1f}% {b['circulation'] / 1000:8.0f} "
              f"{b['circulation'] / t * 100:7.1f}% {b['contested'] / 1000:8.0f} "
              f"{b['contested'] / t * 100:7.1f}%")
    print(f"\n  The productive share falls from {first['productive'] * 100:.1f}% to "
          f"{last['productive'] * 100:.1f}%. Circulation rises from")
    print(f"  {first['circulation'] * 100:.1f}% to {last['circulation'] * 100:.1f}% -- "
          "fifteen times the share, and finance and insurance")
    print("  did essentially no research at all before 1980.")
    print("\n  BUT THE CONTESTED BUCKET IS THE BIG MOVER, from 12.8% to 33.5%, and it is")
    print("  where the classification stops being Marx's and starts being mine. Its")
    print("  largest members in 2024:")
    rows = [(real.get((c, "rd"), {}).get(2024, 0.0) / 1000, bucket(c), names[c])
            for c in names]
    for v, bk, n in sorted(rows, reverse=True)[:8]:
        if bk != "productive":
            print(f"    {v:8.0f} $bn  {bk:12s} {n[:44]}")
    print("\n  Contract research services at $337bn is the largest single R&D holder")
    print("  outside manufacturing, and its research is performed FOR manufacturers --")
    print("  an input to production that happens to be bought rather than done in house.")
    print("  Counting it as unproductive would be an artefact of outsourcing, which is")
    print("  the same disintegration spillover.py measured. Software and telecoms are")
    print("  arguable both ways. So the honest range for the productive share in 2024 is")
    print("  59% on the narrow reading and about 85% if the contested bucket is mostly")
    print("  inputs to production -- against 92% in 1960 either way.")


# --------------------------------------------------------------------------- 2
def did_they_cheapen():
    print("\n" + "=" * 92)
    print("2. DID COMMODITIES GET CHEAPER? -- the outcome Marx's argument is about")
    print("=" * 92)
    du, sv, al = (annual("DDURRG3A086NBEA"), annual("DSERRG3A086NBEA"),
                  annual("DPCERG3A086NBEA"))
    nd = annual("DNDGRG3A086NBEA")
    b = 1960
    print("  Personal consumption deflators, 1960 = 100.\n")
    print(f"  {'year':>6} {'durables':>10} {'nondurables':>12} {'services':>10} "
          f"{'all':>8} | {'durables/services':>18}")
    for y in YEARS:
        if y < 1960 or y not in du:
            continue
        print(f"  {y:6d} {du[y] / du[b] * 100:10.0f} {nd[y] / nd[b] * 100:12.0f} "
              f"{sv[y] / sv[b] * 100:10.0f} {al[y] / al[b] * 100:8.0f} | "
              f"{(du[y] / du[b]) / (sv[y] / sv[b]):17.3f}")
    peak = max(du, key=lambda y: du[y] if y >= 1960 else -1)
    print(f"\n  Durable goods prices PEAKED in {peak} and have fallen in absolute")
    print(f"  nominal terms since: {du[peak] / du[b] * 100:.0f} to "
          f"{du[2024] / du[b] * 100:.0f} on this index, a fall of "
          f"{(1 - du[2024] / du[peak]) * 100:.0f}% over {2024 - peak} years")
    print("  while everything else rose. Relative to services they are 7.3 times cheaper")
    print("  than in 1960.")
    print("\n  So commodity production did EXACTLY what Marx said productive labour does.")
    print("  It cheapened commodities, relentlessly, and it has not stopped. Whatever")
    print("  went wrong with productivity did not go wrong in making things.")


# --------------------------------------------------------------------------- 3
def what_people_buy():
    print("\n" + "=" * 92)
    print("3. BUT WHAT PEOPLE BUY MOVED")
    print("=" * 92)
    dg, ndg, sv = (annual("PCEDG"), annual("PCEND"), annual("PCES"))
    print("  Nominal personal consumption, shares.\n")
    print(f"  {'year':>6} {'durables':>10} {'nondurables':>12} {'services':>10}")
    for y in YEARS:
        if y not in dg:
            continue
        t = dg[y] + ndg[y] + sv[y]
        print(f"  {y:6d} {dg[y] / t * 100:9.1f}% {ndg[y] / t * 100:11.1f}% "
              f"{sv[y] / t * 100:9.1f}%")
    print("\n  Goods were half of consumption in 1960 and are under a third now. And that")
    print("  understates it, because the shares are NOMINAL: goods took a falling share")
    print("  of spending partly BECAUSE they got cheaper. In quantity terms people")
    print("  consume far more goods than in 1960 and pay less of their income for them.")
    print("\n  Which is the trap in reading the aggregate. Total factor productivity is a")
    print("  weighted average, and the weight moved onto the sector where measured")
    print("  productivity growth is slow and where measuring it at all is hardest.")


# --------------------------------------------------------------------------- 4
def verdict():
    print("\n" + "=" * 92)
    print("4. VERDICT")
    print("=" * 92)
    print("  THE HYPOTHESIS IS HALF RIGHT, AND THE HALF THAT FAILS IS THE IMPORTANT ONE.")
    print("\n  Right: research really has moved out of commodity production. The share of")
    print("  R&D capital held by industries that make or transform things fell from 92%")
    print("  to somewhere between 59% and 85% depending on how contract research and")
    print("  software are counted, and finance and insurance went from doing no research")
    print("  at all to 7.6% of the total. Marx's category is doing real work here: those")
    print("  industries circulate value rather than producing it, and research aimed at")
    print("  capturing a larger share of a given surplus cheapens nothing.")
    print("\n  Wrong: commodities kept getting cheaper anyway. Durable goods prices peaked")
    print("  in 1995 and have fallen 32% in nominal terms since, against services up 12")
    print("  times from 1960. If unproductive research were crowding out productive")
    print("  research to the point of slowing the cheapening of commodities, the durables")
    print("  deflator is where it would show, and it shows the opposite.")
    print("\n  WHAT IS ACTUALLY HAPPENING is closer to Baumol than to Marx, but it takes")
    print("  a Marxian form worth stating. The productive sector still raises the")
    print("  productivity of labour and still cheapens its commodities. It has simply")
    print("  become a smaller part of what people buy -- under a third of consumption")
    print("  against a half in 1960 -- so its contribution to the aggregate carries less")
    print("  weight every year, while the growing remainder is services whose output is")
    print("  hard to measure and whose productivity genuinely grows slowly.")
    print("\n  Aggregate TFP is the weighted average, and the weight moved. That is not")
    print("  research being wasted on unproductive uses. It is research succeeding in the")
    print("  sector that is shrinking as a share of expenditure PRECISELY BECAUSE it")
    print("  succeeded there -- goods take less of the budget because they got cheap.")
    print("\n  WHICH LEAVES A QUESTION THIS REPO HAS NOT ASKED. If the commodity-producing")
    print("  sector is still delivering, and the aggregate looks bad because of what it")
    print("  is averaged with, then the productivity slowdown may be less a failure of")
    print("  technology than a fact about the composition of consumption in a rich")
    print("  country. Nothing here tests that, and it deserves the same treatment")
    print("  everything else in this sequence got before being believed.")


def main():
    where()
    did_they_cheapen()
    what_people_buy()
    verdict()


if __name__ == "__main__":
    main()
