"""Declarative diff: desired-state vs current workspace -> a plan of actions.
Renders a `terraform plan`-style diff a human approves before anything mutates.
"""
from dataclasses import dataclass
from .schema import PARENT_OF


@dataclass
class Action:
    op: str            # create | update | noop
    obj: object        # ConfigObject

    @property
    def key(self):
        return self.obj.key


def plan(desired, actual_by_key):
    """actual_by_key: {(otype,name): value} from the live adapter."""
    actions = []
    for o in desired.applyable():
        cur = actual_by_key.get(o.key)
        if cur is None:
            actions.append(Action("create", o))
        elif cur != o.value:
            actions.append(Action("update", o))
        else:
            actions.append(Action("noop", o))
    return actions


def topo_order(actions):
    """Order so a parent object is always applied before its children."""
    depth = {None: 0}
    order = {ot: (0 if PARENT_OF[ot] is None else 1) for ot in PARENT_OF}
    # custom_field depends on pipeline (1), automation_rule on custom_field (2)
    order["automation_rule"] = 2
    return sorted(actions, key=lambda a: order.get(a.obj.otype, 1))


def render_diff(actions, customer="Customer"):
    sym = {"create": "+", "update": "~", "noop": " "}
    lines = [f"Plan for: {customer}", "-" * 52]
    n_c = n_u = n_n = 0
    for a in topo_order(actions):
        s = sym[a.op]
        par = f"  (on {a.obj.parent})" if a.obj.parent else ""
        lines.append(f" {s} {a.obj.otype:<16} {a.obj.name}{par}")
        n_c += a.op == "create"; n_u += a.op == "update"; n_n += a.op == "noop"
    lines.append("-" * 52)
    lines.append(f" Plan: {n_c} to create, {n_u} to update, {n_n} unchanged.")
    return "\n".join(lines), (n_c, n_u, n_n)
