"""Reconciliation: prove the workspace that got built == the approved plan.

Parity is computed over the object types the target can actually provision
(`adapter.supports`). Types it can't auto-provision (e.g. HubSpot roles/automations)
are reported separately as `manual` — they are NOT counted as "missing", because the
agent never claimed to build them. This keeps parity honest (contract §4).
"""
class ReconcileResult:
    def __init__(self):
        self.parity = True
        self.missing = []      # supported keys in desired but absent from actual
        self.drifted = []      # supported keys present but with a different value
        self.manual = []       # keys the target can't auto-provision (documented manual step)
        self.repaired = []

    def __repr__(self):
        return (f"<Reconcile parity={self.parity} missing={len(self.missing)} "
                f"drifted={len(self.drifted)} manual={len(self.manual)} "
                f"repaired={len(self.repaired)}>")


def reconcile(desired, adapter, repair=False):
    res = ReconcileResult()
    supports = getattr(adapter, "supports", lambda o: True)
    norm = getattr(adapter, "normalize", lambda o, v: v)
    actual = adapter.list_objects()
    for o in desired.applyable():
        if not supports(o.otype):
            res.manual.append(o.key)
            continue
        cur = actual.get(o.key)
        if cur is None:
            res.missing.append(o.key)
        elif norm(o.otype, cur) != norm(o.otype, o.value):
            res.drifted.append(o.key)
    res.parity = not (res.missing or res.drifted)
    if repair and not res.parity:
        for o in desired.applyable():
            if not supports(o.otype):
                continue
            cur = actual.get(o.key)
            if cur is None or cur != o.value:
                try:
                    adapter.update(o)
                    res.repaired.append(o.key)
                except Exception:
                    pass
        res = reconcile(desired, adapter, repair=False)  # re-verify, don't assume
    return res
