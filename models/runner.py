"""Run a saved Minsky model headlessly and hand back the paths.

Why not the simulation socket? It emits one frame per solver step with every value in
it, which costs ~55ms a step -- about forty times the engine's own 1.5ms. Over the tens
of thousands of steps a run of this length takes, that is the difference between three
seconds and half an hour. The socket is for watching a model; this is for measuring one.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/minsky-web"))
from minskyweb import headless as H          # noqa: E402

#: Default solver. Minsky ships epsRel=1e-8, epsAbs=1e-10 and the implicit method, which
#: on this model takes 0.0005-long steps at 45ms each -- t=40 would be an hour. The
#: explicit method at 1e-6/1e-8 takes steps 140x longer at 1/30th the cost, and agrees
#: with the tight implicit run to the tolerance reported by `--check`.
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
