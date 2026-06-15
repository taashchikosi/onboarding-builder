"""Typed desired-state model for a customer workspace (the 'onboarding-as-code' core).

Pure stdlib (dataclasses) so the whole engine runs with no installs. The same
shapes are mirrored by the Pydantic models in api.py for the FastAPI layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional

# Object types and their REQUIRED parent type (None = top-level). This is the
# dependency graph the planner topo-sorts and the applier orders by.
PARENT_OF = {
    "pipeline": None,
    "user_role": None,
    "integration": None,
    "custom_field": "pipeline",       # a field lives on a pipeline
    "automation_rule": "custom_field" # a rule references a field
}
OBJECT_TYPES = tuple(PARENT_OF.keys())


@dataclass(frozen=True)
class ConfigObject:
    otype: str                 # one of OBJECT_TYPES
    name: str                  # unique within (otype) for a scenario
    value: str                 # the concrete config (stage list, field type, role perms...)
    parent: Optional[str] = None          # name of the parent object (if PARENT_OF[otype])
    needs_clarification: bool = False      # ambiguous requirement -> ask, don't guess

    @property
    def key(self):
        return (self.otype, self.name)

    def validate(self):
        if self.otype not in OBJECT_TYPES:
            return f"unknown object type '{self.otype}'"
        if PARENT_OF[self.otype] is not None and not self.parent:
            return f"{self.otype} '{self.name}' requires a {PARENT_OF[self.otype]} parent"
        if not self.value:
            return f"{self.otype} '{self.name}' has no config value"
        return None


@dataclass
class DesiredState:
    customer: str = "Customer"
    objects: list = field(default_factory=list)   # list[ConfigObject]

    def by_key(self):
        return {o.key: o for o in self.objects}

    def applyable(self):
        """Objects safe to apply = validated and not awaiting clarification."""
        return [o for o in self.objects if o.validate() is None and not o.needs_clarification]

    def validation_errors(self):
        errs = []
        for o in self.objects:
            e = o.validate()
            if e:
                errs.append(e)
        return errs

    def to_dict(self):
        return {"customer": self.customer, "objects": [asdict(o) for o in self.objects]}
