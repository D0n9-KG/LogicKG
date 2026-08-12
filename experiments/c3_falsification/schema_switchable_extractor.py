"""C3 falsification: does extraction quality track schema evolution?

THE PROPOSITION UNDER TEST (C3, the ceiling contribution of GranularFlow-Bench):
  When the schema evolves (flat MuLMS-style -> L3 higher-order with
  FUNCTION_RELATION/COMPARISON_ARM/CAUSAL_ATTRIBUTION/RESEARCH_QUESTION),
  extraction quality changes in a *measurable* way.

  If TRUE  -> C3 has a foundation; the paper goes for the ceiling.
  If FALSE -> extraction quality is invariant to schema evolution; C3 dies,
              the paper retreats to the floor (C1 dataset + C2 analysis + C4 schema).

This is the MINIMAL test, not the full study. We are not yet measuring *how much*
quality changes or *why*. We are asking the binary question: is there ANY signal?

DESIGN (kill-point fixed before running):
  - Same paper, same extractor model, same temperature (0).
  - Two schema versions:
      v1 FLAT  : L1 entities + L2 relations (MuLMS-style).
      v2 L3    : v1 + L3 higher-order elements.
  - For each, extract structured atoms from the paper.
  - Then a SEPARATE verifier model (different provider) asks, per atom:
      "Is this atom supported by the source text?" (binary, no gold needed).
  - Quality proxy = fraction of atoms the verifier marks supported.
  - Compare v1-quality vs v2-quality across 5 papers.

KILL CONDITION (fixed before running, will not be moved):
  - If |v1 - v2| quality is within noise (paired, across 5 papers, the sign
    is random or the difference < a pre-set threshold) -> C3 has no signal.
  - If v1 != v2 consistently (same direction across papers, magnitude > noise)
    -> C3 has signal; proceed to the full study.

Why a verifier, not gold:
  - We have no gold yet (that's the whole dataset we're building).
  - A separate-model verifier asking "is this supported?" is a reference-free
  - quality proxy. It has known limits (the LLM-judge-misses-semantic-rebinding
    finding), but for THIS test it is sufficient: we only need *a* measurable
  - difference between v1 and v2, not a perfect one.

Caveat (honest): the verifier itself might be schema-insensitive. If so, this
test could miss a real signal. We report verifier limitations alongside.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# --- paths ---
HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = os.path.abspath(os.path.join(HERE, "..", ".."))
TMP = os.path.join(WORKTREE, ".research_tmp", "granular-benchmark")
SAMPLES = os.path.join(TMP, "experiment-samples", "sample5.json")
MINERU_BASE = "C:/Users/D0n9/Desktop/science_evo/data/upstream/remote_mineru/mineru_2355/papers"
OUT = os.path.join(TMP, "c3_results.jsonl")

# --- env ---
ENV = {}
_env_path = os.path.join(WORKTREE, ".env")
# benchmark worktree has no .env; read from era worktree's .env
if not os.path.isfile(_env_path):
    _env_path = "C:/Users/D0n9/Desktop/LogicKG/.env"
for _line in open(_env_path, encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        ENV[_k.strip()] = _v.strip().strip('"').strip("'")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# extractor + verifier use different providers (avoid self-validation)
EXTRACTOR = "deepseek"   # api.deepseek.com
VERIFIER = "qwen27"       # paratera Qwen3.5-27B
EP = {
    "deepseek": ("https://api.deepseek.com/v1", ENV.get("DEEPSEEK_API_KEY"), "deepseek-chat"),
    "qwen27": (ENV.get("PARATERA_BASE_URL", ""), ENV.get("PARATERA_API_KEY"), "Qwen3.5-27B"),
}


def _call(ep: str, prompt: str, max_tokens: int = 2000) -> str | None:
    base, key, model = EP[ep]
    if not key:
        return None
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }).encode()
    for _ in range(3):
        try:
            req = urllib.request.Request(
                base.rstrip("/") + "/chat/completions",
                data=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            raw = urllib.request.urlopen(req, context=CTX, timeout=150).read()
            return json.loads(raw)["choices"][0]["message"]["content"]
        except Exception:
            continue
    return None


def _parse_json(text: str | None) -> Any:
    if not text:
        return None
    text = re.sub(r"```json|```", "", text, flags=re.S)
    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# --- schema versions ---

SCHEMA_V1_FLAT = """Schema (FLAT, MuLMS-style):
Extract these ENTITY types and RELATIONS from the paper.

Entities: MATERIAL, SAMPLE, DEVICE, NUMERIC, UNIT, PROPERTY, MEASUREMENT, CONDITION.
Relations: measures_property, property_value, condition_environment, condition_sampleFeatures, taken_from.

Output a JSON array of atoms. Each atom = one structured finding:
{"entity_type": "...", "entity": "...", "property": "...", "value": "...", "unit": "...", "conditions": [...], "relation": "..."}"""

SCHEMA_V2_L3 = """Schema (HIGHER-ORDER, L3):
Extract L1 entities + L2 relations (same as flat), AND additionally the L3 higher-order elements:

L1 entities: MATERIAL, SAMPLE, DEVICE, NUMERIC, UNIT, PROPERTY, MEASUREMENT, CONDITION.
L2 relations: measures_property, property_value, condition_environment, condition_sampleFeatures, taken_from.
L3 higher-order:
  - FUNCTION_RELATION: a constitutive or scaling law (e.g., mu(I) = ...). Nestable: an argument can itself be a function.
  - COMPARISON_ARM: a comparison group (e.g., frictional vs frictionless; dense vs quasi-static regime).
  - CAUSAL_ATTRIBUTION: a mechanism attribution (e.g., "elastic modulus primarily determined by stress level").
  - RESEARCH_QUESTION: the paper's research question.

Output a JSON array of atoms. Use "layer" to mark L1/L2/L3:
L1/L2: {"layer":"L1","entity_type":"...","entity":"...","property":"...","value":"...","unit":"...","conditions":[...],"relation":"..."}
L3: {"layer":"L3","type":"FUNCTION_RELATION|COMPARISON_ARM|CAUSAL_ATTRIBUTION|RESEARCH_QUESTION","statement":"...","params":[...],"nested_args":[...],"applies_in":"...","validated_by":[...] }"""


EXTRACT_PROMPT = """You are extracting structured information from a scientific paper on granular flow.

{schema}

PAPER TEXT:
{text}

Extract ALL atoms you can find. Be precise. Output ONLY a JSON array, no prose."""


VERIFY_PROMPT = """Is this extracted atom supported by the paper text?

PAPER TEXT (excerpt):
{text}

ATOM:
{atom}

Answer ONLY valid JSON:
{{"supported": true or false, "reason": "one short sentence"}}"""


def _load_paper_text(paper_id: str, max_chars: int = 12000) -> str:
    p = os.path.join(MINERU_BASE, paper_id, "content_list.json")
    if not os.path.isfile(p):
        return ""
    cl = json.load(open(p, encoding="utf-8"))
    texts = [it.get("text", "") for it in cl if it.get("type") == "text" and it.get("text")]
    full = " ".join(texts)
    return full[:max_chars]


def _extract(text: str, schema: str) -> list:
    raw = _call(EXTRACTOR, EXTRACT_PROMPT.format(schema=schema, text=text), 4000)
    atoms = _parse_json(raw)
    return atoms if isinstance(atoms, list) else []


def _verify(text: str, atom: dict) -> dict:
    excerpt = text[:6000]
    raw = _call(VERIFIER, VERIFY_PROMPT.format(text=excerpt, atom=json.dumps(atom, ensure_ascii=False)[:500]), 200)
    return _parse_json(raw) or {"supported": False}


def _run_one(sample: dict) -> dict:
    paper_id = sample["paper_id"]
    text = _load_paper_text(paper_id)
    if not text:
        return {"paper_id": paper_id, "stage": "no_text"}

    v1_atoms = _extract(text, SCHEMA_V1_FLAT)
    v2_atoms = _extract(text, SCHEMA_V2_L3)

    # verify each atom (verifier is reference-free; quality proxy = supported fraction)
    def _quality(atoms):
        if not atoms:
            return {"n": 0, "supported": 0, "frac": None}
        supported = 0
        for a in atoms:
            v = _verify(text, a)
            if v.get("supported"):
                supported += 1
        return {"n": len(atoms), "supported": supported, "frac": supported / len(atoms)}

    return {
        "paper_id": paper_id,
        "title": sample.get("title", ""),
        "v1": _quality(v1_atoms),
        "v2": _quality(v2_atoms),
        "v1_n_atoms": len(v1_atoms),
        "v2_n_atoms": len(v2_atoms),
    }


def main() -> None:
    samples = json.load(open(SAMPLES, encoding="utf-8"))
    print(f"samples: {len(samples)} | extractor: {EP[EXTRACTOR][2]} | verifier: {EP[VERIFIER][2]}")
    print(f"schema v1 = FLAT (L1+L2) | v2 = HIGHER-ORDER (L1+L2+L3)")
    print(f"kill condition: |v1_frac - v2_frac| within noise across 5 papers -> C3 dies")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(_run_one, s): s for s in samples}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            v1 = r.get("v1", {})
            v2 = r.get("v2", {})
            print(f"  {r['paper_id']}: v1={v1.get('frac')} (n={v1.get('n')})  v2={v2.get('frac')} (n={v2.get('n')})")

    with open(OUT, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # analysis
    print("\n=== C3 SIGNAL CHECK ===")
    diffs = []
    for r in results:
        v1f = (r.get("v1") or {}).get("frac")
        v2f = (r.get("v2") or {}).get("frac")
        if v1f is not None and v2f is not None:
            d = v2f - v1f
            diffs.append(d)
            print(f"  {r['paper_id']}: v2-v1 = {d:+.3f}")
    if diffs:
        import statistics
        mean = statistics.mean(diffs)
        n_pos = sum(1 for d in diffs if d > 0.02)
        n_neg = sum(1 for d in diffs if d < -0.02)
        n_zero = len(diffs) - n_pos - n_neg
        print(f"\n  mean(v2-v1) = {mean:+.3f}")
        print(f"  papers with v2>v1 (signal): {n_pos}")
        print(f"  papers with v2<v1 (signal): {n_neg}")
        print(f"  papers within noise (|d|<0.02): {n_zero}")
        print()
        if n_zero == len(diffs):
            print("  VERDICT: NO SIGNAL. Extraction quality invariant to schema evolution. C3 DIES.")
        elif n_pos == len(diffs) or n_neg == len(diffs):
            print("  VERDICT: CONSISTENT SIGNAL. C3 has foundation; proceed to full study.")
        else:
            print("  VERDICT: MIXED. Some signal but inconsistent direction. Inconclusive.")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
