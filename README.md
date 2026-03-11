# LogicKG

LogicKG 是一个面向科研论文与教材知识的图谱系统。它把 Markdown 文档转成可追溯、可检索、可聚类、可问答的图数据，并在此基础上提供教材导入、全图社区检测、GraphRAG 问答、问题发现、相似性分析和配置治理能力。

当前主流程已经完成从旧 `proposition` 运行时向 `Claim / LogicStep / KnowledgeEntity / GlobalCommunity` 的迁移。教材导入不会再落远端 chapter-local community 结构；全局社区由本地 whole-graph projection + vendored Youtu TreeComm 重建。

## 1. 当前核心能力

- 论文导入与重建：将 MinerU Markdown 写入 `Paper / Chunk / ReferenceEntry / LogicStep / Claim / EvidenceEvent / Figure` 图结构。
- 教材导入与章节图谱：将教材 Markdown 切章后交给 autoyoutu 生成章节图，再落库为 `Textbook / TextbookChapter / KnowledgeEntity` 子图。
- 全局社区检测：基于 `KnowledgeEntity + Claim + LogicStep` 的整图投影，使用 vendored Youtu TreeComm 生成 `GlobalCommunity / GlobalKeyword`。
- Ask 问答：统一走 `/rag/ask_v2` 内核，融合 lexical、FAISS、structured retrieval、community、textbook 和 fusion evidence。
- Discovery：从当前图谱中检测 gap、生成候选研究问题、做证据审计和人工反馈闭环。
- 配置与运维：提供 schema 版本管理、Config Center、任务队列、重建入口与清理任务。

## 2. 技术栈

- 后端：FastAPI
- 前端：React 19 + Vite + TypeScript
- 图数据库：Neo4j 5.x
- 向量检索：FAISS
- 教材社区算法：vendored Youtu TreeComm
- 模型接入：OpenAI-compatible LLM / embedding provider

## 3. 仓库结构

```text
.
├─ backend/
│  ├─ app/
│  │  ├─ api/              # FastAPI routers
│  │  ├─ community/        # GlobalCommunity projection + TreeComm adapter
│  │  ├─ discovery/        # gap detection / candidate generation / feedback
│  │  ├─ extraction/       # phase1 extraction and quality gate
│  │  ├─ fusion/           # fusion graph and retrieval support
│  │  ├─ graph/            # Neo4j client and graph snapshot helpers
│  │  ├─ ingest/           # paper/textbook ingest and rebuild pipelines
│  │  ├─ rag/              # ask planner, retrieval, grounding, answer generation
│  │  ├─ similarity/       # claim / logic similarity rebuilds
│  │  ├─ tasks/            # async task queue and handlers
│  │  └─ vector/           # FAISS build/load helpers
│  ├─ tests/
│  ├─ vendor/youtu_graphrag/
│  └─ requirements.txt
├─ frontend/
│  ├─ src/
│  ├─ tests/
│  └─ package.json
├─ docs/
├─ docker-compose.yml
├─ run.ps1
├─ README.md
└─ TECHNICAL_OVERVIEW.zh-CN.md
```

## 4. 快速开始

### 4.1 依赖

- Python 3.11 推荐
- Node.js 18+
- Neo4j 5.x
- 可用的 LLM 与 embedding 配置
- 教材导入额外需要本地 `autoyoutu` 工程目录

### 4.2 环境变量

复制根目录 `.env.example` 为 `.env`，至少补齐这些值：

```env
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=please_change_me

AUTOYOUTU_DIR=C:/path/to/autoyoutu

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_API_KEY=

EMBEDDING_PROVIDER=siliconflow
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://api.siliconflow.com/v1
```

说明：

- 后端优先读取 `backend/.env`，其次读取根目录 `.env`。
- `AUTOYOUTU_DIR` 仅在教材导入时必需。
- embedding 配置会被 Ask、similarity、TreeComm、FAISS 共用。

### 4.3 启动 Neo4j

如果你本机没有现成 Neo4j，可以使用：

```bash
docker compose up -d
```

### 4.4 启动开发环境

推荐直接在仓库根目录运行：

```bash
npm run dev
```

这个命令会：

- 检查并创建后端虚拟环境
- 安装 `backend/requirements.txt`
- 安装前端依赖
- 自动选择空闲端口
- 同步前端 `VITE_API_URL`
- 同时启动后端和前端

也可以手动启动：

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

默认访问地址：

- 前端：`http://127.0.0.1:5173`
- 后端 OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 5. 常见工作流

### 5.1 论文导入

同步导入：

```bash
curl -X POST http://127.0.0.1:8000/ingest/path ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/data/mineru_output\"}"
```

异步任务导入：

```bash
curl -X POST http://127.0.0.1:8000/tasks/ingest/path ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/data/mineru_output\"}"
```

### 5.2 教材导入

```bash
curl -X POST http://127.0.0.1:8000/textbooks/ingest ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/books/book.md\",\"title\":\"Example Textbook\",\"authors\":[\"Author A\"],\"year\":2024}"
```

教材导入完成后会自动触发一次 `GlobalCommunity` 全量重建。

### 5.3 全局社区重建

```bash
curl -X POST http://127.0.0.1:8000/tasks/rebuild/community ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

### 5.4 清理旧 proposition 残留

```bash
curl -X POST http://127.0.0.1:8000/tasks/cleanup/propositions
```

这个任务是一次性维护入口，会删除旧 `Proposition / PropositionGroup` 相关图和陈旧的 FAISS 产物，然后重建 `GlobalCommunity` 与结构化检索语料。

## 6. 关键 API 入口

- `GET /health`
- `POST /ingest/path`
- `POST /tasks/ingest/path`
- `POST /textbooks/ingest`
- `GET /textbooks`
- `GET /textbooks/{textbook_id}/graph`
- `POST /tasks/rebuild/community`
- `GET /community/list`
- `GET /community/{community_id}`
- `POST /rag/ask`
- `POST /rag/ask_v2`
- `POST /rag/ask_v2_stream`
- `POST /discovery/batch`
- `GET /discovery/candidates`
- `POST /discovery/feedback`
- `GET /config-center/profile`
- `GET /schema/active`

## 7. 开发与验证

前端：

```bash
cd frontend
npm run lint
npm run test
npm run build
```

后端：

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

针对社区与 Ask 的常用聚焦回归：

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest ^
  tests/test_tree_comm_adapter.py ^
  tests/test_global_community_service.py ^
  tests/test_rag_service.py ^
  tests/test_rag_structured_retrieval.py -q
```

## 8. 当前实现说明

- `/rag/ask` 已经完全切到 `ask_v2` 内核。
- 教材导入会过滤远端 `community / keyword / super-node` 节点与相关边，只保留章节知识实体和实体关系。
- `GlobalCommunity` 由本地 whole-graph projection + vendored Youtu TreeComm 生成，不再走旧的假适配器。
- 前端 `/fusion` 路由已重定向到 `/ask`；fusion 仍作为后端数据与证据通道存在。
- 旧 proposition 运行时已从 Ask / discovery / frontend 主流程中移除，保留的只有清理任务与兼容测试。

## 9. 相关文档

- [TECHNICAL_OVERVIEW.zh-CN.md](TECHNICAL_OVERVIEW.zh-CN.md)
