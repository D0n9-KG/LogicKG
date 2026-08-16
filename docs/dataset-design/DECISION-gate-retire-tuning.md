# DECISION: conservative gate + retire tuning (2026-08-14)

## 改前状态（checkpoint）
- git HEAD: 5c3ce572 (prompt de-lead) — 种子敏感性脚本已提交，工作区干净
- conservative gate: CONSERVATIVE_CROSS_NODE = 2（growth op 需 cross_node≥2 才接受）
- mismatch_signature: (role-tuple, qualifier-keys, reason)
- retire: 只 retire "concrete orphan 0 实例 + split_from" 和 "abstract parent 无活跃后代"
- 种子敏感性结果（4 篇 3 种子）：
  - A_FULL6: 6 家族 37 pattern
  - B_MIN2: 4 家族 49 pattern（缺 claim/measure，关系塞进 dependency）
  - C_IRREL8: 8 家族 30 pattern（不相关 causal/temporal 没被剪，反而内容激活长出真子）
  - 语义重叠：A↔B 0.73/0.98, A↔C 0.86/0.90, B↔C 0.90/0.67

## 为什么改（诊断）
1. **gate 太严**：cross_node≥2 在 4 篇里对 claim/measure 关系复发不够，B_MIN2 长不出这两个家族，关系被塞进 dependency（B→A 0.98 说明 pattern 几乎都在 A 有对应，但 A 有 B 没有 = A 用了更细家族划分）。
2. **signature 太细**：(role-tuple, qualifier-keys, reason) 里 role-tuple 是 LLM 给的，跨节点复发对不上（LLM 给不同 role 名）。
3. **retire 不够**：C_IRREL8 不相关种子 causal/temporal 没被剪。但这有内容激活成分（causal 长出真子），不全是坏。

## 改向什么
1. **gate 放宽**：cross_node≥2 改成 "cross_node≥2 OR 累积失败≥3 次"（跨论文累积触发，更适合小语料）。
2. **signature 放宽**：用 (qualifier-keys, reason) 去掉 role-tuple（role 是 LLM 噪声），让复发更易识别。
3. **retire 加强**：加"种子 pattern 在累积 N 篇后 0 活跃实例 → retire"（不相关种子清掉，但保留内容激活的）。

## 预期风险
- gate 放宽可能让 schema 又发散（A6 病）——靠 merge/retire 兜，验证看 pattern 数是否爆。
- signature 放宽可能合并不同结构缺口（误判复发）——观察 evolution 质量。
- 若调完更差，git reset 5c3ce572 回退重分析。
