# LogicKG 作为四层科研知识系统第二层底座的重构设计

## 1. 背景

当前 LogicKG 已经具备较强的单篇论文结构化抽取能力。项目能够稳定抽取 `LogicStep`、`Claim`、证据片段、引用语义、教材实体与跨源链接，并通过质量门禁降低结构污染。这说明项目已经足以承担四层科研知识系统中的第二层底座角色。

但现阶段系统的主要问题不是“抽取得不够多”，而是“第二层资产尚未被定义为第三层和第四层可稳定消费的中间对象”。现有 Neo4j 主线更像工作台内部表示，而不是面向训练数据编译的 canonical export。

本设计的目标不是把 LogicKG 扩成一个更复杂的论文图谱产品，而是把它重构成：

1. 稳定输出 `PaperLogicTrace` 的第二层资产引擎。
2. 提供跨论文 `LogicStep` 模式发现能力，作为第三层 `TopicScopeBuilder` 的输入。
3. 为第一层、第三层、第四层预留清晰的 schema 契约和编译接口。

## 2. 设计目标

### 2.1 核心目标

1. 将当前第二层抽取结果规范化为可版本化、可导出、可训练的 `PaperLogicTrace`。
2. 在不污染原始图谱语义的前提下，新增一套面向跨论文模式发现的重叠社区系统。
3. 使 LogicKG 可以自然衔接后续 `RouteState`、`WhyNowCase`、`RouteComparisonCase`、`DecisionPriorCard` 等对象。

### 2.2 非目标

1. 不在本阶段直接实现完整第三层 `RouteState` 合成。
2. 不在本阶段实现开放式第四层宏观假说生成。
3. 不把新的社区结果误当作第三层对象本身。
4. 不继续以“增加更多 claim 数量”为主目标推动系统演进。

## 3. 当前系统定位判断

### 3.1 现有优势

当前代码主线已经具备成为第二层底座的关键条件：

1. `LogicStep + Claim` 双层结构，而不是单纯三元组抽取。
2. quote-based grounding 与证据片段绑定。
3. 引用事件、citation purpose、语义增强。
4. phase1/phase2 质量门和结构化质量报告。

其中，以下模块已经构成第二层底座的基础能力：

1. [orchestrator.py](C:/Users/D0n9/Desktop/LogicKG/backend/app/extraction/orchestrator.py)
2. [logic_claims_v2.py](C:/Users/D0n9/Desktop/LogicKG/backend/app/llm/logic_claims_v2.py)
3. [models.py](C:/Users/D0n9/Desktop/LogicKG/backend/app/citations/models.py)
4. [neo4j_client.py](C:/Users/D0n9/Desktop/LogicKG/backend/app/graph/neo4j_client.py)

### 3.2 当前短板

当前第二层对图谱功能已经足够强，但对训练数据编译还存在明显缺口：

1. 缺少稳定的 `PaperLogicTrace` 导出格式。
2. 缺少面向 L3/L4 的 L2.5 标准槽位。
3. 缺少“topic x year”友好的时间切片中间资产。
4. 缺少真正跨论文、支持重叠归属的 `LogicStep` 模式层。
5. 社区结果仍然更接近前端展示对象，而不是第三层前置输入。

## 4. 第二层目标状态

LogicKG 的目标状态应被定义为：

1. `PaperLogicTrace Export Engine`
2. `L2.5 Normalization Layer`
3. `Cross-paper LogicStep Pattern Layer`

这三层一起构成四层系统中的“强化第二层”。

### 4.1 PaperLogicTrace

每篇论文导出的 `PaperLogicTrace` 至少包含：

1. `paper_metadata`
2. `logic_steps`
3. `claims`
4. `claim_evidence_links`
5. `figures`
6. `limitations`
7. `future_work_signals`
8. `citation_acts`
9. `quality_tier`

### 4.2 L2.5 必补槽位

第二层抽取在导出前应补齐以下标准字段：

| 字段 | 说明 |
|------|------|
| `research_object` | 研究对象、材料、任务或系统 |
| `operation_or_method` | 方法、实验操作、模型族或技术动作 |
| `observed_variable` | 被观测现象、变量或结果对象 |
| `metric` | 指标或评价方式 |
| `comparison_target` | baseline、对照方法或历史方案 |
| `effect_direction` | 提升、下降、无变化、冲突 |
| `effect_size` | 数值、区间或离散等级 |
| `condition_context` | 数据、算力、实验、环境、约束条件 |
| `limitation_type` | 数据、测量、算力、理论、评测、工程等瓶颈类型 |
| `resource_mentions` | dataset、benchmark、instrument、software、hardware 等资源提及 |

### 4.3 导出原则

1. Neo4j 内部对象不是训练集 canonical schema。
2. `PaperLogicTrace` 必须可版本化、可离线存储、可单独回放。
3. L2.5 的演进应尽量不要求重跑最昂贵的原始论文抽取。

## 5. 社区系统的新角色

新的社区系统不再只是“全局社区展示模块”，而应承担三层角色：

1. 发现跨论文 `LogicStep` 共性模式。
2. 为第三层 `TopicScopeBuilder` 提供 topic 候选和证据聚合入口。
3. 为后续 `dominant_methods`、`alternative_routes`、`known_bottlenecks` 提供上游组织能力。

重要的是：社区不是 `RouteState`，而是 `RouteState` 之前的中间组织层。

## 6. 社区系统重构总览

建议废弃“继续修补 TreeComm 作为最终方案”的思路，新增一套独立社区链路：

1. `candidate_graph.py`
2. `overlap_detection.py`
3. `labeling.py`
4. `materializer.py`
5. `service_v2.py`

原有 [tree_comm_adapter.py](C:/Users/D0n9/Desktop/LogicKG/backend/app/community/tree_comm_adapter.py) 和 [projection.py](C:/Users/D0n9/Desktop/LogicKG/backend/app/community/projection.py) 继续保留为 baseline 或回归对照，但不再作为长期主方案。

## 7. Candidate Graph Builder 设计

### 7.1 节点范围

候选图只保留 `LogicStep` 作为聚类主节点。

原因：

1. `Claim` 粒度过细，容易重新把社区拉回单篇论文内部。
2. `LogicStep` 更接近“可复用的方法原型、问题原型、解释原型”。
3. 后续第三层更需要 step 级模式，而不是 claim 级碎片。

### 7.2 不使用的关系

第一版明确忽略：

1. `NEXT`
2. 论文内部的层级组织关系主导聚类
3. `Claim` 直接参与社区主结构

### 7.3 候选边来源

候选图中的 step-step 稀疏边来自以下信号：

1. `SIMILAR_LOGIC`
2. 共享 `EXPLAINS` 实体
3. 引文传播增强信号
4. 局部高信息量短语模式

边权采用组合形式：

`w = a * semantic + b * concept + c * citation + d * phrase`

第一版建议：

1. `semantic` 与 `concept` 为主信号。
2. `citation` 为增强项。
3. `phrase` 为补充项。

### 7.4 稀疏化原则

为避免大规模运行时的平方复杂度，候选图不构建全量相似矩阵，只保留每个 `LogicStep` 的 top-k 邻居。

建议参数：

1. `k_semantic = 20`
2. `k_concept = 10`
3. 合并后的 `max_neighbors_per_step <= 48`

这使边规模接近 `O(N * k)`，而不是 `O(N^2)`。

### 7.5 存储策略

第一版不把候选图永久写回原始图谱。

建议在社区任务运行时：

1. 从 Neo4j 查询基础对象与关系。
2. 在内存或社区索引文件中构造稀疏候选图。
3. 仅把最终社区读模型写回可查询层。

## 8. Overlap Community Detector 设计

### 8.1 选型结论

新的社区算法不再以 TreeComm 为最终方案，而采用“稀疏邻接图 + 重叠社区发现”的路线。

主方案建议：

1. `BigCLAM` 风格重叠社区检测。
2. `SLPA` 作为对照或 fallback。

### 8.2 不采用 TreeComm 作为主方案的原因

当前 TreeComm 的主要问题在于：

1. 最终是硬划分。
2. 不支持自然的多社区归属。
3. 全量运行时存在明显的内存和相似矩阵压力。
4. 更适合中小规模块状社区，而不是大规模跨论文重叠模式发现。

### 8.3 BigCLAM 风格输出

每个 `LogicStep` 对多个社区具有 membership strength。

最终输出时保留：

1. 高于阈值的社区归属。
2. 每个节点最多前 `m` 个社区。
3. `core members` 与 `peripheral members` 区分。

建议约束：

1. `min_community_size >= 5`
2. `max_memberships_per_step <= 3`
3. 对低一致性社区做 coherence gate

## 9. Community Labeler 设计

社区命名不再依赖成员文本直接拼接，而采用独立命名层。

### 9.1 标题目标

标题应表达“这是一类什么样的共性模式”，而不是“社区里有哪些字词”。

### 9.2 命名步骤

1. 从 `core members` 提取高区分度短语。
2. 聚合共享实体、动作模式、技术手段与目标对象。
3. 用有限模板生成标题。

示例模板：

1. `基于{技术手段}的{对象}建模方法`
2. `面向{目标}的{对象}推断范式`
3. `通过{技术手段}实现{对象}优化的研究路线`

### 9.3 摘要结构

社区摘要建议包含：

1. 一句话定义
2. 成员共性说明
3. 代表性论文与代表性 `LogicStep`

### 9.4 Claim 的角色

`Claim` 不参加主聚类，但可参与：

1. 社区标题补充
2. 社区摘要解释
3. 代表性证据展示

## 10. 结果物化与读模型

### 10.1 社区结果不是原始图谱污染物

新的社区结果应被视为派生层。

建议存储为：

1. `Community` 节点
2. `(:LogicStep)-[:IN_COMMUNITY {score, rank, is_core}]->(:Community)`
3. 关键词与摘要节点或嵌入属性

### 10.2 社区对象建议字段

| 字段 | 说明 |
|------|------|
| `community_id` | 稳定主键 |
| `title` | 社区标题 |
| `summary` | 社区摘要 |
| `keywords` | 社区关键词 |
| `member_count` | 成员数 |
| `core_member_count` | 核心成员数 |
| `paper_count` | 覆盖论文数 |
| `version` | 算法版本 |
| `built_at` | 构建时间 |

其中 `paper_count` 很关键，可用于过滤“仍然只有单篇论文覆盖”的社区。

## 11. 与第三层和第四层的接口

### 11.1 面向第三层

社区结果直接支持第三层的以下工作：

1. `TopicScopeBuilder` 发现跨论文 topic 候选。
2. 聚合同类 `LogicStep`，形成 `dominant_methods` 候选。
3. 识别互相竞争或平行的替代路线雏形。
4. 为 `RouteState` 的 supporting / challenging evidence 提供组织入口。

### 11.2 面向第四层

社区不是第四层对象，但可作为第四层的候选来源：

1. 从多个 `RouteState` 中回看哪些模式持续出现。
2. 识别反复出现的成功条件与失败模式。
3. 为 `DecisionPriorCard` 和 `AntiPatternCard` 提供原始证据聚合入口。

## 12. 大规模运行与增量更新

### 12.1 运行策略

当论文规模达到几万到几十万时，系统必须避免全量重算和全量驻内存。

建议分层：

1. 原始图谱层：Neo4j
2. 社区索引层：embedding、ANN、邻居表、membership 中间结果
3. 社区读模型层：供前端和后续编译消费的社区结果

### 12.2 增量更新

新增论文进入后：

1. 新增 `LogicStep`
2. 计算 embedding
3. 更新 ANN 索引
4. 仅为新 step 查找 top-k 邻居
5. 局部更新受影响社区
6. 周期性执行低频全局 refresh

### 12.3 内存控制原则

1. 不构建全量 step-step 相似矩阵。
2. 只保留 top-k 邻居。
3. 分批生成邻居。
4. 在稀疏矩阵或局部子图上运行社区检测。

## 13. 建议的工程边界

不建议把四层研究线全部塞回 LogicKG `main`。

建议：

1. LogicKG 主线继续负责第二层底座与查询接口。
2. 新建 `research_logic/` 子系统负责：
   - 第一层补齐
   - 第三层重建
   - 第四层归纳
   - 训练数据组装

建议目录：

1. `research_logic/exporters/`
2. `research_logic/environment_layer/`
3. `research_logic/route_builder/`
4. `research_logic/prior_builder/`
5. `research_logic/datasets/`
6. `research_logic/training/`
7. `research_logic/eval/`

## 14. 迁移策略

### 14.1 第一阶段

1. 冻结 `PaperLogicTrace` canonical export
2. 增补 L2.5 字段
3. 将当前社区系统降级为 baseline

### 14.2 第二阶段

1. 引入新的 `LogicStep` 候选图构建器
2. 落地重叠社区检测
3. 输出可解释社区读模型

### 14.3 第三阶段

1. 基于社区与 L2.5 资产建设 `TopicScopeBuilder`
2. 形成 `topic x year` 中间特征表
3. 为 `RouteState` 合成预留编译接口

## 15. 决策摘要

本设计确认以下决策：

1. LogicKG 应被重构为四层科研知识系统中的第二层底座，而不是单纯论文图谱产品。
2. 第二层的主要目标从“扩抽”转为“规范化导出 + 可训练资产化”。
3. 跨论文社区系统应完全重构，不再把 TreeComm 作为最终方案。
4. 新社区系统只聚类 `LogicStep`，支持重叠社区，不使用 `NEXT`。
5. 社区结果是第三层前置输入，不是第三层对象本身。
6. `Claim` 主要承担解释和证据角色，而不是主聚类角色。

## 16. 待进入实现计划的问题

在实现前仍需进一步冻结以下内容：

1. `PaperLogicTrace` 的最终字段与版本策略
2. L2.5 槽位的抽取来源与回退规则
3. 候选图边权组合公式与默认参数
4. `BigCLAM` 具体实现方式与依赖策略
5. 社区标题模板与关键词归纳规则
6. 读模型是否写回 Neo4j 还是同时导出 JSON/Parquet

这些问题应在实现计划中拆解为独立任务，并与试点 route packet 验证一起推进。
