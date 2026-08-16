# Schema 重做设计 v2 — 强化超图拓扑 + 放开锁死

## 为什么重做（诊断）

现状的两个真问题（用户戳中）：

1. **schema 层超图性名不副实**：meta-hyperedge 连的槽少（2-3）、meta-edge 多是二元 IS-A，schema 层≈"本体树 + 受控槽"，和 DIAL-KG 的 schema 图拓扑上没拉开差距。novelty 调研坐实的真空"schema-as-hypergraph 富拓扑"没真体现。
2. **三重锁死丢信息**：家族固定 6 个、qualifier key 固定 + 枚举值、角色槽定死 8 个。论文里没预想到的限制种类（因果/时序/不确定性/置信度/假设范围等）被强行塞进现有槽或丢失。防发散做过头变成防灵活。

唯一现状真 novelty = pattern-level split（DIAL-KG/AgentCAT/LOGOS 不做）。单点 novelty 撑不起"schema 层超图"claim。

## 重做目标

把 schema 从"本体树 + 受控槽"升级成"pattern 间有富拓扑约束的关系超图"，同时放开三重锁死（靠 conservative gate + merge/retire 防发散，不靠锁死）。让和 DIAL-KG 的差距从"只多一个 split"扩成"拓扑结构 + split + 灵活演化"三维。

## 改动一：schema 层富拓扑（pattern 间约束）

### 现状
- MetaEdge.relation 有 "pattern_dependency" / "type_relation" 值，但**没实现、没用到**。
- pattern 之间只有 subclass_of（IS-A 树），无其他关系。
- 每个 pattern 是孤立模板。

### 重做：pattern 间三类约束 meta-edge
在 schema 层引入 pattern 间的非树拓扑（DIAL-KG 没有）：

1. **pattern_dependency（依赖）**：pattern A 依赖 pattern B（A 的实例需要 B 先存在）。如 `constitutive_law` depends_on `definition`（本构律的参数要先定义）。
2. **pattern_constraint（约束）**：pattern A 约束 pattern B（A 的存在限制 B 的取值/形式）。如 `constitutive_law` constrains `measure`（本构律要被测量验证，measure 的对象受 law 约束）。
3. **pattern_composition（组合）**：pattern A 是 pattern B + C 的组合。如某本构律 = 基础依赖 + 流态修正 + 参数定义。

这些 meta-edge 让 schema 层成为**有向带约束超图**，不是孤立 pattern 集合。

### 价值（关键，不让富拓扑变花架子）
**schema 约束违反检测**——这是 DIAL-KG 做不到的能力：schema 能发现"本构律引用了未定义的参数""测量对象不在律约束范围内"这类**结构错误**。这是 schema 层富拓扑的真用武之地，可量化（约束违反率）。

## 改动二：放开三重锁死（防发散靠 gate 不靠锁死）

### 现状锁死
- 家族固定 6（TOP_LEVEL_FAMILIES，add_pattern gate 拒非 6 家族）
- qualifier key 固定（QUALIFIER_REGISTRY，validate 拒非注册 key）
- qualifier enum 固定（method=experiment/simulation/theory/review 等）
- 角色槽定死 8 个功能角色

### 重做：可增长 + gate 约束
1. **家族可增长**：agent 能提议新家族（如 causal/temporal/uncertainty），带 evidence + cross_node≥2 conservative gate（防单次乱加）。第一个该家族的 pattern 成根（现有 family_roots 自动机制）。
2. **qualifier 可扩展**：agent 能提议新 qualifier key（如 confidence_level/assumption_scope），过 gate + 注册进 QUALIFIER_REGISTRY（动态注册，不预固定）。enum 仍受控但可扩充（新枚举值过 gate）。
3. **角色槽可动态**：复杂关系能加新角色（intermediate_state/boundary_condition），但受 schema 一致性约束（同 pattern 复用同角色集，跨 pattern 可不同）。

### 防发散不靠锁死，靠什么
- **conservative gate（cross_node≥2）**：新家族/新 qualifier/新槽要复发才加（已验证有效）。
- **merge/retire**：重复的家族/qualifier/pattern 合并清理（已验证）。
- **LLM 只命名不判断**：A4 循环破除。

## 改动三：split 升级（唯一现状 novelty 强化）

### 现状
split 拆过宽 pattern，父标抽象 + 子 IS-A。但拆的维度单一（按 instance 聚类）。

### 重做：多维度 split
- 按 qualifier 值拆（已有：discrete 枚举聚类）
- 按流态拆（已有：applies_in_regime）
- **新增：按 pattern 间依赖拆**——一个过宽 pattern 在不同依赖上下文表现不同（如某依赖在静态 vs 动态流态下语义不同），按依赖上下文拆。
- split 后子 pattern 继承父的 pattern_dependency/constraint 边（拓扑不丢）。

## 改动四：实例层不变（已是真超图）

实例层 Hyperedge 连 N 节点 + 角色 + qualifier + 证据，已验证 n-ary 真起来（arity 3-7）。**不动**。

## 实现顺序（边做边探，每步验证）

1. **放开家族锁死**（最快见效）：TOP_LEVEL_FAMILIES 改可增长 + gate。验证：WebNLG 通用域能抽出边（之前全拒）。
2. **放开 qualifier 注册**：动态注册新 key + enum 扩充 + gate。验证：能加新限制种类不丢。
3. **pattern_dependency 实现**：add_pattern_dependency op + 约束违反检测。验证：能发现"引用未定义参数"结构错误。
4. **pattern_constraint / composition**：约束 + 组合 meta-edge。验证：富拓扑有实测价值。
5. **split 多维度 + 拓扑继承**：按依赖上下文拆 + 子继承 meta-edge。验证：split 在新拓扑下工作。
6. **schema 约束违反检测作为主评测**：量化约束违反率（DIAL-KG 做不到的指标）。

## 风险与探索点（诚实）

- **pattern 间依赖怎么定**：agent 提议 + gate，还是从实例归纳？两边都试，选更稳的。
- **富拓扑会不会让 schema 又发散**：靠 gate + merge 兜，但全放开未测，可能要调。
- **约束违反检测的判定**：结构错误怎么定义才不是 LLM 自判？要确定性判据（如"本构律的参数节点是否在 definition pattern 里有对应"——图可达性，确定性）。
- **novelty 仍可能被占**：pattern 间约束是否有人做？重做中持续核（之前调研 meta-hypergraph 零命中，但 pattern_dependency / ontology constraint 要单独核）。

## 不改的（保持 novelty + 已验证）

- 实例层 n-ary 超图（已验证）
- conservative gate + merge/retire（已验证防发散）
- LLM 只命名不判断（A4 破除）
- 持久化 + 跨论文语料库
- split 作为核心操作（强化不替换）

## 和 DIAL-KG 的差距（重做后预期）

| 维度 | DIAL-KG | 我们（重做后） |
|------|---------|--------------|
| schema 结构 | 扁平谓词集 + IS-A | pattern 间依赖/约束/组合超图 |
| 演化方向 | bottom-up merge | bottom-up + top-down split |
| 限定符 | 固定属性 | 动态可增长 + gate |
| 家族 | schema-free（无家族） | 可增长家族 + gate（有结构） |
| 结构错误检测 | 无 | schema 约束违反检测 |
| 模型 | Qwen-Max | DeepSeek-V3 |

三维差距：拓扑 + split + 灵活演化。
