# 论文大纲（待 WebNLG 流式结果后定稿）

## 标题（暂定）
Self-Evolving Meta-Hypergraph Schema for Knowledge Graph Construction:
Pattern-Level Topology Repair with Constraint Violation Detection

## Abstract
- 问题：现有 LLM-based KG 抽取的 schema 是 flat（DIAL-KG/EDC）或 add-only（AgentCAT），无 pattern 间拓扑约束 + 无结构错误检测。
- 方法：自进化 meta-hypergraph schema（pattern 间 dependency/constraint + IS-A taxonomy + pattern-level split + constraint violation 检测）+ 实例层 n-ary hyper-relational + 放开锁死（家族/qualifier 可增长，gate 防发散）。
- 结果：50 pattern_dependencies + 38 constraint violations（DIAL-KG 做不到）+ split top-down 拆分 + 内容驱动（种子敏感性 0.86-0.98 重合）。
- 诚实限制：无 gold P/R/F1（推专家）；deepseek 单 seed。

## 1 Introduction
- 科学 KG 抽取的 schema 痛点
- 现有工作不足（DIAL-KG flat + bottom-up only；AgentCAT add-only；LOGOS 二元）
- 我们：meta-hypergraph schema + split + constraint violation + 放开

## 2 Related Work
- schema-KG：DIAL-KG / AgentCAT / LOGOS / AutoSchemaKG / EDC
- n-ary RE：Text2NKG / HyperRED / HyperRED
- novelty 真空：schema-as-hypergraph 富拓扑 + pattern split（arXiv 零命中）

## 3 Method
- 3.1 两层结构（schema meta-hypergraph + instance n-ary hypergraph）
- 3.2 5 bounded ops（add/split/merge/retire/rename）+ conservative gate
- 3.3 pattern 间依赖 + constraint violation 检测（REDESIGN v2 核心）
- 3.4 放开锁死（家族/qualifier 可增长 + gate 防发散）

## 4 Experiments
- 4.1 跨文档 schema 演化（颗粒流 4-8 篇）：compactness/redundancy/convergence
- 4.2 constraint violation 检测率（DIAL-KG 做不到）：38 violations，C9726 0.41 排查确认真违反
- 4.3 种子敏感性（内容驱动）：3 种子，A↔C 0.86-0.90
- 4.4 对比 DIAL-KG（WebNLG 流式 schema 质量？待结果）
- 4.5 n-ary QA（88% vs 21%）

## 5 Analysis
- pattern_dependency 实例展示
- constraint violation 实例（指数未定义）
- split 拓扑继承

## 6 Limitations
- 无 gold P/R/F1
- deepseek 单 seed
- C9726 violation 0.41（数值密集论文参数多）

## 待填数字
- [ ] WebNLG 流式 compactness/redundancy（对比 DIAL-KG）
- [ ] constraint violation 跨论文分布（已有 4 篇）
- [ ] 种子敏感性 3 种子（已有）
- [ ] n-ary QA 3 篇（已有，待重跑因重做后代码变）
