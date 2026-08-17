# DECISION: SciER 适配修复（pattern_type 映射）

## 改前状态
- SciER F1=0.034 (ours) vs 0.069 (native)，我们更差
- 根因：pattern_type 用物理域家族名（constitutive_law/dependency/definition...），
  SciER 的 gold relation type 是 CS 域（Used-For/Part-Of/Compare-With...），
  两者对不上 → partial match 的 relation 字段几乎全 miss → recall 极低

## 为什么改
P/R/F1 是有 gold 的标准评测，如果我们在 SciER 上 F1=0.034 远低于 native 0.069，
审稿人会直接判"方法在标准 benchmark 上比 naive 还差"。
不是方法不行（n-ary QA 0.917 vs 0.542 证明方法有效），
是**评测适配没做**——pattern_type 要映射到 gold 的 relation names 才能匹配。

## 改向什么
在 SciER 评测脚本里加 pattern_type → gold relation name 的映射：
- 我们抽的 pattern_type 是自由名（LLM 给的），需要映射到 SciER 的 9 种 gold relation
- 两种方案：
  (A) 评测时用 embedding 自动映射（我们的 pattern_type embedding vs gold relation name embedding，最近匹配）
  (B) 让 LLM 在抽取时直接用 SciER 的 9 种 relation 名（给 prompt 加 SciER relation 枚举）
  先试 B（更直接、更可控）。

## 预期风险
- 如果改 prompt 给 SciER relation 枚举，可能变成"只抽这 9 种关系"——
  但 SciER 测的就是这 9 种，所以 OK。
- 如果 F1 仍低于 native，说明方法在标准 P/R/F1 上确实不占优，
  转向 n-ary QA + constraint violation 优势（已有数据）。
