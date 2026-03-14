# LogicKG

LogicKG 是一个面向科研论文与教材 Markdown 数据的知识图谱工作台。它负责把文档内容导入 Neo4j 图数据库，抽取并组织 `Paper`、`Claim`、`LogicStep`、`KnowledgeEntity`、`Textbook`、`GlobalCommunity` 等结构化节点，再通过 FastAPI 后端、任务队列和 React 前端提供图谱浏览、问答、教材结构分析、运维配置与导入管理能力。

当前仓库的 `main` 分支就是项目的最新主线状态，已经完成这轮主工作区整理与迁移，旧的以 `discovery`、`proposition` 为核心的历史路径不再作为当前产品主流程。

## 当前产品面

前端目前围绕以下几个主模块工作：

- `总览 Overview`：全局知识图谱总览，支持 2D / 3D 浏览。
- `论文 Papers`：论文图谱浏览、论文详情与引用脉络查看。
- `问答 Ask`：结合图结构与检索证据的问答入口。
- `教材 Textbooks`：教材、章节与知识实体结构查看。
- `运维 Ops`：任务、配置中心、Schema 管理等运维入口。
- `导入中心 Import Center`：论文与教材导入、上传及重建任务入口。

当前仍保留的兼容跳转：

- `/fusion` -> `/ask`
- `/discovery` -> `/ops`

## 核心能力

- 将论文 Markdown 导入为论文、分块、引用、Claim、LogicStep、图示与证据图谱。
- 将教材 Markdown 或教材上传文件导入为教材、章节和知识实体图谱。
- 基于 Claim、LogicStep 与实体构建全局 community / overview 图，用于聚类与总览浏览。
- 提供 GraphRAG 风格问答流程，融合词法、向量、结构、community 与教材证据。
- 支持相似度索引、FAISS 向量库、community 图等重建任务。
- 支持 citation 边增强、证据聚合和图谱关系补全。
- 提供任务中心、配置中心、Schema 管理、导入操作等界面。

## 架构概览

```text
论文 / 教材 Markdown 或上传文件
            |
            v
      导入与抽取流水线
            |
            v
Neo4j 图数据库 + 本地存储 + 任务产物
            |
            +--> community / similarity / FAISS 重建
            +--> citation 增强
            +--> ask 检索与回答生成
            |
            v
        FastAPI 路由层
            |
            v
      React + Vite 前端
```

## 仓库结构

```text
.
|-- backend/
|   |-- app/
|   |   |-- api/           # FastAPI 路由
|   |   |-- citations/     # 引用建模、投影、写回
|   |   |-- community/     # 全局 community / overview 图
|   |   |-- extraction/    # 论文抽取与质量门控
|   |   |-- fusion/        # 问答与图融合能力
|   |   |-- graph/         # Neo4j 客户端与图快照逻辑
|   |   |-- ingest/        # 论文/教材导入与上传流程
|   |   |-- llm/           # 模型供应商客户端、Schema、评审逻辑
|   |   |-- rag/           # Ask 检索、规划、答案生成
|   |   |-- similarity/    # 相似度重建逻辑
|   |   |-- tasks/         # 异步任务队列、处理器、持久化
|   |   `-- vector/        # FAISS 等向量能力
|   |-- scripts/
|   |   `-- cleanup_discovery.py
|   `-- tests/
|-- frontend/
|   |-- src/
|   |   |-- components/
|   |   |-- loaders/
|   |   |-- pages/
|   |   |-- panels/
|   |   `-- state/
|   `-- tests/
|-- docs/
|-- tests/                 # PowerShell 启动脚本测试
|-- docker-compose.yml
|-- run.lib.ps1
|-- run.ps1
`-- TECHNICAL_OVERVIEW.zh-CN.md
```

## 环境要求

- Python `3.11`
- Node.js `18+`
- Neo4j `5.x`
- 至少一个可用的大模型对话 / completion 供应商
- 至少一个可用的 embedding 供应商
- 仅在教材特定抽取流程需要时安装 `autoyoutu`

## 快速开始

### 1. 启动 Neo4j

如果本机还没有 Neo4j，可以直接使用：

```bash
docker compose up -d
```

当前 `docker-compose.yml` 默认只绑定到 `127.0.0.1`，更适合本地开发。

### 2. 配置环境变量

先复制根目录示例配置：

```bash
copy .env.example .env
```

至少检查这些关键项：

```env
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=please_change_me

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_API_KEY=
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
OPENROUTER_API_KEY=

EMBEDDING_PROVIDER=siliconflow
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_API_KEY=
SILICONFLOW_API_KEY=
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
```

配置约定如下：

- 后端优先读取 `backend/.env`，找不到时再回退到仓库根目录 `.env`。
- 仓库中提交的是 `.env.example` 基线，用来保证 GitHub 拉到服务器后基础配置一致。
- 真正的密钥、Token、密码必须只放在未追踪的 `.env` 文件里，不能提交到 Git。
- `frontend/.env.example` 故意不写死 `VITE_API_URL`；前端默认会按 LogicKG 的后端端口策略探测 API。

### 3. 一键启动前后端开发环境

在仓库根目录运行：

```bash
npm run dev
```

该命令会执行 `run.ps1`，自动完成以下工作：

- 缺少时创建后端虚拟环境
- 安装缺失的前后端依赖
- 为当前工作区选择安全可用的前后端端口
- 生成 `frontend/.env.local`，写入实际后端地址
- 同时启动 FastAPI 与 Vite

常见本地访问地址：

- 前端：`http://127.0.0.1:5173/` 或自动挑选的其他前端端口
- 后端 OpenAPI：`http://127.0.0.1:8000/docs` 或自动挑选的其他后端端口
- 健康检查：`http://127.0.0.1:<backend-port>/health`

### 4. 手动启动

后端：

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

如果后端不跑在默认端口，需要手动写 `frontend/.env.local`，例如：

```env
VITE_API_URL=http://127.0.0.1:8000
```

## 配置与部署约定

这是这次仓库整理后最重要的约定之一。

### Git 中应保留什么

- 保留根目录 `.env.example`
- 保留 `backend/.env.example`
- 保留 `frontend/.env.example`
- 保留不含隐私信息的默认配置、默认端口、默认 provider 名称、默认结构参数

### Git 中绝对不要保留什么

- 真正的 API Key
- 数据库真实密码
- 线上 Token、私有服务地址中的敏感参数
- 本机临时路径、缓存产物、运行产物

### 从 GitHub 部署到服务器时怎么做

推荐做法是：

1. 从仓库拉取当前 `main`。
2. 直接沿用仓库中的 `.env.example` 作为基础配置模板。
3. 只在服务器本地补充 `.env` 中的密钥、密码和环境特有值。
4. 如果前端和后端同域部署且通过反向代理转发，通常不必额外修改大部分默认项。

这样可以保证：

- 项目的基础配置与本地开发保持一致
- 新机器部署时不需要从头手改一套配置
- 隐私信息仍然不会进入 Git 历史

## 常用命令

仓库根目录：

```bash
npm run dev
docker compose up -d
```

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

PowerShell 启动脚本测试：

```bash
Invoke-Pester tests
```

## 典型工作流

### 论文导入

直接导入：

```bash
curl -X POST http://127.0.0.1:8000/ingest/path ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/data/mineru_output\"}"
```

走任务队列导入：

```bash
curl -X POST http://127.0.0.1:8000/tasks/ingest/path ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/data/mineru_output\"}"
```

### 教材导入

任务式教材导入：

```bash
curl -X POST http://127.0.0.1:8000/textbooks/ingest ^
  -H "Content-Type: application/json" ^
  -d "{\"path\":\"C:/books/book.md\",\"title\":\"Example Textbook\",\"authors\":[\"Author A\"],\"year\":2024}"
```

教材也支持通过 `/textbooks/upload/*` API 与导入中心页面上传。

### 图谱重建

全局 community 重建：

```bash
curl -X POST http://127.0.0.1:8000/tasks/rebuild/community ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

其他常用任务接口还包括：

- `/tasks/rebuild/paper`
- `/tasks/rebuild/faiss`
- `/tasks/rebuild/all`
- `/tasks/rebuild/fusion`
- `/tasks/rebuild/similarity`
- `/tasks/similarity/paper`

### 清理旧版 Discovery 残留

维护脚本：

```bash
cd backend
.\.venv\Scripts\python.exe scripts/cleanup_discovery.py
```

这只是维护脚本，不代表旧版 `discovery` 仍然是当前产品主流程。

## API 概览

当前 `backend/app/main.py` 挂载的主要路由有：

- `/health`
- `/ingest`
- `/rag`
- `/graph`
- `/tasks`
- `/papers`
- `/paper-edits`
- `/schema`
- `/collections`
- `/config-center`
- `/community`
- `/fusion`
- `/textbooks`

常用接口示例：

- `GET /health`
- `GET /graph/network`
- `GET /graph/paper/{paper_id}`
- `POST /ingest/path`
- `POST /tasks/ingest/path`
- `POST /tasks/rebuild/community`
- `GET /tasks`
- `GET /community/list`
- `GET /community/overview-graph`
- `GET /textbooks`
- `GET /textbooks/{textbook_id}/graph`
- `POST /rag/ask_v2`
- `POST /rag/ask_v2_stream`
- `GET /config-center/profile`
- `GET /config-center/catalog`
- `POST /config-center/assistant`
- `GET /schema/active`

完整接口请直接查看：

- `http://127.0.0.1:<backend-port>/docs`

## 配置中心说明

后端核心设置定义在 `backend/app/settings.py`，运行期配置覆盖主要由 `backend/app/ops_config_store.py` 管理。

目前配置中心主要覆盖：

- similarity 相关参数
- 运行并发配置
- provider 与 embedding 配置
- LLM worker pool 配置
- 基础设施相关设置
- 外部集成设置
- global community 设置

前端 API 解析逻辑会：

- 优先复用上次探测成功的后端地址
- 在 `VITE_API_URL` 未设置时探测当前主机
- 按主工作区约定优先尝试 `8000`、`8080`、`18000`、`8001`、`8002` 等端口

这也是为什么当前仓库可以在不提交真实前端环境变量的情况下，仍然保持较顺滑的默认启动体验。

## 当前范围与历史说明

当前主线的推荐使用方式是：

1. 导入论文或教材
2. 在总览 / 论文 / 教材图谱中查看结构
3. 使用 Ask 做图增强问答
4. 在运维页面管理任务、Schema 与配置

如果你在历史提交、旧文档或旧截图里看到 `discovery`、`proposition` 等术语，请把它们视为迁移历史，而不是当前主线使用说明。

## 提交前建议验证

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

PowerShell：

```bash
Invoke-Pester tests
```

## 相关文档

- [TECHNICAL_OVERVIEW.zh-CN.md](TECHNICAL_OVERVIEW.zh-CN.md)
- [AGENTS.md](AGENTS.md)
