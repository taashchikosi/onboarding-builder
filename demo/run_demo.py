"""End-to-end CLI demo: intake -> screen -> compile -> PLAN -> approve -> apply
-> reconcile -> re-run(no-op) -> rollback -> runbook. Credential-free.

Run: python3 demo/run_demo.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from oab.compiler import compile_engineered
from oab.policy import screen_intake
from oab.planner import plan, render_diff
from oab.applier import apply
from oab.reconcile import reconcile
from oab.runbook import generate_runbook
from oab.adapters import MockSandboxAdapter

ROOT = os.path.join(os.path.dirname(__file__), "..")
INTAKE = open(os.path.join(ROOT, "eval", "intakes", "acme_sow.txt")).read()


def hr(t): print("\n" + "=" * 60 + f"\n {t}\n" + "=" * 60)


def main():
    hr("1. SECURITY SCREEN — the intake document is untrusted")
    for line, reason in screen_intake(INTAKE):
        print(f"  🔴 REFUSED [{reason}]: {line}")
    print("  -> these are flagged and NEVER compiled into actions.")

    hr("2. COMPILE — SOW -> desired-state config")
    d = compile_engineered(INTAKE)
    print(f"  customer: {d.customer}")
    print(f"  objects compiled: {len(d.objects)} "
          f"({len(d.applyable())} applyable, "
          f"{sum(o.needs_clarification for o in d.objects)} need clarification)")

    hr("3. PLAN — terraform-style diff (nothing has mutated yet)")
    adp = MockSandboxAdapter()
    p = plan(d, adp.list_objects())
    diff, counts = render_diff(p, d.customer)
    print(diff)

    hr("4. APPROVE + APPLY — idempotent, dependency-ordered")
    res = apply(p, adp)
    print(f"  {res}")
    print(f"  created in sandbox: {len(adp.list_objects())} objects, "
          f"duplicates: {adp.duplicate_count()}")

    hr("5. RECONCILE — does built == approved?")
    rec = reconcile(d, adp)
    print(f"  {rec}")
    print("  🟢 PARITY OK — workspace matches the approved plan."
          if rec.parity else "  🔴 drift detected.")

    hr("6. RE-RUN — idempotency proof")
    p2 = plan(d, adp.list_objects())
    res2 = apply(p2, adp)
    print(f"  re-apply -> applied={len(res2.applied)}, skipped(no-op)={len(res2.skipped)}, "
          f"duplicates={adp.duplicate_count()}")
    print("  -> 'No changes. Workspace already matches desired state.'")

    hr("7. ROLLBACK — break an apply on purpose, stay clean")
    bad = MockSandboxAdapter(fail_rate=1.0)
    rb = apply(plan(d, bad.list_objects()), bad, max_retries=3)
    print(f"  forced failure -> ok={rb.ok}, rolled_back={len(rb.rolled_back)}, "
          f"objects left in sandbox={len(bad.list_objects())}")
    print("  -> never half-built: rolled back to clean state.")

    hr("8. RUNBOOK — generated from the reconciled state")
    rb_md = generate_runbook(d, adp)
    out = os.path.join(ROOT, "demo", "acme_runbook.md")
    open(out, "w").write(rb_md)
    print(f"  wrote {out} ({len(rb_md.splitlines())} lines)")
    print("\n  --- runbook preview ---")
    print("\n".join("  " + l for l in rb_md.splitlines()[:14]))


if __name__ == "__main__":
    main()
