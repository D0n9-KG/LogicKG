# LogicKG 技术总览

## 1. 文档范围

这份文档描述的是当前主仓库 `LogicKG` 的真实运行结构，而不是历史方案。重点是解释当前代码如何组织、系统如何运行、主数据模型是什么，以及 2026-03-11 这一轮 Global Community 迁移之后主流程已经变成了什么样子。

如果只用一句话概括当前系统：

> LogicKG 是一个把论文与教材 Markdown 转成可检索图谱资产，并在其上执行社区检测、问答检索、问题发现和运维治理的图谱系统。

当前主线已经完成两件重要收束：

- 教材图谱不再导入远端 chapter-local community / keyword / super-node
- Ask、discovery 和前端主流程不再依赖旧 `proposition` 运行时

## 2. 系统定位

现在的 LogicKG 不是“单一论文查看器”，也不是“只有向量检索的 RAG demo”。它更接近一个分层知识系统：

1. 文档导入层：接收论文 Markdown 和教材 Markdown
2. 图谱构建层：把文本转成论文图、教材图和全局社区图
3. 检索与问答层：把 chunk、claim、logic step、community、textbook 等多种证据源组织成 Ask 上下文
4. 发现与治理层：从现有图谱中识别 gap、生成候选问题、接收反馈，并通过任务与配置中心管理系统运行

也因此，当前代码库虽然包含 `ingest / rag / discovery / community / similarity / fusion / schema / tasks` 多个模块，但它们不是离散工具集合，而是围绕同一个知识图运行面的不同层。

## 3. 运行拓扑

当前系统的基本运行拓扑如下：

```text
Markdown / Textbook Markdown
        |
        v
  FastAPI backend
        |
        +--> Neo4j                    # 主图数据库
        +--> FAISS                    # 结构化与 chunk 向量检索
        +--> vendored Youtu TreeComm  # 全局社区聚类
        +--> autoyoutu subprocess     # 教材章节图生成
        |
        v
 React + Vite frontend
```

### 3.1 后端

后端入口是 [main.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/main.py)。它注册了这些主路由：

- `health`
- `ingest`
- `rag`
- `graph`
- `tasks`
- `papers`
- `paper_edits`
- `schema`
- `collections`
- `discovery`
- `config-center`
- `community`
- `fusion`
- `textbooks`

同时在应用生命周期中注册任务处理器，并启动文件型任务队列。

### 3.2 前端

前端是 React + Vite 单页应用。主路由定义在 [App.tsx](/C:/Users/D0n9/Desktop/LogicKG/frontend/src/App.tsx)：

- 图谱工作台 shell：`/`、`/ask`
- 独立页面：`/ingest`、`/discovery`、`/ops`
- 详情页：`/paper/:paperId`、`/textbooks/:textbookId`
- 兼容重定向：`/fusion -> /ask`

图谱工作台本身仍然以“总览 / 论文 / Ask / 教材 / 运维”五类模块为核心；而导入页和 discovery 页是独立的 workbench，不再强塞进同一个图壳里。

### 3.3 数据与索引

当前运行依赖两种核心存储：

- Neo4j：保存论文图、教材图、全局社区图、discovery 图和相似性边
- FAISS：保存 chunk 语料和结构化语料（claim / logic_step / community）

`storage/` 目录下面同时承载：

- `storage/faiss/`：全局 FAISS
- `storage/textbooks/`：教材章节图 JSON 副本
- `storage/similarity/`：claim / logic 相似度索引与 embedding
- `storage/discovery/`：discovery prompt policy 等运行产物
- `storage/derived/`：重建时落出的中间结构化产物

## 4. 当前数据模型

当前图模型可以分成四块看。

### 4.1 论文图

论文主图围绕这些节点展开：

- `Paper`
- `Chunk`
- `ReferenceEntry`
- `LogicStep`
- `Claim`
- `EvidenceEvent`
- `Figure`
- `Author`
- `Collection`

常见主关系包括：

- `Paper -[:HAS_CHUNK]-> Chunk`
- `Paper -[:HAS_LOGIC_STEP]-> LogicStep`
- `Paper -[:HAS_CLAIM]-> Claim`
- `LogicStep -[:HAS_CLAIM]-> Claim`
- `LogicStep/Claim -[:EVIDENCED_BY]-> Chunk`
- `Paper -[:HAS_REFERENCE]-> ReferenceEntry`
- `Paper -[:CITES]-> Paper`
- `Paper -[:CITES_UNRESOLVED]-> ReferenceEntry`

另外，论文图还会挂载：

- `SIMILAR_CLAIM`
- `SIMILAR_LOGIC`
- 以及面向教材锚点与 fusion 的 `EXPLAINS`

### 4.2 教材图

教材图是当前主仓库里最重要的新子图之一，节点包括：

- `Textbook`
- `TextbookChapter`
- `KnowledgeEntity`

主要关系包括：

- `Textbook -[:HAS_CHAPTER]-> TextbookChapter`
- `TextbookChapter -[:HAS_ENTITY]-> KnowledgeEntity`
- `KnowledgeEntity -[:RELATES_TO]-> KnowledgeEntity`
- `LogicStep -[:EXPLAINS]-> KnowledgeEntity`

这里有一个关键设计：教材导入只保留实体与实体关系，不再接收远端章节社区结构。

### 4.3 全局社区图

全局社区图是在整图投影上构建的二级结构，节点包括：

- `GlobalCommunity`
- `GlobalKeyword`

主要关系包括：

- `KnowledgeEntity/Claim/LogicStep -[:IN_GLOBAL_COMMUNITY]-> GlobalCommunity`
- `GlobalCommunity -[:HAS_GLOBAL_KEYWORD]-> GlobalKeyword`

这部分是 Ask、structured retrieval 和 discovery 的重要中间层。

### 4.4 Discovery 图

当前 schema 中已经有这些 discovery 相关节点：

- `KnowledgeGapSeed`
- `KnowledgeGap`
- `ResearchQuestion`
- `ResearchQuestionCandidate`
- `FeedbackRecord`

批处理 discovery 的最新候选主要由 `/discovery/candidates` 暴露给前端；Neo4j 中的 discovery helper 则负责把 gap、question、community 来源和反馈等信息写回图中。

### 4.5 Proposition 迁移状态

现在主流程里不再把 `Proposition` 作为一等运行时概念使用。

当前状态是：

- Ask 主流程使用 `Claim / LogicStep / GlobalCommunity / Textbook`
- discovery 以 community 和 claim 为证据来源，不再依赖 proposition contract
- 前端节点类型、计数与样式中已移除 proposition
- 后端保留的 `/tasks/cleanup/propositions` 是一次性迁移/清理入口，而不是正常业务流程的一部分

也就是说，旧 proposition 已经从“运行时契约”降级为“历史清理对象”。

## 5. 后端模块分层

`backend/app/` 当前可以按职责分为几个稳定模块。

### 5.1 `api/`

只负责 HTTP 契约。所有路由都比较薄，实际逻辑下沉到 service、graph 或 task handler。

### 5.2 `ingest/`

负责论文和教材导入，以及相关重建动作：

- 论文导入
- 上传扫描与分片组装
- 教材切章
- autoyoutu 子进程调用
- Youtu graph JSON 导入
- 全局 FAISS 重建
- 旧 proposition 残留清理

### 5.3 `extraction/`

负责论文 phase1 抽取与质量门禁。当前主流程的 canonical 写入已经围绕：

- `LogicStep`
- `Claim`
- `EVIDENCED_BY`

展开，而不是旧 proposition 图层。

### 5.4 `community/`

这一层承接了本轮迁移的重点：

- whole-graph projection
- vendored TreeComm 调用
- 全局社区写回
- 远端教材社区过滤

### 5.5 `rag/`

负责 Ask 规划、检索、structured retrieval、grounding 和答案生成。`/rag/ask` 和 `/rag/ask_v2` 已统一到同一套内部实现。

### 5.6 `discovery/`

负责 gap 检测、候选问题生成、证据审计、排序、反馈与 prompt policy 更新。

### 5.7 `graph/`

核心是 [neo4j_client.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/graph/neo4j_client.py)。它既是 schema 管理器，也是所有图读写 helper 的聚合点。

### 5.8 `similarity/`

负责 claim / logic step embedding、FAISS / matrix 计算和 `SIMILAR_CLAIM` / `SIMILAR_LOGIC` 写回。

### 5.9 `fusion/`

fusion 仍然存在，但角色已经从“独立 UI 模块”转向“Ask 和图谱视图的后端证据通道”。前端 `/fusion` 路由已直接重定向到 `/ask`。

### 5.10 `tasks/`

任务系统是当前后端异步编排的统一入口，支持：

- 导入
- 重建
- similarity
- fusion
- global community
- discovery
- proposition 清理

## 6. 论文导入与重建流程

论文主流程现在可以概括为下面几步。

### 6.1 解析与文档对象化

`ingest` 先把 Markdown 解析成统一文档对象，包括 paper 元数据、chunk、引用、citation span 等。

### 6.2 引用恢复

系统会调用：

- Crossref 解析
- reference fallback agent
- citation event recovery

把参考文献和引用边尽量补齐。

### 6.3 Phase1 抽取与质量门禁

当前 canonical 抽取是 phase1 quality-first 路径：

- 先产出 `LogicStep`
- 再产出 `Claim`
- 再做 grounding / evidence gate / quality tier 判断

如果质量门禁失败，系统会保留诊断信息，但跳过 canonical graph 写入，避免低质量结构进入主图。

### 6.4 写入与重建

如果通过门禁，系统会写入：

- `Paper`
- `Chunk`
- `LogicStep`
- `Claim`
- 引用与 `CITES`
- 图像、证据边等

随后可触发：

- 全局 FAISS 重建
- 相似性重建
- fusion 重建

## 7. 教材导入流程

教材链路是这轮迁移后最值得单独说明的一部分。

### 7.1 分章

[textbook_pipeline.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/ingest/textbook_pipeline.py) 会先把大 Markdown 切分成章节，并为整本书生成稳定 `textbook_id`。

### 7.2 调 autoyoutu

每章都通过 subprocess 调用外部 `autoyoutu` 工程，而不是把它直接 import 到 LogicKG 进程里。这样做的目的是保持依赖边界清晰，避免把外部项目的依赖树直接混进主后端。

### 7.3 规范化远端图

章节图落库前会经过 [remote_graph_normalizer.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/community/remote_graph_normalizer.py) 处理。

它会显式丢弃：

- `community`
- `keyword`
- `super-node`
- `super_node`
- `supernode`

以及相关关系：

- `member_of`
- `keyword_of`
- `represented_by`
- `kw_filter_by`
- `belongs_to`
- `describes`

也就是说，导入到本地教材图里的只会是实体和实体关系。

### 7.4 导入教材子图

[graph_importer.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/ingest/graph_importer.py) 会把 Youtu 图转成本地图结构：

- Youtu `node` -> `KnowledgeEntity`
- Youtu `edge` -> `RELATES_TO`
- `TextbookChapter -[:HAS_ENTITY]-> KnowledgeEntity`

### 7.5 导入后立即重建全局社区

教材导入完成后，系统会自动触发一次 `rebuild_global_communities()`。因此教材知识不是孤立存在的，它会立刻并入当前整图的全局社区层。

## 8. Global Community 迁移后的真实结构

这部分是本次技术总览中最需要和旧文档切开的地方。

### 8.1 投影来源

当前全局社区投影由 [projection.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/community/projection.py) 构建，只包含三类节点：

- `KnowledgeEntity`
- `Claim`
- `LogicStep`

对应来源分别是：

- 教材实体
- 论文主张
- 论文逻辑步骤

也就是说，当前社区层是一个跨教材与论文的 whole-graph community layer，而不是章节本地聚类结果。

### 8.2 聚类实现

社区 service 在 [service.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/community/service.py) 中执行：

1. 构建整图投影
2. 调用 `run_tree_comm`
3. 写回 `GlobalCommunity`
4. 写回 `GlobalKeyword`
5. 重建 `IN_GLOBAL_COMMUNITY`

`run_tree_comm` 的实际实现位于 [tree_comm_adapter.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/community/tree_comm_adapter.py)，并最终解析到：

- [tree_comm.py](/C:/Users/D0n9/Desktop/LogicKG/backend/vendor/youtu_graphrag/utils/tree_comm.py)

也就是 vendored 的 Youtu TreeComm，而不是旧的 fusion clustering 假适配器。

### 8.3 Vendor 兼容层

为了不在仓库根级继续保留顶层 shim，TreeComm 的兼容层已经被下沉到 vendor 包内部：

- [torch.py](/C:/Users/D0n9/Desktop/LogicKG/backend/vendor/youtu_graphrag/_compat/torch.py)
- [sentence_transformers.py](/C:/Users/D0n9/Desktop/LogicKG/backend/vendor/youtu_graphrag/_compat/sentence_transformers.py)

这保证了 TreeComm 的特殊依赖是 vendor 自己管理的，而不是对整个后端 import 路径造成污染。

### 8.4 落库结果

聚类结果最终写入：

- `GlobalCommunity`
- `GlobalKeyword`
- `IN_GLOBAL_COMMUNITY`
- `HAS_GLOBAL_KEYWORD`

structured retrieval、Ask 和 discovery 都从这一层读社区信息。

### 8.5 教材页里的 `community:derived:*` 是什么

教材图快照 helper [textbook_graph.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/graph/textbook_graph.py) 仍然会在页面展示时临时生成 `community:derived:*` 分组。

这些分组只是本地显示辅助，不是：

- 远端导入结果
- `GlobalCommunity`
- 持久化 Neo4j 社区节点

因此不能把它们和全局社区层混为一谈。

## 9. Ask 检索与问答流程

Ask 是当前系统最复杂的在线路径之一。

### 9.1 路由层

[rag.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/api/routers/rag.py) 提供三类入口：

- `POST /rag/ask_v2`
- `POST /rag/ask`
- `POST /rag/ask_v2_stream`

其中 `/rag/ask` 已直接复用 `ask_v2` 内核。

### 9.2 查询规划

[rag/service.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/rag/service.py) 会先调用 planner 生成结构化 query plan，再决定检索顺序和证据组合方式。

系统现在已经支持：

- `paper_query`
- `textbook_query`
- `community_query`
- conversation-aware follow-up
- bilingual rewrite
- textbook-first retrieval plan

### 9.3 多通道证据

当前 Ask 不再只依赖 chunk 向量检索，而是多通道并行：

- lexical chunk retrieval
- FAISS chunk retrieval
- structured retrieval：`claim / logic_step / community`
- textbook anchors
- fusion evidence
- pageindex（可选）

检索结果随后会做：

- 归一化
- 融合排序
- grounding
- dual-evidence coverage 判断

最终把图上下文、结构化证据、grounding 和答案一起返回给前端。

### 9.4 结构化语料

[structured_retrieval.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/rag/structured_retrieval.py) 当前维护三类结构化语料：

- `logic_steps`
- `claims`
- `communities`

其中 `communities` 语料是从 `GlobalCommunity` 现算的，不再来自 proposition group。

## 10. Discovery 流程

discovery 现在是一条独立但已经接入主图的后端链路。

### 10.1 批处理入口

[discovery.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/api/routers/discovery.py) 暴露：

- `POST /discovery/batch`
- `GET /discovery/candidates`
- `GET /discovery/candidates/{candidate_id}`
- `POST /discovery/feedback`

### 10.2 批处理阶段

[service.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/discovery/service.py) 中的 `run_discovery_batch()` 会按顺序执行：

1. `detect_knowledge_gaps`
2. `generate_candidate_questions`
3. 构建 hybrid context
4. `audit_candidate_evidence`
5. `rank_candidates`
6. 更新 prompt policy
7. 把结果写回 discovery graph

### 10.3 上下文来源

discovery 的 hybrid context 目前可组合三类外部来源：

- adjacent papers
- random papers
- community-derived papers

`community_method` 支持：

- `author_hop`
- `louvain`
- `hybrid`

虽然参数名里还保留了 `louvain` 这种历史术语，但主系统的共享社区层已经切到 `GlobalCommunity`。

### 10.4 反馈

反馈入口是 `accepted / rejected / needs_revision`。反馈会：

- 更新候选状态与得分
- 写入 `FeedbackRecord`
- 反哺 prompt policy bandit

## 11. 相似性与 Fusion

### 11.1 Similarity

[similarity/service.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/similarity/service.py) 负责：

- 收集 `Claim` 与 `LogicStep` 的有效文本
- 生成 embedding
- 构建近邻
- 写回 `SIMILAR_CLAIM` 与 `SIMILAR_LOGIC`

这层现在已经不再承担 proposition group 聚类职责。

### 11.2 Fusion

fusion 仍然有自己的后端 service 和图结构：

- `FusionCommunity`
- `FusionKeyword`
- `EXPLAINS`

它主要服务于：

- paper section basics 检索
- Ask 中的 fusion evidence 补强
- 图谱聚合视图

但不再是当前社区迁移的核心聚类实现。

## 12. 配置中心与 Schema 治理

### 12.1 Schema 版本

[schema.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/api/routers/schema.py) 暴露了完整的 schema 生命周期：

- 读取 active schema
- 查看历史版本
- 新建版本
- 激活版本
- 删除版本
- 校验 schema
- 应用 preset

当前 preset 有三类：

- `high_precision`
- `balanced`
- `high_recall`

### 12.2 Config Center

[config_center.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/api/routers/config_center.py) 统一管理：

- discovery 参数
- similarity 参数
- schema 规则与 prompt 编辑入口

它还提供一个基于启发式/LLM 的配置建议助手，但主配置仍然是显式版本化和人工确认的，不会静默自动改写 active schema。

## 13. 任务系统与运维

任务模型定义在 [models.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/tasks/models.py)，当前主要任务类型包括：

- `ingest_path`
- `ingest_upload_ready`
- `upload_replace`
- `rebuild_paper`
- `rebuild_faiss`
- `rebuild_all`
- `rebuild_similarity`
- `rebuild_fusion`
- `rebuild_global_communities`
- `cleanup_legacy_propositions`
- `update_similarity_paper`
- `ingest_textbook`
- `discovery_batch`

任务系统的特点是：

- 文件型持久化
- 有进度、阶段、日志、结果字段
- 前端运维页可直接消费
- 适合大导入与重建流程

## 14. 前端结构

### 14.1 Shell 与模块

前端状态定义在 [types.ts](/C:/Users/D0n9/Desktop/LogicKG/frontend/src/state/types.ts)。图壳层的模块包括：

- `overview`
- `papers`
- `ask`
- `textbooks`
- `ops`

而 `ingest` 和 `discovery` 走独立页面。

### 14.2 主要页面

当前前端主要由这些页面/工作台组成：

- 导入中心：上传、扫描、任务轮询、冲突处理
- Ask：图谱增强问答、结构化证据、grounding、子图视图
- 教材页：教材目录、章节图、教材快照
- Discovery：批处理、候选问题列表、反馈
- Ops：任务队列、配置中心、未解析引用

### 14.3 图展示

图渲染同时使用：

- Cytoscape 2D 图
- 3D Force Graph

不同页面按场景切换布局：

- `cose`
- `dagre`
- `breadthfirst`
- `concentric`
- `preset`

## 15. 环境与配置

[settings.py](/C:/Users/D0n9/Desktop/LogicKG/backend/app/settings.py) 是当前后端配置的唯一规范入口，主要包括：

- Neo4j
- LLM
- embedding
- phase1 gate
- similarity / clustering
- task 并发
- pageindex
- autoyoutu
- global community

其中和本轮迁移强相关的配置有：

- `AUTOYOUTU_DIR`
- `GLOBAL_COMMUNITY_VERSION`
- `GLOBAL_COMMUNITY_MAX_NODES`
- `GLOBAL_COMMUNITY_MAX_EDGES`
- `GLOBAL_COMMUNITY_TOP_KEYWORDS`
- `GLOBAL_COMMUNITY_TREE_COMM_EMBEDDING_MODEL`
- `GLOBAL_COMMUNITY_TREE_COMM_STRUCT_WEIGHT`

## 16. 当前边界与注意事项

当前系统虽然已经完成主流程收束，但还有几个边界需要明确。

### 16.1 `cleanup/propositions` 仍然保留

这不是回退 proposition 运行时，而是给存量图做一次性清理和重建的维护入口。

### 16.2 全局社区质量依赖上游抽取质量

TreeComm 已经是真实跑在本地 whole-graph projection 上，但聚类效果仍然强依赖：

- claim / logic step 文本质量
- 教材实体清洗质量
- embedding 提供方稳定性

也就是说，社区层已经完成“路径正确”的迁移，但“主题质量”仍然是一个持续优化问题。

### 16.3 教材页展示社区与持久化全局社区不是一回事

教材快照里的 `community:derived:*` 只用于页面组织，不代表持久化社区节点。

### 16.4 `fusion` 仍在，但不是社区主算法

当前 community migration 的结论应该始终以：

- `backend/app/community/*`
- `backend/vendor/youtu_graphrag/*`

这两层为准，而不是以旧 fusion clustering 视角理解。

## 17. 总结

从当前代码状态看，LogicKG 已经完成了从“论文图 + 零散教材支持 + proposition 历史包袱”向“统一结构化知识图 + 教材实体图 + 本地全局社区层 + community-first Ask/discovery”的主线收束。

它现在的主运行闭环是：

1. 导入论文与教材
2. 生成结构化图
3. 构建全局社区和结构化检索语料
4. 通过 Ask 和 discovery 消费这些图层
5. 用任务、配置中心和清理任务维护系统状态

这也是理解当前仓库最重要的切口：主图谱已经不再围绕 proposition，而是围绕 `Claim / LogicStep / KnowledgeEntity / GlobalCommunity` 运行。
