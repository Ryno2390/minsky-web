"""Run a saved Minsky model headlessly and hand back the paths.

Why not the simulation socket? Because this reloads between runs, so an override left over
from the previous experiment cannot contaminate the next one, and because a batch of
experiments wants paths rather than frames.

NOT because the socket is slow. It once cost ~55ms a step against the engine's own ~1.5ms,
and that number was quoted here for a while, but it was a defect rather than a property and
it is fixed: `live_value_ids()` was being called once per value key from inside a
comprehension, and value objects are now bound once per run. The socket also takes `every`
and `maxFps`. Do not avoid it on performance grounds.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/minsky-web"))
from minskyweb import headless as H          # noqa: E402

#: Default solver.
#:
#: The comparison here is against THIS REPO's defaults, not Minsky's, and the distinction
#: was wrong in this comment for a while. Minsky itself ships epsRel=1e-2, epsAbs=1e-3 and
#: the EXPLICIT method (schema/simulation.h) -- far too loose to measure anything with.
#: What ships at 1e-8/1e-10/implicit is minskyweb's own SANE_SOLVER (headless.py), applied
#: on clear(), which is what a model built through this repo actually starts from.
#:
#: Against that: implicit at 1e-8/1e-10 takes 0.0005-long steps at 45ms each on this model,
#: so t=40 would be an hour. The explicit method at 1e-6/1e-8 takes steps 140x longer at
#: 1/30th the cost, and agrees with the tight implicit run to the tolerance `--check`
#: reports.
SOLVER = dict(implicit=False, epsRel=1e-6, epsAbs=1e-8)


class Run:
    """One loaded model, reloadable, so a series of experiments share a process."""

    def __init__(self, path, solver=None):
        self.path = os.path.expanduser(path)
        self.solver = dict(SOLVER, **(solver or {}))
        self.m = H.Model()
        self.mk = self.m.minsky
        self._load()

    def _load(self):
        self.mk.load(self.path)
        self.mk.implicit(self.solver["implicit"])
        self.mk.epsRel(self.solver["epsRel"])
        self.mk.epsAbs(self.solver["epsAbs"])
        self._ids = {}
        for ref, it in self.m.all_raw():
            if not it.classType().startswith("Variable:"):
                continue
            try:
                nm = it.name()
            except Exception:
                continue
            self._ids.setdefault(nm, it.valueId())

    def use(self, path):
        """Point this runner at a different model.

        pyminsky is one model per process, so comparing two models means loading them
        alternately rather than holding both.
        """
        self.path = os.path.expanduser(path)
        self._load()
        return self

    def go(self, tmax, watch, overrides=None, samples=400, max_steps=400_000):
        """Reload, apply `overrides`, run to `tmax`, and sample `watch` along the way.

        Reloading rather than resetting because pyminsky is one model per process: an
        override left over from the previous experiment would silently contaminate the
        next one, and nothing would say so.
        """
        self._load()
        for nm, val in (overrides or {}).items():
            self.m.set_init(nm, val)
        self.m.reset()
        missing = [nm for nm in watch if nm not in self._ids]
        if missing:
            raise SystemExit(f"not in the model: {missing}")
        vv = self.mk.variableValues
        ids = {nm: self._ids[nm] for nm in watch}
        out = {nm: [] for nm in watch}
        out["t"] = []

        def sample():
            out["t"].append(self.mk.t())
            for nm, vid in ids.items():
                out[nm].append(vv[vid].value())

        sample()
        every = max(1, int(tmax / max(samples, 1) / 0.07))   # ~`samples` rows
        n = 0
        while self.mk.t() < tmax and n < max_steps:
            self.mk.step()
            n += 1
            if n % every == 0:
                sample()
        sample()
        out["steps"] = n
        if self.mk.t() < tmax * 0.999:
            raise SystemExit(f"the run stalled at t={self.mk.t():.3f} after {n} steps")
        return out
