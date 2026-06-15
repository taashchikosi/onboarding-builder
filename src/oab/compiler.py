"""Intake (SOW / discovery transcript) -> DesiredState.

Two compilers so the eval can measure the value of engineering discipline:

  compile_engineered(): synonym-aware headers, TYPE-AWARE field/automation/
      integration parsing, parent inference, ambiguity detection
      (-> needs_clarification, never a silent guess), and unsafe-line screening.
      This is the reference behaviour the real LLM must match/beat.

  compile_baseline(): a naive single-pass parse (what an ungoverned 'LLM writes
      the config' does): keyword-guess the type, no parent inference, no synonym
      map, no ambiguity handling, NO safety screen. Lower precision + recall.

When OAB_DEEPSEEK_KEY is set, get_provider() returns DeepSeekLLM and the
engineered path uses the model's extraction (then still validates + screens).
"""
import re
from .schema import ConfigObject, DesiredState, PARENT_OF
from .policy import line_is_unsafe
from .llm import get_provider

HEADER_SYNONYMS = {
    "pipeline": "pipeline", "pipelines": "pipeline", "deal stage": "pipeline",
    "deal stages": "pipeline", "stages": "pipeline",
    "property": "custom_field", "properties": "custom_field",
    "custom field": "custom_field", "custom fields": "custom_field",
    "field": "custom_field", "fields": "custom_field",
    "role": "user_role", "roles": "user_role", "permission": "user_role",
    "permissions": "user_role",
    "workflow": "automation_rule", "workflows": "automation_rule",
    "automation": "automation_rule", "automations": "automation_rule",
    "integration": "integration", "integrations": "integration",
    "connected app": "integration", "connected apps": "integration", "apps": "integration",
}
AMBIGUOUS_MARKERS = ("tbd", "?", "either", " or ", "not sure", "depends")


def _customer(text):
    m = re.search(r"customer\s*:\s*(.+)", text, re.I)
    return m.group(1).strip() if m else "Customer"


def _match_header(line):
    """Return canonical type if this line is a section header, else None."""
    if not line.endswith(":"):
        return None
    head = line.rstrip(":").strip().lower()
    if head in HEADER_SYNONYMS:
        return HEADER_SYNONYMS[head]
    # combined headers like 'Pipelines / Deal Stages:' or 'Roles / Permissions:'
    for syn, t in HEADER_SYNONYMS.items():
        if re.search(r"\b" + re.escape(syn) + r"\b", head):
            return t
    return None


def _ambiguous(text):
    low = " " + text.lower() + " "
    return any(mk in low for mk in AMBIGUOUS_MARKERS)


def _from_llm_json(data, intake_text):
    """Build a validated, SAFETY-RE-SCREENED DesiredState from LLM JSON.
    Defense in depth: even though the prompt forbids unsafe objects, we re-screen
    every emitted object here — the model is untrusted too."""
    customer = (data.get("customer") or _customer(intake_text)).strip()
    objects = []
    valid_types = set(PARENT_OF.keys())
    for o in data.get("objects", []):
        if not isinstance(o, dict):
            continue
        otype = str(o.get("otype", "")).strip()
        name = str(o.get("name", "")).strip()
        if otype not in valid_types or not name:
            continue
        value = str(o.get("value", "") or name).strip()
        parent = o.get("parent")
        parent = str(parent).strip() if parent else None
        # SECURITY re-screen: drop any object whose text trips the unsafe guard
        if line_is_unsafe(f"{name} {value}") or (parent and line_is_unsafe(parent)):
            continue
        objects.append(ConfigObject(
            otype=otype, name=name, value=value, parent=parent,
            needs_clarification=bool(o.get("needs_clarification", False)),
        ))
    return DesiredState(customer=customer, objects=objects)


def compile_engineered(text, provider=None):
    provider = provider or get_provider()
    if provider.name != "mock":
        data = provider.extract(text)            # real LLM extraction
        if data is not None:
            return _from_llm_json(data, text)     # used + re-screened + validated
        # provider failed -> graceful fallback to deterministic rules below

    customer = _customer(text)
    objects = []
    cur_type = None
    last_pipeline = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("customer:"):
            continue
        if line.lower().startswith("notes:"):
            cur_type = None
            continue
        if line_is_unsafe(line):                 # SECURITY: never compile unsafe lines
            continue

        t = _match_header(line)
        if t:
            cur_type = t
            continue
        if cur_type is None or not line.startswith(("-", "*", "•")):
            continue

        content = line.lstrip("-*• ").strip()
        ambiguous = _ambiguous(content)
        name, value, parent = content, content, None

        if cur_type == "pipeline":
            if ":" in content:
                name, value = (s.strip() for s in content.split(":", 1))
            last_pipeline = name

        elif cur_type == "user_role":
            if ":" in content:
                name, value = (s.strip() for s in content.split(":", 1))

        elif cur_type == "custom_field":
            m = re.search(r"\bon\s+(.+)$", content, re.I)        # explicit parent
            if m:
                parent = m.group(1).strip()
                content = content[:m.start()].strip()
            elif last_pipeline:
                parent = last_pipeline                            # inferred parent
            else:
                ambiguous = True                                  # nothing to attach to
            fm = re.match(r"(.+?)\s*(\([^)]*\))\s*$", content)    # 'Name (type)'
            if fm:
                name, value = fm.group(1).strip(), fm.group(2).strip()
            elif ":" in content:
                name, value = (s.strip() for s in content.split(":", 1))
            else:
                name = value = content

        elif cur_type == "automation_rule":
            # prefer an explicit reference verb ('uses'/'references') over a stray
            # 'on' inside the rule name (e.g. 'Notify on stage change uses Field').
            m = re.search(r"\b(uses|references)\s+(.+)$", content, re.I) \
                or re.search(r"\bon\s+(?!stage\b)(.+)$", content, re.I)
            if m:
                parent = m.groups()[-1].strip()
                name = content[:m.start()].strip()
                value = parent
            else:
                ambiguous = True
                name = value = content

        elif cur_type == "integration":
            name = value = content.split("(")[0].strip()

        if name:
            objects.append(ConfigObject(
                otype=cur_type, name=name, value=value or name,
                parent=parent, needs_clarification=ambiguous,
            ))

    return DesiredState(customer=customer, objects=objects)


def compile_baseline(text):
    """Naive: guess type from the first keyword on each bullet; no parents,
    no synonym inference, no ambiguity handling, no safety screen."""
    customer = _customer(text)
    objects = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(("-", "*", "•")):
            continue
        content = line.lstrip("-*• ").strip()
        name, value = (content.split(":", 1) + [content])[:2] if ":" in content else (content, content)
        name, value = name.strip(), value.strip()
        low = content.lower()
        if "pipeline" in low or "stage" in low:
            t = "pipeline"
        elif "role" in low or "permission" in low:
            t = "user_role"
        elif "integration" in low or "slack" in low or "gmail" in low or "jira" in low or "zendesk" in low:
            t = "integration"
        elif "workflow" in low or "automation" in low or "notify" in low or "escalate" in low:
            t = "automation_rule"
        else:
            t = "custom_field"
        objects.append(ConfigObject(otype=t, name=name, value=value or name, parent=None))
    return DesiredState(customer=customer, objects=objects)
