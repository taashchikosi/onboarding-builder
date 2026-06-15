"""Compile-accuracy eval: compilers vs hand-labeled gold desired-states.

Compilers scored:
  baseline   — naive single-pass keyword guess (no parents, no synonyms, no safety)
  engineered — the rule-based reference (synonym-aware, parent inference, ambiguity, safety)
  deepseek   — the real DeepSeek model (only with --llm; needs OAB_DEEPSEEK_KEY)

Metrics (item-level precision / recall / F1), normalized + free-text-tolerant:
  identity = (otype, name)             -> 'found the right objects?'
  parent   = (otype, name, parent)     -> 'wired dependencies right?' (the hard part)
  full     = (otype, name, value, parent)

Run:  python3 eval/run_eval.py            # baseline vs engineered (offline, free)
      python3 eval/run_eval.py --llm      # + the live DeepSeek model (costs a few tokens)
"""
import os, sys, re, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from oab.compiler import compile_engineered, compile_baseline

HERE = os.path.dirname(__file__)
USE_LLM = "--llm" in sys.argv


def norm(s):
    s = (s or "").lower()
    s = s.replace("(", " ").replace(")", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9, ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def keyset(objs, level, from_gold=False):
    out = set()
    for o in objs:
        g = (lambda k, d=None: o.get(k, d)) if from_gold else (lambda k, d=None: getattr(o, k, d))
        ot, nm, val, par = g("otype"), norm(g("name")), norm(g("value")), norm(g("parent"))
        if level == "identity":
            out.add((ot, nm))
        elif level == "parent":
            out.add((ot, nm, par))
        else:
            out.add((ot, nm, val, par))
    return out


def prf(pred, gold):
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def compilers():
    from oab.llm import MockLLM, DeepSeekLLM
    mock = MockLLM()
    # 'rules' = pure deterministic reference (MockLLM forces the rule path).
    comps = {
        "baseline": lambda t: compile_baseline(t).objects,
        "rules": lambda t, p=mock: compile_engineered(t, provider=p).applyable(),
    }
    if USE_LLM:
        prov = DeepSeekLLM()
        if not prov.api_key:
            print("  (--llm requested but no OAB_DEEPSEEK_KEY; skipping deepseek)")
        else:
            comps["deepseek"] = lambda t, p=prov: compile_engineered(t, provider=p).applyable()
    return comps


def run():
    comps = compilers()
    levels = ["identity", "parent", "full"]
    agg = {c: {lv: [] for lv in levels} for c in comps}

    n = len(glob.glob(os.path.join(HERE, "gold", "*.json")))
    print("=" * 74)
    print(f" COMPILE-ACCURACY EVAL — {n} hand-labeled scenarios  "
          f"(LLM: {'ON' if 'deepseek' in comps else 'off'})")
    print("=" * 74)
    print(f"  {'scenario':<20}" + "".join(f"{c+' pF1':>16}" for c in comps))

    for gpath in sorted(glob.glob(os.path.join(HERE, "gold", "*.json"))):
        gold = json.load(open(gpath))
        intake = open(os.path.join(HERE, "intakes", gold["intake"])).read()
        gsets = {lv: keyset(gold["objects"], lv, from_gold=True) for lv in levels}
        row = f"  {gold['customer']:<20}"
        for c, fn in comps.items():
            objs = fn(intake)
            for lv in levels:
                agg[c][lv].append(prf(keyset(objs, lv), gsets[lv]))
            row += f"{agg[c]['parent'][-1][2]*100:>15.1f}%"
        print(row)

    print("-" * 74)

    def avg(rows, i):
        return sum(x[i] for x in rows) / len(rows) if rows else 0.0

    for lv, title in [("identity", "object identity (otype+name)"),
                      ("parent", "parent-link / dependency (otype+name+parent)"),
                      ("full", "full config (otype+name+value+parent)")]:
        print(f"\n [{title}]")
        for c in comps:
            p, r, f = (avg(agg[c][lv], i) for i in range(3))
            print(f"   {c:<11}: P {p*100:5.1f}  R {r*100:5.1f}  F1 {f*100:5.1f}")

    print("\n" + "=" * 74)
    best = "deepseek" if "deepseek" in comps else "rules"
    hb = avg(agg[best]["parent"], 2) * 100
    bb = avg(agg["baseline"]["parent"], 2) * 100
    print(f" HEADLINE: parent-link F1   {best} {hb:.1f}%   vs   baseline {bb:.1f}%")
    print("=" * 74)


if __name__ == "__main__":
    run()
