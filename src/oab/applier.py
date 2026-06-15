"""Safe apply: idempotent, dependency-ordered, retried, and REVERSIBLE.

Guarantees:
  * idempotency  — an object already present is skipped (re-run = no-op).
  * ordering     — parents applied before children (topo order from planner).
  * resilience   — transient failures retried with backoff (capped).
  * atomicity    — if any object can't be applied after retries, every object
                   created in THIS run is rolled back (compensating delete), so
                   the workspace is never left half-built.
"""
import time
from .planner import topo_order
from .adapters import TransientError, ManualStepRequired


class ApplyResult:
    def __init__(self):
        self.applied = []        # keys successfully applied
        self.skipped = []        # idempotent no-ops
        self.manual = []         # types the target can't auto-provision (honest manual step)
        self.rolled_back = []    # keys undone after a failure
        self.failed = None       # the action that defeated retries
        self.ok = True

    def __repr__(self):
        return (f"<ApplyResult ok={self.ok} applied={len(self.applied)} "
                f"skipped={len(self.skipped)} manual={len(self.manual)} "
                f"rolled_back={len(self.rolled_back)}>")


def apply(actions, adapter, *, max_retries=4, backoff=0.0, dry_run=False):
    res = ApplyResult()
    if dry_run:
        res.skipped = [a.key for a in actions]
        return res

    actual = adapter.list_objects()
    created_this_run = []

    supports = getattr(adapter, "supports", lambda o: True)
    norm = getattr(adapter, "normalize", lambda o, v: v)

    for a in topo_order(actions):
        if a.op == "noop":
            res.skipped.append(a.key)
            continue
        # honest manual step: target can't auto-provision this type (e.g. roles in HubSpot)
        if not supports(a.obj.otype):
            res.manual.append(a.key)
            continue
        # idempotency: already present with an equivalent value -> skip (vocab-normalised)
        if norm(a.obj.otype, actual.get(a.key)) == norm(a.obj.otype, a.obj.value):
            res.skipped.append(a.key)
            continue

        ok = False
        manual = False
        for attempt in range(max_retries):
            try:
                if a.op == "create":
                    adapter.create(a.obj)
                    created_this_run.append(a.key)
                else:
                    adapter.update(a.obj)
                ok = True
                break
            except ManualStepRequired:
                manual = True        # not a failure — a documented manual step
                break
            except TransientError:
                if backoff:
                    time.sleep(backoff * (2 ** attempt))
                continue

        if manual:
            res.manual.append(a.key)
            continue

        if not ok:
            # ROLLBACK everything this run created, then report clean failure
            res.ok = False
            res.failed = a.key
            for k in reversed(created_this_run):
                adapter.delete(k)
                res.rolled_back.append(k)
            res.applied = []
            return res

        res.applied.append(a.key)

    return res
