# LogicKG

LogicKG 是一个面向科研论文的结构化知识图谱系统，核心目标是把论文文本转成可计算、可追溯、可问答的图谱资产。

它将 MinerU 产出的 Markdown 解析为图结构（如 `Paper / Chunk / ReferenceEntry / Proposition / CITES`），并结合向量检索（FAISS）和大模型能力，提供从导入、抽取、质检、图谱浏览到 GraphRAG 问答的一体化工作台。

---

## 1. 核心能力

- 结构化入库：论文、段落、引用、命题、关系等写入 Neo4j
- 证据可追溯：回答与边关系可回溯到原文片段（含 chunk 和行号）
- 双轨抽取：`Raw Pool` 保留候选，`Validated KG` 只写入通过门禁的数据
- 质量门禁：支持覆盖率、冲突率、逻辑步骤完整度等多维评估
- GraphRAG 问答：向量召回 + 图上下文 + LLM 生成
- Schema 可配置：前端可直接调规则与提示词版本
- 中英双界面：核心导航、面板、问答体验支持中英文切换

---

## 2. 技术栈

- 后端：FastAPI
- 前端：React + Vite + TypeScript
- 图数据库：Neo4j 5.x
- 向量检索：FAISS
- 模型接入：DeepSeek / OpenAI / OpenRouter / SiliconFlow（按配置）

---

## 3. 仓库结构（当前真实状态）

```text
.
├─ backend/                  # FastAPI 后端
│  ├─ app/                   # API、抽取、RAG、任务、图谱访问等
│  ├─ tests/                 # 后端测试
│  ├─ requirements.txt
│  ├─ runs/                  # 运行产物（忽略提交）
│  └─ storage/               # 数据产物（忽略提交）
├─ frontend/                 # React 前端
│  ├─ src/
│  ├─ tests/
│  └─ package.json
├─ docs/
│  └─ releases/
│     ├─ README.md
│     └─ 2026-02-20-round8-evidence-quote-and-p03-gate.md
├─ docker-compose.yml        # 本地 Neo4j 启动（可选）
├─ .env.example              # 根目录示例配置
├─ run.ps1                   # Windows 一键开发启动
└─ README.md
```

---

## 4. 快速开始

### 4.1 前置依赖

- Python 3.10+（推荐 3.11）
- Node.js 18+（推荐 20）
- Neo4j 5.x
- 至少一组可用模型密钥（LLM + Embedding）

### 4.2 配置环境变量

在仓库根目录创建 `.env`：

```bash
cp .env.example .env
```

最小示例：

```env
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your_deepseek_key

EMBEDDING_PROVIDER=siliconflow
EMBEDDING_MODEL=BAAI/bge-m3
SILICONFLOW_API_KEY=your_siliconflow_key
```

说明：

- 后端会优先读取 `backend/.env`，其次读取根目录 `.env`
- 抽取策略阈值（`phase1_*` / `phase2_*`）主要通过前端 Schema 页面管理

### 4.3 启动 Neo4j

方式 A（推荐）：本机已有 Neo4j Desktop / 服务

方式 B（Docker）：

```bash
docker compose up -d
```

### 4.4 启动项目

Windows（推荐）：

```powershell
.\run.ps1
```

手动启动（Linux/macOS 或通用）：

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

访问地址：

- 前端：`http://127.0.0.1:5173`
- 后端文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

---

## 5. 典型使用流程

1. 在前端「导入中心」或调用 `/ingest/path` 导入 MinerU Markdown
2. 在论文/图谱页面检查抽取结果与关系质量
3. 在 Ask 页面基于图谱进行问答与证据追溯
4. 在 Schema 页面调整规则与提示词，保存版本后重建验证

`/ingest/path` 示例：

```bash
curl -X POST 'http://127.0.0.1:8000/ingest/path' \
  -H 'Content-Type: application/json' \
  -d '{"path":"/data/mineru_output"}'
```

---

## 6. 配置与版本管理

- 抽取配置模板：`high_precision` / `balanced` / `high_recall`
- 常用接口：
  - `GET /schema/presets`
  - `POST /schema/presets/apply`
- 配置中心（运维页）可统一管理 discovery/similarity/schema 关键参数

建议：

- 为每次策略调整填写可识别的版本名称
- 重要调参后，对同一批论文做重建对比（覆盖率、冲突率、证据可追溯率）

---

## 7. 开发与验证命令

### 7.1 前端

```bash
cd frontend
npm run lint
npm run test
npm run build
```

### 7.2 后端

```bash
cd backend
pytest -q
```

当前基线（本仓库最近一次完整回归）：

- 前端：`lint/test/build` 全通过
- 后端：`343 passed`

---

## 8. 部署建议（生产）

推荐拓扑：

- Neo4j：Docker 或托管服务（不对公网直接暴露 7687）
- 后端：systemd 管理 Uvicorn，监听 `127.0.0.1:8000`
- 前端：Nginx 静态托管 + `/api` 反代后端

关键点：

- `.env` 只保存在服务器本地，权限建议 `600`
- `backend/storage/` 与 `backend/runs/` 做周期备份
- 上线前做一次最小冒烟：导入 -> 查询 -> Ask -> 证据追溯

---

## 9. 安全与提交规范

- 不提交 `.env`、`backend/storage/`、`backend/runs/`、`node_modules/`、`dist/`
- 推送前建议执行：

```bash
git status -sb
rg -n "ghp_|github_pat_|sk-|BEGIN .*PRIVATE KEY" -S .
```

---

## 10. 常见问题

- Neo4j 连接失败：检查 URI、账号密码、防火墙与端口占用
- Embedding 报错：确认 `EMBEDDING_PROVIDER` 与对应 API key 已配置
- 导入慢：先缩小导入目录做最小样本验证，再扩容跑批
- 前端显示异常：先跑 `npm run build` 与浏览器控制台检查

---

## 11. 发布说明

历史发布说明见：

- [docs/releases/README.md](docs/releases/README.md)
- [docs/releases/2026-02-20-round8-evidence-quote-and-p03-gate.md](docs/releases/2026-02-20-round8-evidence-quote-and-p03-gate.md)

---

## 12. License

如需开源分发，请补充 `LICENSE` 与 `CONTRIBUTING.md`。
