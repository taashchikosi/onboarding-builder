"""Security layer: the intake DOCUMENT is untrusted input.

Two guards:
  1. screen_intake() — scans the raw SOW/transcript for injected unsafe
     instructions (privilege escalation, security-disable, data exfiltration,
     destructive ops, prompt-injection). Returns the flagged lines; the agent
     REFUSES these at the plan stage and never compiles them into actions.
  2. is_permitted() — an allow-list of object types/operations. The prompt is
     NOT the boundary; this list + the scoped sandbox credential are.
"""
import re

# Only these object types may ever be provisioned by the auto-builder.
ALLOWED_OBJECT_TYPES = {"pipeline", "custom_field", "user_role", "automation_rule", "integration"}
ALLOWED_OPS = {"create", "update", "noop"}

# Patterns that must NEVER become an action, even if they appear in the intake.
UNSAFE_PATTERNS = [
    (r"grant\s+(admin|owner|super[\s-]?user|root)", "privilege escalation"),
    (r"make\s+\S+\s+(an?\s+)?admin", "privilege escalation"),
    (r"(disable|turn\s+off|bypass)\s+(sso|mfa|2fa|two[\s-]?factor|security|audit)", "security control disable"),
    (r"(export|email|send|forward)\s+(all\s+)?(customer|user|contact|client)s?\b", "data exfiltration"),
    (r"\b(delete|drop|wipe|purge|truncate)\b", "destructive operation"),
    (r"(ignore|disregard|override)\s+(the\s+)?(previous|above|prior|system)\s+(instruction|prompt|rule)", "prompt injection"),
    (r"add\s+\S+@(?!{customer_domain})\S+\.\S+\s+as\s+(admin|owner)", "external admin grant"),
    (r"grant\s+access\s+to\s+\S+@\S+", "external access grant"),
]


def screen_intake(text):
    """Return list of (line, reason) for every unsafe instruction found."""
    flagged = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        for pat, reason in UNSAFE_PATTERNS:
            if re.search(pat, low):
                flagged.append((line, reason))
                break
    return flagged


def is_permitted(otype, op):
    return otype in ALLOWED_OBJECT_TYPES and op in ALLOWED_OPS


def line_is_unsafe(line):
    low = line.lower()
    for pat, reason in UNSAFE_PATTERNS:
        if re.search(pat, low):
            return reason
    return None
