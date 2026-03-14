# LogicKG

LogicKG 是一个面向科研论文与教材 Markdown 的知识图谱系统。它把文档转换为可追溯、可检索、可聚类、可问答的图资产，并在此基础上提供论文/教材导入、全图社区重建、GraphRAG 问答、相似性分析、引用语义增强和运维配置能力。

当前主工作区已经完成两条关键收束：

- 主运行时围绕 `Claim / LogicStep / KnowledgeEntity / GlobalCommunity` 运转，不再依赖旧 `proposition` 路径。
- `discovery` 功能已整体下线；旧书签访问 `/discovery` 时会前端重定向到 `/ops`。

## 核心能力

- 论文导入与重建：把 MinerU Markdown 写入 `Paper / Chunk / ReferenceEntry / LogicStep / Claim / EvidenceEvent / Figure` 图结构。
- 教材导入：把教材 Markdown 切章后生成 `Textbook / TextbookChapter / KnowledgeEntity` 子图。
- 全局社区重建：基于 `KnowledgeEntity + Claim + LogicStep` 的 whole-graph projection，调用 vendored Youtu TreeComm 生成 `GlobalCommunity / GlobalKeyword`。
- Ask 问答：统一走 `/rag/ask_v2` 内核，融合 lexical、FAISS、structured retrieval、community、textbook 与 fusion evidence。
- 相似性分析：重建 claim / logic step embedding，写回 `SIMILAR_CLAIM` / `SIMILAR_LOGIC`。
- Citation 语义增强：从引用上下文生成 `citation_acts.json`、`citation_mentions.json`，保留 polarity、purpose、semantic signals 和 target scopes。
- 运维与配置：提供任务队列、Config Center、Schema 管理、未解析引用恢复与历史清理脚本。

## 仓库结构

```text
.
├─ backend/
│  ├─ app/
│  │  ├─ api/              # FastAPI routers
│  │  ├─ citations/        # citation semantic enrichment
│  │  ├─ community/        # GlobalCommunity projection + TreeComm adapter
│  │  ├─ extraction/       # phase1 extraction and quality gate
│  │  ├─ fusion/           # fusion graph and retrieval support
│  │  ├─ graph/            # Neo4j client and graph snapshot helpers
│  │  ├─ ingest/           # paper/textbook ingest and rebuild pipelines
│  │  ├─ rag/              # ask planner, retrieval, grounding, answer generation
│  │  ├─ similarity/       # claim / logic similarity rebuilds
│  │  ├─ tasks/            # async task queue and handlers
│  │  └─ vector/           # FAISS build/load helpers
│  ├─ scripts/
│  │  └─ cleanup_discovery.py   # one-shot legacy discovery cleanup
│  └─ tests/
├─ frontend/
│  ├─ src/
│  └─ tests/
├─ docs/
├─ docker-compose.yml
├─ run.ps1
└─ TECHNICAL_OVERVIEW.zh-CN.md
```

## 快速开始

### 依赖

- Python 3.11
- Node.js 18+
- Neo4j 5.x
- 可用的 LLM 与 embedding 配置
- 教材导入额外需要本地 `autoyoutu` 工程目录

### 环境变量

复制根目录 `.env.example` 为 `.env`，至少补齐：

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

### 启动

如果本机没有 Neo4j：

```bash
docker compose up -d
```

推荐直接在仓库根目录运行：

```bash
npm run dev
```

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

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端 OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 常见工作流

### 论文导入

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

### 教材导入

```bash
curl -X POST http://127.0.0.1:8000/textbooks/ingest ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/books/book.md\",\"title\":\"Example Textbook\",\"authors\":[\"Author A\"],\"year\":2024}"
```

### 全局社区重建

```bash
curl -X POST http://127.0.0.1:8000/tasks/rebuild/community ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

### 一次性清理遗留 discovery 数据

```bash
cd backend
.\.venv\Scripts\python.exe scripts/cleanup_discovery.py
```

这个脚本是维护入口，不代表 `discovery` 仍然是在线功能。

## 关键 API

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
- `GET /config-center/profile`
- `GET /config-center/catalog`
- `POST /config-center/assistant`
- `GET /schema/active`

## 开发验证

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

## 当前实现说明

- `/rag/ask` 已完全复用 `ask_v2` 内核。
- 教材导入会过滤远端 chapter-local community / keyword / super-node，只保留教材实体图。
- `GlobalCommunity` 由本地 whole-graph projection + vendored Youtu TreeComm 生成。
- 前端 `/fusion` 路由重定向到 `/ask`。
- 前端 `/discovery` 路由重定向到 `/ops`，Discovery 页面与配置入口已移除。
- Citation 语义增强保留为论文重建的一部分，不再依赖 Discovery 工作台。

## 相关文档

- [TECHNICAL_OVERVIEW.zh-CN.md](TECHNICAL_OVERVIEW.zh-CN.md)
