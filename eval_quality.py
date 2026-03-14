"""
LogicKG 全面质量评测脚本
用法: python eval_quality.py [--base-url http://localhost:8000] [--wait]
"""
import json
import sys
import time
import argparse
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("请先安装 requests: pip install requests")

# ─────────────── RAG 问题集（DEM 领域）───────────────
RAG_QUESTIONS = [
    "What contact models are used in DEM simulations of granular materials?",
    "How does particle shape affect packing density in DEM simulations?",
    "What are the main challenges in simulating crushable sands with DEM?",
    "How does particle size segregation occur in granular flows?",
    "What is the role of friction coefficient in DEM shear tests?",
    "How do DEM simulations validate against experimental data?",
    "What are the limitations of current DEM approaches for pharmaceutical powders?",
    "How does the YADE framework implement the DEM algorithm?",
    "What is the relationship between jamming and shear in granular packings?",
    "How is inter-particle bonding modeled in DEM for crushable materials?",
]

ALL_STEPS = ["Background", "Problem", "Method", "Experiment", "Result", "Conclusion"]


def get(base: str, path: str, params: dict = None) -> Any:
    resp = requests.get(f"{base}{path}", params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def post(base: str, path: str, body: dict, timeout: int = 60) -> Any:
    resp = requests.post(f"{base}{path}", json=body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def wait_for_task(base: str, task_id: str, poll_sec: int = 15) -> dict:
    """轮询任务直到完成"""
    print(f"  等待任务 {task_id} ...")
    while True:
        tasks = get(base, "/tasks", {"limit": 5})["tasks"]
        t = next((x for x in tasks if x["task_id"] == task_id), None)
        if t is None:
            print("  任务记录消失，视为完成。")
            return {}
        status = t["status"]
        progress = t.get("progress", 0)
        stage = t.get("stage", "")
        print(f"  [{progress:.0%}] {stage} — {status}")
        if status in ("succeeded", "failed", "canceled"):
            return t
        time.sleep(poll_sec)


# ─────────────── Phase A：论文级统计 ───────────────
def analyze_paper(base: str, paper_id: str) -> dict:
    try:
        d = get(base, f"/graph/paper/{paper_id}")
    except Exception as e:
        return {"paper_id": paper_id, "error": str(e)}

    paper = d.get("paper", {})
    logic_steps = d.get("logic_steps", [])
    claims = d.get("claims", [])
    outgoing = d.get("outgoing_cites", [])
    unresolved = d.get("unresolved", [])

    # Logic Steps 分析
    step_map = {s["step_type"]: s for s in logic_steps}
    covered_steps = [
        st for st in ALL_STEPS
        if st in step_map and step_map[st].get("summary", "").strip()
    ]
    steps_with_evidence = [
        st for st in covered_steps
        if step_map[st].get("evidence_chunk_ids") or step_map[st].get("evidence")
    ]

    # Claims 分析
    total_claims = len(claims)
    supported = sum(1 for c in claims if c.get("support_label") == "supported")
    weak = sum(1 for c in claims if c.get("support_label") == "weak")
    unsupported = sum(1 for c in claims if c.get("support_label") == "unsupported")
    with_evidence = sum(
        1 for c in claims
        if c.get("evidence_chunk_ids") or c.get("evidence") or c.get("targets")
    )
    evidence_weak_claims = sum(
        1 for c in claims if c.get("evidence_weak") is True
    )

    # Purpose 分析
    purpose_counts: dict[str, int] = {}
    for cit in outgoing:
        for label in cit.get("purpose_labels", []):
            purpose_counts[label] = purpose_counts.get(label, 0) + 1

    # Phase1 质量报告
    quality = paper.get("phase1_quality_json") or {}
    if isinstance(quality, str):
        try:
            quality = json.loads(quality)
        except Exception:
            quality = {}

    return {
        "paper_id": paper_id,
        "title": paper.get("title", "")[:80],
        "paper_source": paper.get("paper_source", ""),
        "gate_passed": paper.get("phase1_gate_passed"),
        "quality_tier": quality.get("quality_tier", quality.get("quality_tier_score")),
        "quality_tier_score": quality.get("quality_tier_score"),
        "supported_claim_ratio": quality.get("supported_claim_ratio"),
        "step_coverage_ratio": quality.get("step_coverage_ratio"),
        "critical_slot_coverage": quality.get("critical_slot_coverage"),
        "conflict_rate": quality.get("conflict_rate"),
        "gate_fail_reasons": quality.get("gate_fail_reasons", []),
        # Steps
        "steps_covered": len(covered_steps),
        "steps_with_evidence": len(steps_with_evidence),
        "covered_step_list": covered_steps,
        "missing_steps": [st for st in ALL_STEPS if st not in covered_steps],
        # Claims
        "total_claims": total_claims,
        "supported_claims": supported,
        "weak_claims": weak,
        "unsupported_claims": unsupported,
        "claims_with_evidence": with_evidence,
        "evidence_weak_claims": evidence_weak_claims,
        # Citations
        "cites_resolved": len(outgoing),
        "cites_unresolved": len(unresolved),
        "citation_resolve_rate": (
            len(outgoing) / max(1, len(outgoing) + len(unresolved))
        ),
        "purpose_distribution": purpose_counts,
    }


# ─────────────── Phase B：演化关系统计 ───────────────
def analyze_evolution(base: str) -> dict:
    try:
        data = get(base, "/evolution/propositions", {"limit": 2000})
    except Exception as e:
        return {"error": str(e)}

    props = data.get("propositions", [])
    if not props:
        return {"total_propositions": 0, "note": "暂无命题数据"}

    state_dist: dict[str, int] = {}
    has_relations = 0
    self_loops = 0
    relation_counts = {"SUPPORTS": 0, "CHALLENGES": 0, "SUPERSEDES": 0}

    for p in props:
        state = p.get("current_state", "unknown")
        state_dist[state] = state_dist.get(state, 0) + 1

        sup = int(p.get("supports") or 0)
        cha = int(p.get("challenges") or 0)
        sup_s = int(p.get("supersedes") or 0)
        relation_counts["SUPPORTS"] += sup
        relation_counts["CHALLENGES"] += cha
        relation_counts["SUPERSEDES"] += sup_s
        if sup + cha + sup_s > 0:
            has_relations += 1

    total = len(props)
    coverage_rate = has_relations / max(1, total)
    self_loop_rate = 0.0  # API 返回聚合计数，无法做精确自环检测

    return {
        "total_propositions": total,
        "state_distribution": state_dist,
        "has_relations_count": has_relations,
        "coverage_rate": coverage_rate,
        "total_relations": sum(relation_counts.values()),
        "relation_breakdown": relation_counts,
        "self_loop_count": self_loops,
        "self_loop_rate": self_loop_rate,
    }


# ─────────────── Phase C：RAG 问答 ───────────────
def run_rag_tests(base: str, http_timeout: int = 90) -> list[dict]:
    results = []
    for i, q in enumerate(RAG_QUESTIONS, 1):
        print(f"  [{i}/{len(RAG_QUESTIONS)}] {q[:70]}...")
        try:
            resp = post(base, "/rag/ask", {"question": q, "k": 8}, timeout=http_timeout)
            answer = resp.get("answer", "")
            evidence = resp.get("evidence", resp.get("contexts", []))
            paper_ids = list({e.get("paper_id", "") for e in evidence if e.get("paper_id")})
            results.append({
                "question": q,
                "answer_preview": answer[:300],
                "answer_length": len(answer),
                "evidence_count": len(evidence),
                "evidence_paper_count": len(paper_ids),
                "evidence_paper_ids": paper_ids,
                "has_answer": bool(answer.strip()),
            })
        except Exception as e:
            results.append({"question": q, "error": str(e)})
    return results


# ─────────────── 打印报告 ───────────────
def fmt(v, fmt_str=".2f") -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:{fmt_str}}"
    return str(v)


def print_report(papers: list[dict], evolution: dict, rag: list[dict]) -> dict:
    print("\n" + "═" * 70)
    print("  LogicKG DEM 20 篇质量评测报告")
    print("═" * 70)

    # ── 摄入总览 ──
    total = len(papers)
    errors = [p for p in papers if "error" in p]
    ok = [p for p in papers if "error" not in p]
    gate_passed = [p for p in ok if p.get("gate_passed") is True]
    gate_failed = [p for p in ok if p.get("gate_passed") is False]

    print(f"\n【A. 摄入 & Phase1 Gate】")
    print(f"  论文总数       : {total}")
    print(f"  摄入错误       : {len(errors)}")
    print(f"  Gate 通过      : {len(gate_passed)} / {len(ok)}"
          f"  ({len(gate_passed)/max(1,len(ok)):.0%})")
    tier_dist: dict[str, int] = {}
    for p in ok:
        t = str(p.get("quality_tier") or "unknown")
        tier_dist[t] = tier_dist.get(t, 0) + 1
    for tier, cnt in sorted(tier_dist.items()):
        print(f"    质量等级 {tier:10s}: {cnt} 篇")

    fail_reason_all: dict[str, int] = {}
    for p in gate_failed:
        for r in p.get("gate_fail_reasons", []):
            fail_reason_all[r] = fail_reason_all.get(r, 0) + 1
    if fail_reason_all:
        print("  Gate 失败原因分布:")
        for r, cnt in sorted(fail_reason_all.items(), key=lambda x: -x[1]):
            print(f"    {r}: {cnt} 次")

    # ── Logic Steps ──
    print(f"\n【B. Logic Steps 完整性】")
    avg_steps = sum(p.get("steps_covered", 0) for p in ok) / max(1, len(ok))
    avg_cov = sum(p.get("step_coverage_ratio") or 0 for p in ok) / max(1, len(ok))
    all_6 = sum(1 for p in ok if p.get("steps_covered", 0) == 6)
    print(f"  平均覆盖步骤数 : {avg_steps:.1f} / 6")
    print(f"  平均 step_coverage_ratio: {avg_cov:.2%}")
    print(f"  全6步覆盖论文  : {all_6} / {len(ok)}")
    # 各步骤缺失统计
    missing_counts: dict[str, int] = {}
    for p in ok:
        for s in p.get("missing_steps", []):
            missing_counts[s] = missing_counts.get(s, 0) + 1
    print("  各步骤缺失次数:")
    for s in ALL_STEPS:
        cnt = missing_counts.get(s, 0)
        bar = "#" * cnt + "-" * (len(ok) - cnt)
        print(f"    {s:12s}: {cnt:2d} 篇缺失  {bar}")

    # ── Claims ──
    print(f"\n【C. Claims 质量】")
    avg_supported_ratio = sum(
        p.get("supported_claim_ratio") or 0 for p in ok
    ) / max(1, len(ok))
    avg_claims = sum(p.get("total_claims", 0) for p in ok) / max(1, len(ok))
    avg_weak_rate = sum(
        p.get("evidence_weak_claims", 0) / max(1, p.get("total_claims", 1))
        for p in ok
    ) / max(1, len(ok))
    avg_critical = sum(
        p.get("critical_slot_coverage") or 0 for p in ok
    ) / max(1, len(ok))
    avg_conflict = sum(
        p.get("conflict_rate") or 0 for p in ok
    ) / max(1, len(ok))
    print(f"  平均 Claims 数          : {avg_claims:.1f}")
    print(f"  平均 supported_ratio    : {avg_supported_ratio:.2%}")
    print(f"  平均 critical_slot_cov  : {avg_critical:.2%}")
    print(f"  平均 evidence_weak 比例 : {avg_weak_rate:.2%}")
    print(f"  平均 conflict_rate      : {avg_conflict:.4f}")

    # ── Citations ──
    print(f"\n【D. 引用解析质量】")
    total_resolved = sum(p.get("cites_resolved", 0) for p in ok)
    total_unresolved = sum(p.get("cites_unresolved", 0) for p in ok)
    total_cites = total_resolved + total_unresolved
    resolve_rate = total_resolved / max(1, total_cites)
    print(f"  总引用解析数   : {total_resolved} resolved / {total_unresolved} unresolved")
    print(f"  整体解析率     : {resolve_rate:.2%}")
    # Purpose 分布聚合
    all_purposes: dict[str, int] = {}
    for p in ok:
        for label, cnt in p.get("purpose_distribution", {}).items():
            all_purposes[label] = all_purposes.get(label, 0) + cnt
    if all_purposes:
        print("  引用目的标签分布:")
        for label, cnt in sorted(all_purposes.items(), key=lambda x: -x[1])[:8]:
            print(f"    {label:25s}: {cnt}")
        # 检查"Background 塌缩"
        bg = all_purposes.get("Background", 0)
        bg_ratio = bg / max(1, sum(all_purposes.values()))
        if bg_ratio > 0.6:
            print(f"  ⚠️  Background 占比过高: {bg_ratio:.0%}（可能存在 purpose 塌缩）")

    # ── Evolution ──
    print(f"\n【E. 演化关系质量】")
    if "error" in evolution:
        print(f"  错误: {evolution['error']}")
    else:
        print(f"  总命题数       : {evolution.get('total_propositions', 0)}")
        print(f"  关系覆盖率     : {evolution.get('coverage_rate', 0):.2%}")
        print(f"  总关系数       : {evolution.get('total_relations', 0)}")
        rels = evolution.get("relation_breakdown", {})
        for rt, cnt in rels.items():
            print(f"    {rt:15s}: {cnt}")
        print(f"  自环率         : {evolution.get('self_loop_rate', 0):.4f}")
        state_dist = evolution.get("state_distribution", {})
        if state_dist:
            print(f"  命题状态分布   : {state_dist}")
        cov = evolution.get("coverage_rate", 0)
        slr = evolution.get("self_loop_rate", 0)
        if cov < 0.2:
            print("  ⚠️  覆盖率偏低（<20%），演化图稀疏")
        if slr > 0.05:
            print(f"  ⚠️  自环率偏高（{slr:.2%}），可能存在同一命题自比较")

    # ── RAG ──
    print(f"\n【F. RAG 问答质量】")
    rag_ok = [r for r in rag if "error" not in r]
    has_answer = sum(1 for r in rag_ok if r.get("has_answer"))
    avg_evidence = sum(r.get("evidence_count", 0) for r in rag_ok) / max(1, len(rag_ok))
    print(f"  测试题数       : {len(rag)}")
    print(f"  有效回答数     : {has_answer} / {len(rag_ok)}")
    print(f"  平均检索证据数 : {avg_evidence:.1f}")
    for r in rag:
        if "error" in r:
            print(f"  ✗ {r['question'][:60]}... → 错误: {r['error']}")
        else:
            ev = r.get("evidence_count", 0)
            pcount = r.get("evidence_paper_count", 0)
            has = "✓" if r.get("has_answer") else "✗"
            print(f"  {has} [{ev}篇证据/{pcount}篇论文] {r['question'][:55]}...")
            if r.get("answer_preview"):
                print(f"      → {r['answer_preview'][:150]}")

    # ── 论文明细表 ──
    print(f"\n【论文级明细】")
    header = f"{'source':15s} {'gate':5s} {'tier':7s} {'steps':5s} {'supp%':6s} {'crit%':6s} {'res%':5s} {'claims':6s}"
    print("  " + header)
    print("  " + "─" * len(header))
    for p in sorted(ok, key=lambda x: x.get("paper_source", "")):
        src = (p.get("paper_source") or "")[:14]
        gate = "✓" if p.get("gate_passed") else "✗"
        tier = str(p.get("quality_tier") or "?")[:7]
        steps = f"{p.get('steps_covered',0)}/6"
        supp = p.get("supported_claim_ratio")
        crit = p.get("critical_slot_coverage")
        res = p.get("citation_resolve_rate")
        claims = p.get("total_claims", 0)
        print(f"  {src:15s} {gate:5s} {tier:7s} {steps:5s} "
              f"{fmt(supp,'5.0%'):6s} {fmt(crit,'5.0%'):6s} "
              f"{fmt(res,'4.0%'):5s} {claims:6d}")

    print("\n" + "═" * 70)

    # 构建汇总数据
    return {
        "summary": {
            "total_papers": total,
            "ingest_errors": len(errors),
            "gate_pass_rate": len(gate_passed) / max(1, len(ok)),
            "quality_tier_dist": tier_dist,
            "gate_fail_reason_dist": fail_reason_all,
            "avg_step_coverage": avg_cov,
            "full_6step_rate": all_6 / max(1, len(ok)),
            "avg_supported_claim_ratio": avg_supported_ratio,
            "avg_critical_slot_coverage": avg_critical,
            "avg_conflict_rate": avg_conflict,
            "citation_resolve_rate": resolve_rate,
            "purpose_distribution": all_purposes,
        },
        "evolution": evolution,
        "rag_results": rag,
        "papers": ok,
        "errors": errors,
    }


# ─────────────── 主入口 ───────────────
def main():
    parser = argparse.ArgumentParser(description="LogicKG 质量评测")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--wait", action="store_true", help="等待摄入任务完成后再评测")
    parser.add_argument("--wait-task-id", default=None)
    parser.add_argument("--skip-rag", action="store_true")
    parser.add_argument("--rag-http-timeout", type=int, default=90, help="RAG接口HTTP超时（秒）")
    parser.add_argument("--out", default="eval_report.json")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    print(f"后端地址: {base}")

    # 可选：等待任务完成
    if args.wait and args.wait_task_id:
        result = wait_for_task(base, args.wait_task_id)
        if result.get("status") == "failed":
            print(f"⚠️  任务失败: {result.get('error')}")

    # A: 获取所有论文
    print("\n[Phase A] 获取论文列表...")
    all_papers_resp = get(base, "/graph/papers", {"limit": 200})
    papers_list = all_papers_resp.get("papers", [])
    print(f"  共 {len(papers_list)} 篇论文")

    paper_results = []
    for i, p in enumerate(papers_list, 1):
        pid = p["paper_id"]
        src = p.get("paper_source") or pid[:16]
        print(f"  [{i}/{len(papers_list)}] 分析 {src}...")
        result = analyze_paper(base, pid)
        paper_results.append(result)

    # B: 演化分析
    print("\n[Phase B] 演化关系分析...")
    evolution_result = analyze_evolution(base)

    # C: RAG 测试
    rag_results = []
    if not args.skip_rag:
        print("\n[Phase C] RAG 问答测试...")
        rag_results = run_rag_tests(base, http_timeout=max(30, args.rag_http_timeout))
    else:
        print("\n[Phase C] RAG 测试跳过（--skip-rag）")

    # D: 报告
    report = print_report(paper_results, evolution_result, rag_results)

    # 保存
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n完整报告已保存至: {args.out}")


if __name__ == "__main__":
    main()
