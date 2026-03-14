# LogicKG 技术总览

## 1. 当前定位

LogicKG 现在是一个“文档导入 -> 图谱构建 -> 社区组织 -> 检索问答 -> 运维治理”的统一系统，而不是一组互相松散拼接的工具页。

当前主工作区已经明确收束到下面这条主线：

1. 论文和教材 Markdown 被导入为可追溯图资产。
2. 图资产围绕 `Claim / LogicStep / KnowledgeEntity / GlobalCommunity` 组织。
3. Ask、相似性、社区层和运维配置消费这些图层。
4. `discovery` 在线功能已下线，仅保留一次性历史清理路径。
5. Citation 语义增强作为独立基础能力保留。

## 2. 运行拓扑

```text
Markdown / Textbook Markdown
        |
        v
  FastAPI backend
        |
        +--> Neo4j                    # 主图数据库
        +--> FAISS                    # 向量索引
        +--> vendored Youtu TreeComm  # whole-graph community clustering
        +--> autoyoutu subprocess     # 教材章节图生成
        |
        v
 React + Vite frontend
```

后端入口是 `backend/app/main.py`，前端入口是 `frontend/src/App.tsx`。

## 3. 后端模块边界

`backend/app/` 现在可以按职责分为下面几层：

- `api/`
  负责 HTTP 契约，路由本身保持薄，业务逻辑下沉到 service、graph helper 或 task handler。
- `ingest/`
  负责论文/教材导入、重建、派生产物写回，以及历史清理编排。
- `extraction/`
  负责论文 phase1 抽取、质量门禁和 canonical graph 写入。
- `citations/`
  负责引用语义增强，包括 `citation act`、`citation mention`、polarity、purpose labels、semantic signals 和 target scopes。
- `community/`
  负责 whole-graph projection、TreeComm 聚类和 `GlobalCommunity / GlobalKeyword` 写回。
- `rag/`
  负责 Ask 查询规划、structured retrieval、grounding 和答案生成。
- `similarity/`
  负责 claim / logic step embedding、近邻计算和相似边写回。
- `fusion/`
  作为 Ask 与图视图的证据通道保留。
- `graph/`
  提供 Neo4j schema 与读写 helper。
- `tasks/`
  提供文件型异步任务队列与处理器。

## 4. 当前图模型

### 4.1 论文主图

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

常见关系包括：

- `Paper -[:HAS_CHUNK]-> Chunk`
- `Paper -[:HAS_LOGIC_STEP]-> LogicStep`
- `Paper -[:HAS_CLAIM]-> Claim`
- `LogicStep -[:HAS_CLAIM]-> Claim`
- `LogicStep/Claim -[:EVIDENCED_BY]-> Chunk`
- `Paper -[:HAS_REFERENCE]-> ReferenceEntry`
- `Paper -[:CITES]-> Paper`
- `Paper -[:CITES_UNRESOLVED]-> ReferenceEntry`

### 4.2 教材子图

教材子图以这些节点为主：

- `Textbook`
- `TextbookChapter`
- `KnowledgeEntity`

教材导入只保留实体与实体关系，不再导入远端 chapter-local community / keyword / super-node。

### 4.3 全局社区层

当前 whole-graph community layer 由这些节点组成：

- `GlobalCommunity`
- `GlobalKeyword`

输入投影只包含：

- `KnowledgeEntity`
- `Claim`
- `LogicStep`

这意味着共享社区层已经脱离旧 proposition 路径，也不依赖 discovery 图。

### 4.4 Citation 语义增强层

论文重建阶段会额外生成两类衍生产物：

- `citation_acts.json`
  聚合同一篇论文对同一目标论文的引用行为，包含 purpose labels、polarity、semantic signals、target scopes 等。
- `citation_mentions.json`
  描述具体引用落在正文哪个 chunk、哪组 ref_num、哪个 span。

这层能力用于增强引用理解与后续 claim target enrichment，不再依赖 Discovery 工作台。

### 4.5 已移除的 Discovery 图

`KnowledgeGap / ResearchQuestion / FeedbackRecord` 等 discovery 专属节点已不再是当前运行时模型的一部分。对应的历史数据清理由 `backend/scripts/cleanup_discovery.py` 一次性完成。

## 5. 论文重建流程

论文主链路可以概括为：

1. 解析 Markdown，生成统一文档对象。
2. 恢复 reference 和 citation event。
3. 执行 phase1 抽取与质量门禁。
4. 通过门禁后写入 `LogicStep / Claim / Evidence`。
5. 写入 citation purpose，并生成 citation semantic artifacts。
6. 落盘 `document_ir.json`、`citations.json`、`llm_imrad.json`、`llm_citation_purposes.json`、`citation_acts.json`、`citation_mentions.json`。

如果 phase1 gate 失败，会保留诊断信息，但跳过 canonical graph 写入，避免低质量结构污染主图。

## 6. 教材导入流程

教材链路分为四步：

1. 把大 Markdown 切分为章节。
2. 通过 subprocess 调用本地 `autoyoutu` 生成章节图。
3. 通过 normalizer 过滤掉远端 community/keyword/super-node 结构。
4. 把实体图写回 Neo4j，并在导入后触发一次 `GlobalCommunity` 重建。

## 7. Ask 与检索

Ask 当前统一走 `/rag/ask_v2` 内核，主流程包括：

1. 生成 query plan。
2. 并行组织 lexical、FAISS、structured retrieval、community、textbook、fusion evidence。
3. 进行归一化、融合排序和 grounding。
4. 把图上下文、结构化证据和答案一起返回前端。

`/rag/ask` 现在只是兼容入口，内部复用 `ask_v2`。

## 8. 前端结构

前端是 React + Vite 单页应用。

当前主路由：

- 图谱工作台：`/`、`/ask`
- 独立页面：`/ingest`、`/ops`
- 详情页：`/paper/:paperId`、`/textbooks/:textbookId`
- 兼容重定向：`/fusion -> /ask`、`/discovery -> /ops`

图壳模块只保留：

- `overview`
- `papers`
- `ask`
- `textbooks`
- `ops`

`DiscoveryPage`、顶部导航入口、Overview discovery 摘要和 Config Center discovery 面板都已移除。

## 9. Config Center 与 Ops

Config Center 现在只保留两块活跃配置面：

- `similarity`
- `schema`

本地 assistant 历史也会过滤掉旧的 discovery 建议锚点，避免把退役模块重新暴露给用户。

Ops 工作台仍然承载：

- 任务队列
- Config Center
- 未解析引用恢复

## 10. 任务系统

当前主要任务类型包括：

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

`discovery_batch` 已从任务模型与处理器中移除。

## 11. 配置与存储

核心配置入口仍然是 `backend/app/settings.py`。

当前活跃配置主要覆盖：

- Neo4j
- LLM
- embedding
- extraction / phase1 gate
- similarity / clustering
- task 并发
- pageindex
- autoyoutu
- global community

`storage/discovery/` 不再是活跃运行产物目录；它只在历史清理时被删除。

## 12. 当前边界

需要特别注意的边界如下：

- `cleanup_discovery.py` 是维护入口，不代表 discovery 功能仍在线。
- Citation 语义增强虽然最初来自 discovery 演进线，但现在作为独立基础能力保留。
- proposition 已从主运行时降级为历史清理对象，不再是 Ask、前端或图模型的核心概念。

## 13. 总结

从当前代码状态看，LogicKG 已经完成了从“论文图 + 教材图 + proposition 历史包袱 + discovery 工作台”向“统一结构化知识图 + whole-graph community layer + Ask / similarity / citation semantic enrichment + ops/config 治理”的主线收束。

当前真实的主运行闭环是：

1. 导入论文与教材
2. 生成结构化图
3. 构建全局社区与检索资产
4. 通过 Ask、similarity 和 citation semantic enrichment 消费这些图层
5. 用任务、配置和清理脚本维护系统状态
