"""Analyze quality of ingested papers."""
import json
from pathlib import Path
from collections import Counter

runs_dir = Path("C:/Users/D0n9/Desktop/LogicKG/backend/runs/20260219T114654Z")
papers = ["01_1478","02_1050","03_491","04_1228","05_340","07_1605","09_1007","11_251","12_1606","15_1396"]

print("=== CLAIMS 质量分析 ===")
total_claims = 0
semantic_verified = 0
lexical_only = 0
span_missing = 0

for paper in papers:
    f = runs_dir / f"{paper}.llm_imrad.json"
    if not f.exists():
        continue
    data = json.loads(f.read_text(encoding="utf-8"))
    claims = data.get("claims", [])

    paper_total = len(claims)
    paper_semantic = sum(1 for c in claims if c.get("judge_reason","").startswith("semantic"))
    paper_lexical = sum(1 for c in claims if c.get("judge_reason","") == "high lexical overlap")
    paper_span_missing = sum(1 for c in claims if c.get("span_start", -1) == -1)

    total_claims += paper_total
    semantic_verified += paper_semantic
    lexical_only += paper_lexical
    span_missing += paper_span_missing

    step_types = {}
    for c in claims:
        st = c.get("step_type", "Unknown")
        step_types[st] = step_types.get(st, 0) + 1
    print(f"{paper}: {paper_total} claims, semantic={paper_semantic}, lexical={paper_lexical}, span_missing={paper_span_missing}, steps={dict(step_types)}")

if total_claims > 0:
    print(f"\nTotal: {total_claims} claims, semantic={semantic_verified}({100*semantic_verified/total_claims:.1f}%), lexical={lexical_only}({100*lexical_only/total_claims:.1f}%), span_missing={span_missing}({100*span_missing/total_claims:.1f}%)")

print("\n=== Citation Purpose 分布 ===")
all_labels = Counter()
multi_label_count = 0
unknown_count = 0
total_citations = 0

for paper in papers:
    f = runs_dir / f"{paper}.llm_citation_purposes.json"
    if not f.exists():
        continue
    data = json.loads(f.read_text(encoding="utf-8"))
    total_citations += len(data)
    for item in data:
        labels = item.get("labels", [])
        for lbl in labels:
            all_labels[lbl] += 1
        if len(labels) > 1:
            multi_label_count += 1
        if "Unknown" in labels:
            unknown_count += 1

print(f"标签总分布: {dict(all_labels.most_common())}")
print(f"总引用条数: {total_citations}")
if total_citations > 0:
    print(f"多标签引用: {multi_label_count} ({100*multi_label_count/total_citations:.1f}%)")
    print(f"Unknown标签: {unknown_count} ({100*unknown_count/total_citations:.1f}%)")

print("\n=== 示例Claims（judge_score分布）===")
score_buckets = {"<0.5": 0, "0.5-0.7": 0, "0.7-0.8": 0, "0.8-0.9": 0, ">=0.9": 0}
for paper in papers[:3]:  # Only first 3 for brevity
    f = runs_dir / f"{paper}.llm_imrad.json"
    if not f.exists():
        continue
    data = json.loads(f.read_text(encoding="utf-8"))
    for c in data.get("claims", []):
        score = c.get("judge_score", 0)
        if score < 0.5:
            score_buckets["<0.5"] += 1
        elif score < 0.7:
            score_buckets["0.5-0.7"] += 1
        elif score < 0.8:
            score_buckets["0.7-0.8"] += 1
        elif score < 0.9:
            score_buckets["0.8-0.9"] += 1
        else:
            score_buckets[">=0.9"] += 1
print(f"Judge score分布 (前3篇): {score_buckets}")

print("\n=== 几个具体claims（quality检查）===")
f = runs_dir / "01_1478.llm_imrad.json"
data = json.loads(f.read_text(encoding="utf-8"))
for c in data.get("claims", [])[:5]:
    print(f"  [{c.get('step_type')}][{c.get('judge_reason','')}({c.get('judge_score',0):.2f})] {c.get('text','')[:120]}")
    print(f"    span_start={c.get('span_start',-999)}, span_end={c.get('span_end',-999)}")
