"""Generate the customer runbook + kickoff plan FROM the reconciled state
(not a template). Output is markdown; the pdf skill renders it for the case study.
"""
from .schema import PARENT_OF

def generate_runbook(desired, adapter):
    actual = adapter.list_objects()
    by_type = {}
    for o in desired.applyable():
        if o.key in actual:
            by_type.setdefault(o.otype, []).append(o)

    lines = [f"# Onboarding Runbook — {desired.customer}", "",
             "_Generated from the provisioned workspace state (verified by reconcile)._", ""]
    pretty = {"pipeline": "Pipelines", "custom_field": "Custom Fields",
              "user_role": "User Roles", "automation_rule": "Automations",
              "integration": "Integrations"}
    lines += ["## What was built", ""]
    for t in ["pipeline", "custom_field", "user_role", "automation_rule", "integration"]:
        items = by_type.get(t, [])
        if not items:
            continue
        lines.append(f"### {pretty[t]}")
        for o in items:
            par = f" — on **{o.parent}**" if o.parent else ""
            lines.append(f"- **{o.name}**: {o.value}{par}")
        lines.append("")

    lines += ["## Kickoff plan", "",
              "1. Verify pipeline stages with the customer's RevOps lead.",
              "2. Confirm field-level permissions for each role.",
              "3. Dry-run each automation on a test record.",
              "4. Connect integrations and validate the first sync.",
              "5. Schedule the go-live review.", ""]
    clar = [o for o in desired.objects if o.needs_clarification]
    if clar:
        lines += ["## ⚠️ Needs your confirmation (not auto-built)", ""]
        for o in clar:
            lines.append(f"- **{o.name}** ({o.otype}): ambiguous in the intake — confirm before building.")
        lines.append("")
    return "\n".join(lines)
