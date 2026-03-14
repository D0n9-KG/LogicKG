import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { apiGet, apiPost, apiPut } from '../api'
import { LOCALE_STORAGE_KEY, resolveInitialLocale, translate, useI18n } from '../i18n'
import SchemaPage from './SchemaPage'
import './config-center.css'

type BuiltinModuleTab = 'similarity' | 'schema' | 'runtime' | 'llm_workers' | 'providers'
type ModuleTab = BuiltinModuleTab | (string & {})
type PaperType = 'research' | 'review' | 'software' | 'theoretical' | 'case_study'

type SimilarityConfig = {
  group_clustering_method: 'agglomerative' | 'louvain' | 'hybrid'
  group_clustering_threshold: number
}

type RuntimeConfig = {
  ingest_llm_max_workers: number
  phase1_chunk_claim_max_workers: number
  phase1_grounding_max_workers: number
  phase2_conflict_max_workers: number
  ingest_pre_llm_max_workers: number
  faiss_embed_max_workers: number
  llm_global_max_concurrent: number
}

type LlmWorker = {
  id: string
  label: string
  base_url: string
  api_key: string
  model: string
  max_concurrent: number
  enabled: boolean
}

type LlmWorkersConfig = {
  items: LlmWorker[]
}

type LlmWorkerTestResponse = {
  reachable?: boolean
  error?: string | null
  worker?: {
    id?: string
    label?: string
  }
}

type WorkerTestState = {
  busy: boolean
  reachable: boolean | null
  error: string
}

type ProvidersConfig = {
  llm_provider: string
  llm_base_url: string
  llm_api_key: string
  llm_model: string
  deepseek_api_key: string
  openrouter_api_key: string
  openai_api_key: string
  embedding_provider: string
  embedding_base_url: string
  embedding_api_key: string
  embedding_model: string
  siliconflow_api_key: string
}

type ConfigModuleValues = {
  similarity: SimilarityConfig
  runtime: RuntimeConfig
  llm_workers: LlmWorkersConfig
  providers: ProvidersConfig
} & Record<string, Record<string, unknown>>

type ConfigProfile = {
  version: number
  updated_at?: string
  modules: ConfigModuleValues
}

type ConfigProfileResponse = {
  profile?: Partial<ConfigProfile>
}

type ConfigCatalogFieldOption = string | { value?: string | number | boolean; label?: string }

type ConfigCatalogField = {
  key?: string
  anchor?: string
  label?: string
  description?: string
  current_value?: unknown
  type?: string
  input_type?: string
  control?: string
  options?: ConfigCatalogFieldOption[]
  min?: number
  max?: number
  step?: number
  placeholder?: string
  secret?: boolean
  multiline?: boolean
}

type ConfigCatalogModule = {
  id?: string
  label?: string
  description?: string
  fields?: ConfigCatalogField[]
  rule_keys?: string[]
  prompt_keys?: string[]
}

type ConfigCatalogResponse = {
  modules?: ConfigCatalogModule[]
}

type SchemaSummary = {
  paper_type: PaperType
  version: number
  name?: string
}

type SchemaVersionsResponse = {
  versions?: Array<{ version?: number; name?: string }>
}

type AssistantSuggestion = {
  module: string
  key: string
  anchor: string
  suggested_value: string
  rationale: string
  focus_key?: string | null
  caution?: string | null
}

type AssistantResponse = {
  used_llm?: boolean
  suggestions?: AssistantSuggestion[]
}

type AssistantTurn = {
  id: string
  created_at: string
  goal: string
  used_llm: boolean
  suggestions: AssistantSuggestion[]
  error?: string
}

const CHAT_TURNS_STORAGE_KEY = 'logickg.config_center.assistant_turns.v1'
const CHAT_GOAL_STORAGE_KEY = 'logickg.config_center.assistant_goal.v1'
const ASSISTANT_WIDTH_STORAGE_KEY = 'logickg.config_center.assistant_width.v1'
const MAX_CHAT_TURNS = 24
const DEFAULT_ASSISTANT_WIDTH = 460
const DEFAULT_SCHEMA_ASSISTANT_WIDTH = 560
const MIN_ASSISTANT_WIDTH = 360
const MIN_SCHEMA_ASSISTANT_WIDTH = 460

type ModuleItem = {
  id: ModuleTab
  label: { zh: string; en: string }
  desc: { zh: string; en: string }
}

type GenericFieldKind = 'string' | 'password' | 'boolean' | 'number' | 'select' | 'textarea'

type GenericFieldViewModel = {
  key: string
  anchor: string
  label: string
  description: string
  placeholder: string
  kind: GenericFieldKind
  value: unknown
  options: Array<{ value: string; label: string }>
  min?: number
  max?: number
  step?: number
}

type LocalizedCopy = {
  labelZh: string
  labelEn?: string
  descZh?: string
  descEn?: string
}

const MODULE_LOCALIZATION: Record<string, LocalizedCopy> = {
  similarity: {
    labelZh: '相似性',
    labelEn: 'Similarity',
    descZh: '相似性聚类行为。',
    descEn: 'Similarity clustering behavior.',
  },
  schema: {
    labelZh: '抽取策略',
    labelEn: 'Extraction Policy',
    descZh: '抽取规则与提示词控制。',
    descEn: 'Schema rules and prompt controls.',
  },
  runtime: {
    labelZh: '运行并发',
    labelEn: 'Runtime Concurrency',
    descZh: '单篇抽取、预处理与全局限流设置。',
    descEn: 'Per-paper extraction, preprocessing, and global limiter settings.',
  },
  llm_workers: {
    labelZh: 'LLM 工作器',
    labelEn: 'LLM Workers',
    descZh: '为不同来源的大模型配置独立工作器，并按整篇论文分配任务。',
    descEn: 'Bind whole-paper extraction jobs to independently configured LLM gateways.',
  },
  providers: {
    labelZh: '模型与向量',
    labelEn: 'LLM & Embeddings',
    descZh: '向量服务与嵌入模型设置。',
    descEn: 'Embedding service and model settings.',
  },
  infra: {
    labelZh: '基础设施',
    labelEn: 'Infrastructure',
    descZh: '管理图数据库、存储与教材执行环境。核心连接项建议在后端重启后再观察。',
    descEn: 'Graph database, storage, and textbook execution settings. Core connection changes are safest after a backend restart.',
  },
  integrations: {
    labelZh: '外部集成',
    labelEn: 'External Integrations',
    descZh: '管理 Crossref 等外部服务接入信息。环境变量仍会覆盖这里保存的值。',
    descEn: 'Crossref and other external service identifiers. Environment variables still override saved values.',
  },
  community: {
    labelZh: '全局社区',
    labelEn: 'Global Community',
    descZh: '管理全局社区聚类的规模上限与社区树参数。较大改动建议配合手动重建。',
    descEn: 'Global community clustering limits and TreeComm parameters. Large changes are best paired with a manual community rebuild.',
  },
}

const FIELD_LOCALIZATION: Record<string, LocalizedCopy> = {
  'similarity.group_clustering_method': {
    labelZh: '相似性聚类方法',
    labelEn: 'group_clustering_method',
    descZh: '决定相似性聚类在重建时如何形成分组。',
  },
  'similarity.group_clustering_threshold': {
    labelZh: '相似性分组阈值',
    labelEn: 'group_clustering_threshold',
    descZh: '阈值越高，聚类越紧、越保守。',
  },
  'runtime.ingest_llm_max_workers': { labelZh: '论文级并发', labelEn: 'ingest_llm_max_workers' },
  'runtime.phase1_chunk_claim_max_workers': { labelZh: '单篇要点并发', labelEn: 'phase1_chunk_claim_max_workers' },
  'runtime.phase1_grounding_max_workers': { labelZh: '证据复核并发', labelEn: 'phase1_grounding_max_workers' },
  'runtime.phase2_conflict_max_workers': { labelZh: '冲突裁决并发', labelEn: 'phase2_conflict_max_workers' },
  'runtime.ingest_pre_llm_max_workers': { labelZh: '预处理并发', labelEn: 'ingest_pre_llm_max_workers' },
  'runtime.faiss_embed_max_workers': { labelZh: '向量索引嵌入并发', labelEn: 'faiss_embed_max_workers' },
  'runtime.llm_global_max_concurrent': { labelZh: '大模型全局并发上限', labelEn: 'llm_global_max_concurrent' },
  'schema.rules_json': { labelZh: '规则 JSON', labelEn: 'schema.rules_json' },
  'schema.prompts_json': { labelZh: '提示词 JSON', labelEn: 'schema.prompts_json' },
  'providers.llm_provider': { labelZh: '大模型提供方', descZh: '选择抽取与审核任务默认使用的大模型服务。' },
  'providers.llm_base_url': { labelZh: '大模型服务基础地址', descZh: '如需走代理或兼容网关，可在这里覆盖默认地址。' },
  'providers.llm_api_key': { labelZh: '大模型接口密钥', descZh: '默认大模型服务的接口密钥。若留空，会回退到提供方专用密钥。' },
  'providers.llm_model': { labelZh: '大模型默认模型', descZh: '抽取、审核等流程默认使用的模型标识。' },
  'providers.deepseek_api_key': { labelZh: 'DeepSeek 接口密钥', descZh: '当大模型提供方为 DeepSeek 时使用的密钥。' },
  'providers.openrouter_api_key': { labelZh: 'OpenRouter 接口密钥', descZh: '当大模型提供方为 OpenRouter 时使用的密钥。' },
  'providers.openai_api_key': { labelZh: 'OpenAI 接口密钥', descZh: 'OpenAI 及兼容提供方的回退密钥。' },
  'providers.embedding_provider': { labelZh: '向量提供方', descZh: '选择向量检索、向量索引和聚类使用的向量服务。' },
  'providers.embedding_base_url': { labelZh: '向量服务地址', descZh: '如需走代理或自建兼容服务，可在这里覆盖默认向量地址。' },
  'providers.embedding_api_key': { labelZh: '向量接口密钥', descZh: '向量服务使用的接口密钥。' },
  'providers.embedding_model': { labelZh: '向量默认模型', descZh: '向量索引与检索默认使用的模型标识。' },
  'providers.siliconflow_api_key': { labelZh: 'SiliconFlow 接口密钥', descZh: '当向量提供方为 SiliconFlow 时使用的密钥。' },
  'infra.neo4j_uri': { labelZh: 'Neo4j 地址', descZh: '图数据库的 Bolt 连接地址。' },
  'infra.neo4j_user': { labelZh: 'Neo4j 用户名', descZh: '图数据库登录用户名。' },
  'infra.neo4j_password': { labelZh: 'Neo4j 密码', descZh: '图数据库登录密码。' },
  'infra.pageindex_enabled': { labelZh: '页索引开关', descZh: '控制 PDF 页索引相关能力是否启用。' },
  'infra.pageindex_index_dir': { labelZh: '页索引目录', descZh: '页索引生成与读取索引文件的目录。' },
  'infra.data_root': { labelZh: '数据根目录', descZh: '相对路径数据的统一根目录。' },
  'infra.storage_dir': { labelZh: '存储目录', descZh: '论文、派生产物与运维配置的主存储目录。' },
  'infra.autoyoutu_dir': { labelZh: 'AutoYoutu 目录', descZh: 'AutoYoutu 项目的本地路径。' },
  'infra.youtu_ssh_host': { labelZh: '远程 Youtu 主机', descZh: '远程执行 Youtu 时使用的 SSH 主机。' },
  'infra.youtu_ssh_user': { labelZh: '远程 Youtu 用户', descZh: '远程执行 Youtu 时使用的 SSH 用户名。' },
  'infra.youtu_ssh_key_path': { labelZh: '远程 Youtu 密钥路径', descZh: '远程执行 Youtu 时使用的 SSH 私钥路径。' },
  'infra.textbook_youtu_schema': { labelZh: '教材 Youtu 规则', descZh: '教材解析默认使用的 Youtu 规则。' },
  'infra.textbook_chapter_max_tokens': { labelZh: '教材章节分块上限', descZh: '教材章节切块时的软 token 上限。' },
  'integrations.crossref_mailto': { labelZh: 'Crossref 联系邮箱', descZh: 'Crossref polite pool 请求使用的联系邮箱。' },
  'integrations.crossref_user_agent': { labelZh: 'Crossref 标识', descZh: 'Crossref 请求里附带的 User-Agent 前缀。' },
  'community.global_community_version': { labelZh: '全局社区版本', descZh: '全局社区索引使用的版本标签。' },
  'community.global_community_max_nodes': { labelZh: '全局社区节点上限', descZh: '投影到全局社区图中的最大节点数。' },
  'community.global_community_max_edges': { labelZh: '全局社区边上限', descZh: '投影到全局社区图中的最大边数。' },
  'community.global_community_top_keywords': { labelZh: '社区关键词数量', descZh: '每个全局社区保留的关键词数量。' },
  'community.global_community_tree_comm_embedding_model': { labelZh: '社区树向量模型', descZh: '社区树构建使用的向量模型。' },
  'community.global_community_tree_comm_struct_weight': { labelZh: '社区树结构权重', descZh: '社区树中结构信息所占权重，0 表示仅语义，1 表示仅结构。' },
}

type TranslateFn = (zh: string, en: string) => string

function localizedModuleLabel(moduleId: string, fallbackLabel: string, t: TranslateFn) {
  const copy = MODULE_LOCALIZATION[moduleId]
  if (copy) return t(copy.labelZh, copy.labelEn || fallbackLabel || humanizeToken(moduleId))
  return fallbackLabel || humanizeToken(moduleId)
}

function localizedModuleDescription(moduleId: string, fallbackDesc: string, t: TranslateFn) {
  const copy = MODULE_LOCALIZATION[moduleId]
  if (copy?.descZh) return t(copy.descZh, copy.descEn || fallbackDesc || copy.descZh)
  return fallbackDesc
}

function localizedFieldLabel(anchor: string, fallbackLabel: string, t: TranslateFn) {
  const copy = FIELD_LOCALIZATION[anchor]
  if (copy) return t(copy.labelZh, copy.labelEn || fallbackLabel || anchor)
  return fallbackLabel
}

function localizedFieldDescription(anchor: string, fallbackDescription: string, t: TranslateFn) {
  const copy = FIELD_LOCALIZATION[anchor]
  if (copy?.descZh) return t(copy.descZh, copy.descEn || fallbackDescription || copy.descZh)
  return fallbackDescription
}

const MODULE_ITEMS: ModuleItem[] = [
  {
    id: 'similarity',
    label: { zh: '相似性', en: 'Similarity' },
    desc: { zh: '相似性聚类行为。', en: 'Similarity clustering behavior.' },
  },
  {
    id: 'schema',
    label: { zh: '抽取策略', en: 'Extraction Policy' },
    desc: { zh: '抽取规则与提示词控制。', en: 'Schema rules and prompt controls.' },
  },
  {
    id: 'runtime',
    label: { zh: '运行并发', en: 'Runtime Concurrency' },
    desc: { zh: '大模型、抽取与向量索引的后端并发与限流。', en: 'Backend LLM, extraction, and FAISS worker limits.' },
  },
  {
    id: 'llm_workers',
    label: { zh: 'LLM 工作器', en: 'LLM Workers' },
    desc: { zh: '按整篇论文绑定到不同来源的大模型工作器。', en: 'Bind whole-paper jobs to independently configured LLM gateways.' },
  },
  {
    id: 'providers',
    label: { zh: '模型与向量', en: 'LLM & Embeddings' },
    desc: { zh: '默认/回退 LLM 与向量服务设置。', en: 'Default/fallback LLM and embedding settings.' },
  },
]

const SCHEMA_PAPER_TYPES: Array<{ value: PaperType; zh: string; en: string }> = [
  { value: 'research', zh: '研究论文', en: 'Research' },
  { value: 'review', zh: '综述论文', en: 'Review' },
  { value: 'software', zh: '软件论文', en: 'Software' },
  { value: 'theoretical', zh: '理论论文', en: 'Theoretical' },
  { value: 'case_study', zh: '案例论文', en: 'Case Study' },
]

const RUNTIME_FIELDS: Array<{
  key: keyof RuntimeConfig
  zh: string
  en: string
  min: number
  max: number
  helpZh: string
  helpEn: string
}> = [
  {
    key: 'phase1_chunk_claim_max_workers',
    zh: '单篇要点并发',
    en: 'phase1_chunk_claim_max_workers',
    min: 1,
    max: 8,
    helpZh: '单篇论文内部，要点抽取批次的参考并发数。当全局空闲连接充足时，系统可自动上调（最高 6）。',
    helpEn: 'Reference concurrency for claim-batch workers inside one paper. The system may raise this automatically when global LLM slots are idle (hard cap 6).',
  },
  {
    key: 'phase1_grounding_max_workers',
    zh: '证据复核并发',
    en: 'phase1_grounding_max_workers',
    min: 1,
    max: 6,
    helpZh: 'Claim 证据复核阶段的参考并发数，全局空闲时可自动上调。此值同时参与计算"有效论文并发"（分母 = 要点/复核/冲突三者最大值）。',
    helpEn: 'Reference concurrency for claim grounding. Also used as the per-paper fan-out denominator (max of claim/grounding/conflict workers) when deriving effective paper concurrency.',
  },
  {
    key: 'phase2_conflict_max_workers',
    zh: '冲突裁决并发',
    en: 'phase2_conflict_max_workers',
    min: 1,
    max: 6,
    helpZh: '语义冲突裁决阶段的参考并发数，全局空闲时可自动上调。同上，也参与"有效论文并发"分母计算。',
    helpEn: 'Reference concurrency for conflict judging. Also factors into the per-paper fan-out denominator.',
  },
  {
    key: 'ingest_pre_llm_max_workers',
    zh: '预处理并发',
    en: 'ingest_pre_llm_max_workers',
    min: 1,
    max: 8,
    helpZh: '参考文献补抽、citation event 恢复等 LLM 前置步骤的并发线程数。不参与论文级并发计算，独立于主抽取流程。',
    helpEn: 'Parallel threads for pre-LLM steps (reference recovery, citation events). Independent from main extraction concurrency.',
  },
  {
    key: 'faiss_embed_max_workers',
    zh: '向量索引嵌入并发',
    en: 'faiss_embed_max_workers',
    min: 1,
    max: 6,
    helpZh: '重建全局 FAISS 向量索引时，同时调用向量服务生成嵌入的线程数。仅在索引重建任务中生效，不影响抽取速度。',
    helpEn: 'Parallel threads calling the embedding service when rebuilding the global FAISS index. Only active during index rebuild, not during paper extraction.',
  },
  {
    key: 'llm_global_max_concurrent',
    zh: '大模型全局并发上限',
    en: 'llm_global_max_concurrent',
    min: 1,
    max: 256,
    helpZh: '后端进程级全局信号量，限制同时在途的 LLM HTTP 请求总数。⚠ 该值在后端启动时初始化一次，修改后须重启后端才能生效。有效论文并发 = floor(此值 ÷ 内部并发分母)。',
    helpEn: 'Process-wide semaphore capping total in-flight LLM requests. ⚠ Initialized once at startup — backend restart required after changes. Effective paper concurrency = floor(this value ÷ per-paper fan-out).',
  },
]

function asBoolean(value: unknown, fallback: boolean) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const text = value.trim().toLowerCase()
    if (text === 'true' || text === '1' || text === 'on' || text === 'yes') return true
    if (text === 'false' || text === '0' || text === 'off' || text === 'no') return false
  }
  return fallback
}

function asNumber(value: unknown, fallback: number) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return n
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeLooseModule(raw: unknown): Record<string, unknown> {
  if (!isRecord(raw)) return {}
  return { ...raw }
}

function normalizeLlmWorkersConfig(raw: unknown): LlmWorkersConfig {
  const itemsRaw = isRecord(raw) && Array.isArray(raw.items) ? raw.items : []
  return {
    items: itemsRaw.map((item, index) => {
      const row = isRecord(item) ? item : {}
      const fallbackId = `worker-${index + 1}`
      return {
        id: String(row.id ?? '').trim() || fallbackId,
        label: String(row.label ?? '').trim(),
        base_url: String(row.base_url ?? '').trim(),
        api_key: String(row.api_key ?? '').trim(),
        model: String(row.model ?? '').trim(),
        max_concurrent: Math.max(1, Math.min(128, asNumber(row.max_concurrent, 32))),
        enabled: asBoolean(row.enabled, true),
      }
    }),
  }
}

function normalizeProvidersConfig(raw: unknown): ProvidersConfig {
  const row = isRecord(raw) ? raw : {}
  return {
    llm_provider: String(row.llm_provider ?? 'deepseek').trim() || 'deepseek',
    llm_base_url: String(row.llm_base_url ?? '').trim(),
    llm_api_key: String(row.llm_api_key ?? '').trim(),
    llm_model: String(row.llm_model ?? 'deepseek-chat').trim() || 'deepseek-chat',
    deepseek_api_key: String(row.deepseek_api_key ?? '').trim(),
    openrouter_api_key: String(row.openrouter_api_key ?? '').trim(),
    openai_api_key: String(row.openai_api_key ?? '').trim(),
    embedding_provider: String(row.embedding_provider ?? '').trim(),
    embedding_base_url: String(row.embedding_base_url ?? '').trim(),
    embedding_api_key: String(row.embedding_api_key ?? '').trim(),
    embedding_model: String(row.embedding_model ?? 'text-embedding-3-small').trim() || 'text-embedding-3-small',
    siliconflow_api_key: String(row.siliconflow_api_key ?? '').trim(),
  }
}

function isBuiltinModule(moduleId: string): moduleId is BuiltinModuleTab {
  return moduleId === 'similarity' || moduleId === 'runtime' || moduleId === 'schema' || moduleId === 'llm_workers' || moduleId === 'providers'
}

function humanizeToken(text: string) {
  if (!text) return ''
  return text
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function normalizeFieldOptions(raw: unknown): Array<{ value: string; label: string }> {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') {
        const value = String(item)
        return value ? { value, label: value } : null
      }
      if (!isRecord(item)) return null
      const value = String(item.value ?? '').trim()
      if (!value) return null
      const label = String(item.label ?? value).trim() || value
      return { value, label }
    })
    .filter((item): item is { value: string; label: string } => Boolean(item))
}

function inferGenericFieldKind(field: ConfigCatalogField | undefined, key: string, value: unknown): GenericFieldKind {
  const typeHint = String(field?.input_type ?? field?.type ?? field?.control ?? '').trim().toLowerCase()
  const options = normalizeFieldOptions(field?.options)
  if (typeHint === 'textarea' || typeHint === 'multiline' || typeHint === 'json' || field?.multiline) return 'textarea'
  if (typeHint === 'password' || typeHint === 'secret' || field?.secret || /(password|secret|token|api[_-]?key)$/i.test(key)) {
    return 'password'
  }
  if (options.length > 0 && (typeHint === '' || typeHint === 'select' || typeHint === 'enum' || typeHint === 'choice')) return 'select'
  if (typeHint === 'boolean' || typeHint === 'bool' || typeHint === 'checkbox' || typeHint === 'switch' || typeof value === 'boolean') {
    return 'boolean'
  }
  if (typeHint === 'number' || typeHint === 'integer' || typeHint === 'float' || typeHint === 'int' || typeof value === 'number') {
    return 'number'
  }
  return 'string'
}

function coerceGenericFieldValue(field: ConfigCatalogField | undefined, key: string, rawValue: string, fallback: unknown) {
  const kind = inferGenericFieldKind(field, key, fallback)
  if (kind === 'boolean') return asBoolean(rawValue, Boolean(fallback))
  if (kind === 'number') return asNumber(rawValue, typeof fallback === 'number' ? fallback : 0)
  return rawValue
}

function buildGenericFieldModels(moduleId: string, moduleValues: Record<string, unknown>, moduleCatalog: ConfigCatalogModule | null): GenericFieldViewModel[] {
  const result: GenericFieldViewModel[] = []
  const seen = new Set<string>()
  const catalogFields = Array.isArray(moduleCatalog?.fields) ? moduleCatalog?.fields ?? [] : []

  for (const field of catalogFields) {
    const key = String(field?.key ?? '').trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    const currentValue = key in moduleValues ? moduleValues[key] : field?.current_value
    result.push({
      key,
      anchor: String(field?.anchor ?? `${moduleId}.${key}`),
      label: String(field?.label ?? key).trim() || key,
      description: String(field?.description ?? '').trim(),
      placeholder: String(field?.placeholder ?? '').trim(),
      kind: inferGenericFieldKind(field, key, currentValue),
      value: currentValue,
      options: normalizeFieldOptions(field?.options),
      min: typeof field?.min === 'number' ? field.min : undefined,
      max: typeof field?.max === 'number' ? field.max : undefined,
      step: typeof field?.step === 'number' ? field.step : undefined,
    })
  }

  for (const key of Object.keys(moduleValues)) {
    if (seen.has(key)) continue
    const value = moduleValues[key]
    result.push({
      key,
      anchor: `${moduleId}.${key}`,
      label: key,
      description: humanizeToken(key),
      placeholder: '',
      kind: inferGenericFieldKind(undefined, key, value),
      value,
      options: [],
    })
  }

  return result
}

function parseError(error: unknown) {
  const raw = String((error as { message?: unknown } | null)?.message ?? error ?? '').trim()
  if (!raw) return 'Unknown error'
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    if (typeof parsed?.detail === 'string' && parsed.detail.trim()) return parsed.detail
  } catch {
    // ignore parse errors and fall back to original text
  }
  return raw
}

function makeTurnId() {
  const rnd = Math.random().toString(36).slice(2, 8)
  return `turn_${Date.now()}_${rnd}`
}

function createEmptyLlmWorker(index: number): LlmWorker {
  return {
    id: `worker-${index + 1}`,
    label: '',
    base_url: '',
    api_key: '',
    model: '',
    max_concurrent: 3,
    enabled: true,
  }
}

function workerTestKey(worker: Pick<LlmWorker, 'id'>, index: number) {
  return `${String(worker.id || '').trim() || 'worker'}:${index}`
}

function isSupportedAssistantSuggestion(raw: { module?: unknown; anchor?: unknown; key?: unknown }) {
  const module = String(raw.module ?? '').trim()
  const anchor = String(raw.anchor ?? '').trim()
  const key = String(raw.key ?? '').trim()
  if (!module || !anchor || !key) return false
  if (module === 'discovery') return false
  return anchor.startsWith(`${module}.`)
}

function normalizeSuggestion(raw: unknown): AssistantSuggestion | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  if (!isSupportedAssistantSuggestion(row)) return null
  return {
    module: String(row.module ?? ''),
    key: String(row.key ?? ''),
    anchor: String(row.anchor ?? ''),
    suggested_value: String(row.suggested_value ?? ''),
    rationale: String(row.rationale ?? ''),
    focus_key: row.focus_key == null ? null : String(row.focus_key),
    caution: row.caution == null ? null : String(row.caution),
  }
}

function normalizeTurn(raw: unknown): AssistantTurn | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  const id = String(row.id ?? '').trim()
  const goal = String(row.goal ?? '').trim()
  const createdAt = String(row.created_at ?? '').trim()
  if (!id || !goal || !createdAt) return null

  const suggestionsRaw = Array.isArray(row.suggestions) ? row.suggestions : []
  const suggestions = suggestionsRaw.map(normalizeSuggestion).filter((item): item is AssistantSuggestion => Boolean(item))
  const error = row.error == null ? undefined : String(row.error)
  if (!suggestions.length && !error) return null

  return {
    id,
    created_at: createdAt,
    goal,
    used_llm: Boolean(row.used_llm),
    suggestions,
    error,
  }
}

function loadStoredTurns(): AssistantTurn[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(CHAT_TURNS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeTurn).filter((item): item is AssistantTurn => Boolean(item)).slice(0, MAX_CHAT_TURNS)
  } catch {
    return []
  }
}

function defaultAssistantGoal() {
  if (typeof window === 'undefined') {
    return translate('zh-CN', '提高抽取精度，同时减少噪声要点并保持召回稳定。', 'Make extraction stricter and reduce noisy claims while keeping recall stable.')
  }
  const locale = resolveInitialLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY), window.navigator.language)
  return translate(locale, '提高抽取精度，同时减少噪声要点并保持召回稳定。', 'Make extraction stricter and reduce noisy claims while keeping recall stable.')
}

function loadStoredGoal() {
  if (typeof window === 'undefined') return defaultAssistantGoal()
  const raw = window.localStorage.getItem(CHAT_GOAL_STORAGE_KEY)
  const goal = String(raw ?? '').trim()
  return goal || defaultAssistantGoal()
}

function loadStoredAssistantWidth(): number | null {
  if (typeof window === 'undefined') return null
  const raw = window.localStorage.getItem(ASSISTANT_WIDTH_STORAGE_KEY)
  if (raw == null) return null
  const width = Number(raw)
  if (!Number.isFinite(width)) return null
  if (width < 280 || width > 900) return null
  return Math.round(width)
}

function normalizeProfile(raw: Partial<ConfigProfile> | null | undefined): ConfigProfile {
  const modulesRaw = isRecord(raw?.modules) ? raw.modules : {}
  const similarityRaw = raw?.modules?.similarity as Partial<SimilarityConfig> | undefined
  const runtimeRaw = raw?.modules?.runtime as Partial<RuntimeConfig> | undefined
  const llmWorkersRaw = raw?.modules?.llm_workers
  const modules = {
    similarity: {
      group_clustering_method: (String(
        similarityRaw?.group_clustering_method ?? 'hybrid',
      ) as SimilarityConfig['group_clustering_method']) ?? 'hybrid',
      group_clustering_threshold: Math.max(0, Math.min(1, asNumber(similarityRaw?.group_clustering_threshold, 0.85))),
    },
    runtime: {
      ingest_llm_max_workers: Math.max(1, Math.min(32, asNumber(runtimeRaw?.ingest_llm_max_workers, 5))),
      phase1_chunk_claim_max_workers: Math.max(1, Math.min(8, asNumber(runtimeRaw?.phase1_chunk_claim_max_workers, 4))),
      phase1_grounding_max_workers: Math.max(1, Math.min(6, asNumber(runtimeRaw?.phase1_grounding_max_workers, 3))),
      phase2_conflict_max_workers: Math.max(1, Math.min(6, asNumber(runtimeRaw?.phase2_conflict_max_workers, 3))),
      ingest_pre_llm_max_workers: Math.max(1, Math.min(8, asNumber(runtimeRaw?.ingest_pre_llm_max_workers, 6))),
      faiss_embed_max_workers: Math.max(1, Math.min(6, asNumber(runtimeRaw?.faiss_embed_max_workers, 4))),
      llm_global_max_concurrent: Math.max(1, Math.min(256, asNumber(runtimeRaw?.llm_global_max_concurrent, 32))),
    },
    llm_workers: normalizeLlmWorkersConfig(llmWorkersRaw),
    providers: normalizeProvidersConfig(raw?.modules?.providers),
  } as ConfigModuleValues

  for (const [moduleId, moduleValue] of Object.entries(modulesRaw)) {
    if (moduleId === 'similarity' || moduleId === 'runtime' || moduleId === 'llm_workers' || moduleId === 'providers') continue
    modules[moduleId] = normalizeLooseModule(moduleValue)
  }

  return {
    version: asNumber(raw?.version, 1),
    updated_at: String(raw?.updated_at ?? ''),
    modules,
  }
}

function fallbackCatalog(): ConfigCatalogResponse {
  return {
    modules: [
      { id: 'similarity', label: 'Similarity', fields: [] },
      { id: 'schema', label: 'Extraction Policy', fields: [], rule_keys: [], prompt_keys: [] },
      { id: 'runtime', label: 'Runtime Concurrency', fields: [] },
      { id: 'llm_workers', label: 'LLM Workers', fields: [] },
      { id: 'providers', label: 'LLM & Embeddings', fields: [] },
    ],
  }
}

export default function ConfigCenterPage() {
  const { locale, t } = useI18n()
  const [active, setActive] = useState<ModuleTab>('similarity')
  const [profile, setProfile] = useState<ConfigProfile>(() => normalizeProfile(null))
  const [catalog, setCatalog] = useState<ConfigCatalogResponse>(() => fallbackCatalog())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [warning, setWarning] = useState('')
  const [info, setInfo] = useState('')
  const [flashAnchor, setFlashAnchor] = useState('')
  const [jumpNonce, setJumpNonce] = useState(0)
  const [schemaJumpTarget, setSchemaJumpTarget] = useState<string | null>(null)
  const [schemaJumpFocusKey, setSchemaJumpFocusKey] = useState<string | null>(null)
  const [goal, setGoal] = useState(() => loadStoredGoal())
  const [assistantBusy, setAssistantBusy] = useState(false)
  const [assistantTurns, setAssistantTurns] = useState<AssistantTurn[]>(() => loadStoredTurns())
  const [showSchemaKeyList, setShowSchemaKeyList] = useState(false)
  const [schemaPaperType, setSchemaPaperType] = useState<PaperType>('research')
  const [schemaSummary, setSchemaSummary] = useState<SchemaSummary | null>(null)
  const [schemaVersions, setSchemaVersions] = useState<Array<{ version: number; name?: string }>>([])
  const [schemaVersionLoading, setSchemaVersionLoading] = useState(false)
  const [schemaVersionBusy, setSchemaVersionBusy] = useState(false)
  const [schemaActivateVersion, setSchemaActivateVersion] = useState('')
  const [assistantWidth, setAssistantWidth] = useState<number | null>(() => loadStoredAssistantWidth())
  const [isResizingAssistant, setIsResizingAssistant] = useState(false)
  const [workerTestStates, setWorkerTestStates] = useState<Record<string, WorkerTestState>>({})
  const layoutRef = useRef<HTMLDivElement | null>(null)
  const resizeStartRef = useRef<{ startX: number; startWidth: number } | null>(null)

  const refreshAll = useCallback(async () => {
    setLoading(true)
    setError('')
    setWarning('')
    try {
      const [profileRes, catalogRes] = await Promise.allSettled([
        apiGet<ConfigProfileResponse>('/config-center/profile'),
        apiGet<ConfigCatalogResponse>('/config-center/catalog'),
      ])

      if (profileRes.status !== 'fulfilled') throw profileRes.reason
      setProfile(normalizeProfile(profileRes.value.profile))

      if (catalogRes.status === 'fulfilled') {
        setCatalog(catalogRes.value ?? fallbackCatalog())
      } else {
        setCatalog(fallbackCatalog())
        setWarning(
          t(
            '当前后端未提供 Catalog 接口，核心配置编辑仍可使用。',
            'Catalog endpoint is unavailable on the connected backend. Core config editing still works.',
          ),
        )
      }
    } catch (cause: unknown) {
      setError(parseError(cause))
    } finally {
      setLoading(false)
    }
  }, [t])

  const refreshSchemaOverview = useCallback(async (paperType: PaperType) => {
    setSchemaVersionLoading(true)
    try {
      const [activeRes, versionsRes] = await Promise.all([
        apiGet<{ schema: SchemaSummary }>(`/schema/active?paper_type=${encodeURIComponent(paperType)}`),
        apiGet<SchemaVersionsResponse>(`/schema/versions?paper_type=${encodeURIComponent(paperType)}`),
      ])
      setSchemaSummary(activeRes.schema ?? null)
      setSchemaVersions(
        (versionsRes.versions ?? []).map((row) => ({
          version: asNumber(row.version, 1),
          name: String(row.name ?? '').trim() || undefined,
        })),
      )
      setSchemaActivateVersion('')
    } catch (cause: unknown) {
      setError(parseError(cause))
    } finally {
      setSchemaVersionLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (active !== 'schema') return
    void refreshSchemaOverview(schemaPaperType)
  }, [active, schemaPaperType, refreshSchemaOverview])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(CHAT_TURNS_STORAGE_KEY, JSON.stringify(assistantTurns.slice(0, MAX_CHAT_TURNS)))
    } catch {
      // ignore persistence failures
    }
  }, [assistantTurns])

  const enabledWorkerPaperCapacity = profile.modules.llm_workers.items.reduce(
    (sum, worker) => sum + (worker.enabled ? Math.max(1, Math.min(128, Number(worker.max_concurrent || 1))) : 0),
    0,
  )
  const estimatedPaperFanout = Math.max(
    1,
    Math.max(1, Math.min(8, Number(profile.modules.runtime.phase1_chunk_claim_max_workers || 1))),
    Math.max(1, Math.min(6, Number(profile.modules.runtime.phase1_grounding_max_workers || 1))),
    Math.max(1, Math.min(6, Number(profile.modules.runtime.phase2_conflict_max_workers || 1))),
  )
  const routableWorkerPaperSlots = profile.modules.llm_workers.items.reduce(
    (sum, worker) => {
      if (!worker.enabled || !worker.base_url.trim() || !worker.api_key.trim()) return sum
      const workerCapacity = Math.max(1, Math.min(128, Number(worker.max_concurrent || 1)))
      return sum + Math.max(1, Math.ceil(workerCapacity / estimatedPaperFanout))
    },
    0,
  )
  const effectiveIngestPaperConcurrency =
    routableWorkerPaperSlots > 0
      ? Math.max(
          1,
          Math.min(
            256,
            routableWorkerPaperSlots,
            Math.max(1, Math.floor(profile.modules.runtime.llm_global_max_concurrent / estimatedPaperFanout)),
          ),
        )
      : Math.max(
          1,
          Math.min(
            256,
            Number(profile.modules.runtime.ingest_llm_max_workers || 1),
            Math.max(1, Math.floor(profile.modules.runtime.llm_global_max_concurrent / estimatedPaperFanout)),
          ),
        )

  useEffect(() => {
    const validKeys = new Set(profile.modules.llm_workers.items.map((worker, index) => workerTestKey(worker, index)))
    setWorkerTestStates((prev) => {
      const next = Object.fromEntries(Object.entries(prev).filter(([key]) => validKeys.has(key)))
      return Object.keys(next).length === Object.keys(prev).length ? prev : next
    })
  }, [profile.modules.llm_workers.items])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(CHAT_GOAL_STORAGE_KEY, goal)
    } catch {
      // ignore persistence failures
    }
  }, [goal])

  useEffect(() => {
    if (typeof window === 'undefined' || assistantWidth == null) return
    try {
      window.localStorage.setItem(ASSISTANT_WIDTH_STORAGE_KEY, String(assistantWidth))
    } catch {
      // ignore persistence failures
    }
  }, [assistantWidth])

  const assistantMinWidth = active === 'schema' ? MIN_SCHEMA_ASSISTANT_WIDTH : MIN_ASSISTANT_WIDTH
  const assistantDefaultWidth = active === 'schema' ? DEFAULT_SCHEMA_ASSISTANT_WIDTH : DEFAULT_ASSISTANT_WIDTH
  const effectiveAssistantWidth = Math.max(assistantMinWidth, assistantWidth ?? assistantDefaultWidth)

  const clampAssistantWidth = useCallback(
    (rawWidth: number) => {
      const min = assistantMinWidth
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? (typeof window !== 'undefined' ? window.innerWidth : 1600)
      const max = Math.min(780, Math.max(min + 40, layoutWidth - 520))
      return Math.max(min, Math.min(max, Math.round(rawWidth)))
    },
    [assistantMinWidth],
  )

  function startAssistantResize(event: ReactPointerEvent<HTMLButtonElement>) {
    if (typeof window === 'undefined') return
    if (window.matchMedia('(max-width: 1320px)').matches) return
    event.preventDefault()
    resizeStartRef.current = {
      startX: event.clientX,
      startWidth: effectiveAssistantWidth,
    }
    setIsResizingAssistant(true)
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }

  useEffect(() => {
    if (!isResizingAssistant) return

    function onPointerMove(event: PointerEvent) {
      const start = resizeStartRef.current
      if (!start) return
      const delta = start.startX - event.clientX
      setAssistantWidth(clampAssistantWidth(start.startWidth + delta))
    }

    function onPointerUp() {
      setIsResizingAssistant(false)
      resizeStartRef.current = null
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [isResizingAssistant, clampAssistantWidth])

  function flashTo(anchor: string) {
    const domId = `cfg-${anchor.replace(/\./g, '-')}`
    setFlashAnchor(domId)
    const element = document.getElementById(domId)
    if (element) element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(() => {
      setFlashAnchor((prev) => (prev === domId ? '' : prev))
    }, 1600)
  }

  function jumpToSuggestion(row: AssistantSuggestion) {
    const anchor = String(row.anchor ?? '')
    const focusKey = String(row.focus_key ?? '').trim() || null
    if (anchor.startsWith('similarity.')) {
      setActive('similarity')
      flashTo(anchor)
      return
    }
    if (anchor.startsWith('runtime.')) {
      setActive('runtime')
      flashTo(anchor)
      return
    }
    if (anchor.startsWith('schema.')) {
      setActive('schema')
      setSchemaJumpTarget(anchor)
      setSchemaJumpFocusKey(focusKey)
      setJumpNonce((value) => value + 1)
      return
    }
    const moduleId = anchor.split('.', 1)[0]?.trim()
    if (moduleId) {
      setActive(moduleId)
      flashTo(anchor)
    }
  }

  function updateSimilarity<K extends keyof SimilarityConfig>(key: K, value: SimilarityConfig[K]) {
    setProfile((prev) => ({ ...prev, modules: { ...prev.modules, similarity: { ...prev.modules.similarity, [key]: value } } }))
  }

  function updateRuntime<K extends keyof RuntimeConfig>(key: K, value: RuntimeConfig[K]) {
    setProfile((prev) => ({ ...prev, modules: { ...prev.modules, runtime: { ...prev.modules.runtime, [key]: value } } }))
  }

  function updateProviders<K extends keyof ProvidersConfig>(key: K, value: ProvidersConfig[K]) {
    setProfile((prev) => ({ ...prev, modules: { ...prev.modules, providers: { ...prev.modules.providers, [key]: value } } }))
  }

  function updateLlmWorker(index: number, key: keyof LlmWorker, value: LlmWorker[keyof LlmWorker]) {
    setProfile((prev) => ({
      ...prev,
      modules: {
        ...prev.modules,
        llm_workers: {
          items: prev.modules.llm_workers.items.map((item, itemIndex) =>
            itemIndex === index ? { ...item, [key]: value } : item,
          ),
        },
      },
    }))
  }

  function addLlmWorker() {
    setProfile((prev) => ({
      ...prev,
      modules: {
        ...prev.modules,
        llm_workers: {
          items: [...prev.modules.llm_workers.items, createEmptyLlmWorker(prev.modules.llm_workers.items.length)],
        },
      },
    }))
  }

  function removeLlmWorker(index: number) {
    setProfile((prev) => ({
      ...prev,
      modules: {
        ...prev.modules,
        llm_workers: {
          items: prev.modules.llm_workers.items.filter((_, itemIndex) => itemIndex !== index),
        },
      },
    }))
  }

  async function testLlmWorker(index: number) {
    const worker = profile.modules.llm_workers.items[index]
    if (!worker) return
    const key = workerTestKey(worker, index)
    setWorkerTestStates((prev) => ({
      ...prev,
      [key]: { busy: true, reachable: null, error: '' },
    }))
    try {
      const res = await apiPost<LlmWorkerTestResponse>('/config-center/llm-workers/test', { worker })
      setWorkerTestStates((prev) => ({
        ...prev,
        [key]: {
          busy: false,
          reachable: Boolean(res.reachable),
          error: String(res.error ?? '').trim(),
        },
      }))
    } catch (cause: unknown) {
      setWorkerTestStates((prev) => ({
        ...prev,
        [key]: {
          busy: false,
          reachable: false,
          error: parseError(cause),
        },
      }))
    }
  }

  function updateGenericModule(moduleId: string, key: string, value: unknown) {
    setProfile((prev) => ({
      ...prev,
      modules: {
        ...prev.modules,
        [moduleId]: {
          ...(prev.modules[moduleId] ?? {}),
          [key]: value,
        },
      },
    }))
  }

  function schemaVersionLabel(item: { version: number; name?: string }) {
    const name = String(item.name ?? '').trim()
    return name ? `${name} (v${item.version})` : `v${item.version}`
  }

  function paperTypeLabel(value: PaperType) {
    const item = SCHEMA_PAPER_TYPES.find((row) => row.value === value)
    return item ? t(item.zh, item.en) : value
  }

  async function activateSchemaVersion() {
    const version = Number(schemaActivateVersion)
    if (!Number.isFinite(version) || version <= 0) return
    setSchemaVersionBusy(true)
    setError('')
    setInfo('')
    try {
      const res = await apiPost<{ schema: SchemaSummary }>('/schema/activate', {
        paper_type: schemaPaperType,
        version: Math.trunc(version),
      })
      const nextSchema = res.schema ?? null
      setSchemaSummary(nextSchema)
      setInfo(
        nextSchema
          ? t(
              `已切换到 ${paperTypeLabel(schemaPaperType)} 的 ${schemaVersionLabel(nextSchema)}。`,
              `Activated ${schemaVersionLabel(nextSchema)} for ${paperTypeLabel(schemaPaperType)}.`,
            )
          : t('已切换抽取规则版本。', 'Schema version activated.'),
      )
      await refreshSchemaOverview(schemaPaperType)
    } catch (cause: unknown) {
      setError(parseError(cause))
    } finally {
      setSchemaVersionBusy(false)
    }
  }

  async function saveProfile() {
    setSaving(true)
    setError('')
    setInfo('')
    try {
      const res = await apiPut<ConfigProfileResponse>('/config-center/profile', {
        modules: {
          ...profile.modules,
          runtime: {
            ...profile.modules.runtime,
            ingest_llm_max_workers: effectiveIngestPaperConcurrency,
          },
        },
      })
      setProfile(normalizeProfile(res.profile))
      setInfo(t('配置已保存。', 'Configuration profile saved.'))
    } catch (cause: unknown) {
      setError(parseError(cause))
    } finally {
      setSaving(false)
    }
  }

  async function runAssistant() {
    const prompt = goal.trim()
    if (!prompt) return

    setAssistantBusy(true)
    setError('')
    try {
      const res = await apiPost<AssistantResponse>('/config-center/assistant', {
        goal: prompt,
        max_suggestions: 12,
        locale,
      })

      const suggestions = (Array.isArray(res.suggestions) ? res.suggestions : [])
        .map(normalizeSuggestion)
        .filter((item): item is AssistantSuggestion => Boolean(item))

      const turn: AssistantTurn = {
        id: makeTurnId(),
        created_at: new Date().toISOString(),
        goal: prompt,
        used_llm: Boolean(res.used_llm),
        suggestions,
      }
      setAssistantTurns((prev) => [turn, ...prev].slice(0, MAX_CHAT_TURNS))
      setGoal('')
    } catch (cause: unknown) {
      const message = parseError(cause)
      const turn: AssistantTurn = {
        id: makeTurnId(),
        created_at: new Date().toISOString(),
        goal: prompt,
        used_llm: false,
        suggestions: [],
        error: message,
      }
      setAssistantTurns((prev) => [turn, ...prev].slice(0, MAX_CHAT_TURNS))
      setError(message)
    } finally {
      setAssistantBusy(false)
    }
  }

  function applySuggestion(row: AssistantSuggestion) {
    const anchor = String(row.anchor ?? '')
    const value = String(row.suggested_value ?? '').trim()
    if (anchor.startsWith('similarity.')) {
      const key = anchor.slice('similarity.'.length) as keyof SimilarityConfig
      if (key === 'group_clustering_method') {
        updateSimilarity(key, value as SimilarityConfig[typeof key])
      } else {
        updateSimilarity(key, asNumber(value, profile.modules.similarity[key] as number) as SimilarityConfig[typeof key])
      }
      setActive('similarity')
    } else {
      if (anchor.startsWith('runtime.')) {
        const key = anchor.slice('runtime.'.length) as keyof RuntimeConfig
        updateRuntime(key, asNumber(value, profile.modules.runtime[key] as number) as RuntimeConfig[typeof key])
        setActive('runtime')
      } else if (!anchor.startsWith('schema.')) {
        const [moduleId, key] = anchor.split('.', 2)
        if (!moduleId || !key) {
          jumpToSuggestion(row)
          return
        }
        const moduleCatalog = (catalog.modules ?? []).find((module) => String(module?.id ?? '').trim() === moduleId) ?? null
        const field = Array.isArray(moduleCatalog?.fields)
          ? (moduleCatalog?.fields ?? []).find((item) => String(item?.key ?? '').trim() === key)
          : undefined
        const fallback = profile.modules[moduleId]?.[key]
        updateGenericModule(moduleId, key, coerceGenericFieldValue(field, key, value, fallback))
        setActive(moduleId)
      } else {
        jumpToSuggestion(row)
        return
      }
    }
    flashTo(anchor)
    setInfo(t(`已应用建议到 ${anchor}。请保存配置以持久化。`, `Applied suggestion to ${anchor}. Save profile to persist.`))
  }

  const schemaModule = useMemo(
    () => (catalog.modules ?? []).find((module) => String(module?.id ?? '') === 'schema') ?? null,
    [catalog.modules],
  )
  const catalogModuleMap = useMemo(
    () =>
      new Map(
        (catalog.modules ?? [])
          .map((module) => {
            const id = String(module?.id ?? '').trim()
            return id ? ([id, module] as const) : null
          })
          .filter((item): item is readonly [string, ConfigCatalogModule] => Boolean(item)),
      ),
    [catalog.modules],
  )
  const llmWorkersCatalog = useMemo(() => catalogModuleMap.get('llm_workers') ?? null, [catalogModuleMap])
  const schemaRuleKeys = useMemo(() => schemaModule?.rule_keys ?? [], [schemaModule])
  const schemaPromptKeys = useMemo(() => schemaModule?.prompt_keys ?? [], [schemaModule])
  const schemaRulePreview = useMemo(() => schemaRuleKeys.slice(0, 18), [schemaRuleKeys])
  const schemaPromptPreview = useMemo(() => schemaPromptKeys.slice(0, 18), [schemaPromptKeys])
  const moduleItems = useMemo(() => {
    const seen = new Set<string>(MODULE_ITEMS.map((item) => item.id))
    const extras: ModuleItem[] = []

    for (const module of catalog.modules ?? []) {
      const id = String(module?.id ?? '').trim()
      if (!id || isBuiltinModule(id) || seen.has(id)) continue
      seen.add(id)
      const rawLabel = String(module?.label ?? humanizeToken(id)).trim() || humanizeToken(id)
      const rawDesc = String(module?.description ?? '').trim() || t('附加配置模块。', 'Additional configuration module.')
      extras.push({
        id,
        label: {
          zh: localizedModuleLabel(id, rawLabel, (zh) => zh),
          en: localizedModuleLabel(id, rawLabel, (_zh, fallbackEn) => fallbackEn),
        },
        desc: {
          zh: localizedModuleDescription(id, rawDesc, (zh) => zh),
          en: localizedModuleDescription(id, rawDesc, (_zh, fallbackEn) => fallbackEn),
        },
      })
    }

    for (const moduleId of Object.keys(profile.modules)) {
      if (isBuiltinModule(moduleId) || seen.has(moduleId)) continue
      seen.add(moduleId)
      const label = humanizeToken(moduleId)
      extras.push({
        id: moduleId,
        label: {
          zh: localizedModuleLabel(moduleId, label, (zh) => zh),
          en: localizedModuleLabel(moduleId, label, (_zh, fallbackEn) => fallbackEn),
        },
        desc: {
          zh: localizedModuleDescription(moduleId, t('附加配置模块。', 'Additional configuration module.'), (zh) => zh),
          en: localizedModuleDescription(moduleId, 'Additional configuration module.', (_zh, fallbackEn) => fallbackEn),
        },
      })
    }

    return [...MODULE_ITEMS, ...extras]
  }, [catalog.modules, profile.modules, t])
  const genericModuleId = !isBuiltinModule(active) ? active : null
  const genericModuleCatalog = genericModuleId ? catalogModuleMap.get(genericModuleId) ?? null : null
  const genericModuleValues = useMemo(
    () => (genericModuleId ? profile.modules[genericModuleId] ?? {} : {}),
    [genericModuleId, profile.modules],
  )
  const genericFieldModels = useMemo(
    () => (genericModuleId ? buildGenericFieldModels(genericModuleId, genericModuleValues, genericModuleCatalog) : []),
    [genericModuleCatalog, genericModuleId, genericModuleValues],
  )

  useEffect(() => {
    if (moduleItems.some((item) => item.id === active)) return
    setActive(moduleItems[0]?.id ?? 'similarity')
  }, [active, moduleItems])

  const layoutClass = active === 'schema' ? 'cc-layout cc-layout--schema' : 'cc-layout'
  const layoutStyle = { '--cc-assistant-w': `${effectiveAssistantWidth}px` } as CSSProperties

  return (
    <div className="page cc-page">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">{t('配置中心', 'Config Center')}</h2>
          <div className="pageSubtitle">
            {t(
              '统一管理相似性聚类、抽取策略和运维调优建议。',
              'Unified operations configuration for similarity clustering, extraction policy, and tuning guidance.',
            )}
          </div>
          <div className="metaLine">
            {t('配置档格式', 'Profile Format')} v{profile.version} - {t('更新时间', 'Updated')} {profile.updated_at || '--'}
          </div>
        </div>
        <div className="row">
          <button className="btn" disabled={loading} onClick={() => void refreshAll()}>
            {loading ? t('刷新中...', 'Refreshing...') : t('刷新', 'Refresh')}
          </button>
          <button className="btn btnPrimary" disabled={saving} onClick={() => void saveProfile()}>
            {saving ? t('保存中...', 'Saving...') : t('保存配置', 'Save Profile')}
          </button>
        </div>
      </div>

      {warning ? <div className="cc-warning-box">{warning}</div> : null}
      {error ? <div className="errorBox">{error}</div> : null}
      {info ? <div className="hint" style={{ marginBottom: 10 }}>{info}</div> : null}

      <div ref={layoutRef} className={layoutClass} style={layoutStyle}>
        <section className="cc-main">
          <div className="cc-module-tabs">
            {moduleItems.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`cc-module-tab${active === item.id ? ' is-active' : ''}`}
                onClick={() => setActive(item.id)}
              >
                <span>{t(item.label.zh, item.label.en)}</span>
                <small>{t(item.desc.zh, item.desc.en)}</small>
              </button>
            ))}
          </div>

          {active === 'similarity' ? (
            <section className="panel">
              <div className="panelHeader">
                <div className="panelTitle">{t('相似性聚类', 'Similarity and Clustering')}</div>
              </div>
              <div className="panelBody cc-grid cc-grid--compact">
                <label
                  id="cfg-similarity-group_clustering_method"
                  className={`cc-field${flashAnchor === 'cfg-similarity-group_clustering_method' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('相似性聚类方法', 'group_clustering_method')}</span>
                  <select
                    className="input"
                    value={profile.modules.similarity.group_clustering_method}
                    onChange={(event) =>
                      updateSimilarity('group_clustering_method', event.target.value as SimilarityConfig['group_clustering_method'])
                    }
                  >
                    <option value="hybrid">{t('混合策略', 'hybrid')}</option>
                    <option value="louvain">{t('Louvain 社区', 'louvain')}</option>
                    <option value="agglomerative">{t('层次聚类', 'agglomerative')}</option>
                  </select>
                  <span className="cc-help">
                    {t('决定相似性图谱在重建时如何形成分组。', 'How similarity clusters are formed during similarity rebuild.')}
                  </span>
                </label>

                <label
                  id="cfg-similarity-group_clustering_threshold"
                  className={`cc-field${flashAnchor === 'cfg-similarity-group_clustering_threshold' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('分组阈值', 'group_clustering_threshold')}</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={profile.modules.similarity.group_clustering_threshold}
                    onChange={(event) =>
                      updateSimilarity('group_clustering_threshold', Math.max(0, Math.min(1, Number(event.target.value || 0.85))))
                    }
                  />
                  <span className="cc-help">
                    {t('阈值越高，聚类越紧、越保守。', 'Higher values produce tighter and more conservative clusters.')}
                  </span>
                </label>
              </div>
            </section>
          ) : null}

          {active === 'runtime' ? (
            <section className="panel">
              <div className="panelHeader">
                <div className="split">
                  <div className="panelTitle">{t('运行并发', 'Runtime Concurrency')}</div>
                  <div className="row">
                    <span className="pill">{t('平衡版默认值', 'Balanced Defaults')}</span>
                    <span className="pill">{t(`有效论文并发 ${effectiveIngestPaperConcurrency}`, `Effective Paper Concurrency ${effectiveIngestPaperConcurrency}`)}</span>
                    <span className="pill">{t(`工作器连接容量 ${enabledWorkerPaperCapacity}`, `Worker Connection Capacity ${enabledWorkerPaperCapacity}`)}</span>
                  </div>
                </div>
              </div>
              <div className="panelBody">
                <div className="hint" style={{ marginBottom: 12 }}>
                  {t(
                    '这里管理单篇内部并发、预处理和全局大模型限流。各单篇并发字段为"参考值"，系统在全局连接空闲时可自动上调。"有效论文并发"由 LLM 工作器连接容量和全局上限共同决定，前者可热更新，后者（大模型全局并发上限）需重启后端才能生效。',
                    'Manage per-paper fan-out, preprocessing, and the global LLM limiter. Per-paper concurrency fields are reference values — the system may raise them when global slots are idle. Effective paper concurrency is derived from worker connection capacity and the global cap; worker changes take effect immediately, but the global cap (llm_global_max_concurrent) requires a backend restart.',
                  )}
                </div>
                <div className="cc-grid cc-grid--compact">
                  <label
                    id="cfg-runtime-ingest_llm_max_workers"
                    className={`cc-field${flashAnchor === 'cfg-runtime-ingest_llm_max_workers' ? ' is-flash' : ''}`}
                  >
                    <span className="cc-label">{t('论文级并发', 'ingest_llm_max_workers')}</span>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      max={16}
                      step={1}
                      value={effectiveIngestPaperConcurrency}
                      readOnly
                      disabled
                    />
                    <span className="cc-help">
                      {t(
                        '只读，由系统自动推算：min(全局上限 ÷ 内部并发分母, 各可路由工作器的 ceil(连接数 ÷ 分母) 之和)。调整工作器"最大并发连接数"或"大模型全局并发上限"可改变该值（后者需重启后端）。',
                        'Read-only, auto-derived: min(global_cap ÷ fan-out, Σ ceil(worker_connections ÷ fan-out) for routable workers). Change worker connection capacity or llm_global_max_concurrent to affect this (the latter requires a backend restart).',
                      )}
                    </span>
                  </label>
                  {RUNTIME_FIELDS.map((field) => (
                    <label
                      key={field.key}
                      id={`cfg-runtime-${field.key}`}
                      className={`cc-field${flashAnchor === `cfg-runtime-${field.key}` ? ' is-flash' : ''}`}
                    >
                      <span className="cc-label">{t(field.zh, field.en)}</span>
                      <input
                        className="input"
                        type="number"
                        min={field.min}
                        max={field.max}
                        step={1}
                        value={profile.modules.runtime[field.key]}
                        onChange={(event) =>
                          updateRuntime(
                            field.key,
                            Math.max(field.min, Math.min(field.max, Math.trunc(Number(event.target.value || profile.modules.runtime[field.key])))) as RuntimeConfig[typeof field.key],
                          )
                        }
                      />
                      <span className="cc-help">{t(field.helpZh, field.helpEn)}</span>
                    </label>
                  ))}
                </div>
              </div>
            </section>
          ) : null}

          {active === 'providers' ? (
            <section className="panel">
              <div className="panelHeader">
                <div className="split">
                  <div className="panelTitle">{t('模型与向量', 'LLM & Embeddings')}</div>
                  <span className="pill">{t('去重整理', 'Reduced duplication')}</span>
                </div>
              </div>
              <div className="panelBody">
                <div className="hint" style={{ marginBottom: 12 }}>
                  {t(
                    'LLM 工作器负责整篇论文抽取所需的 url、key、model。这里仅保留向量服务相关配置，旧的单路 LLM 配置不再在此处显示。',
                    'LLM workers own the url, key, and model used for whole-paper extraction. This panel now only keeps embedding-related settings; older single-provider LLM settings are no longer shown here.',
                  )}
                </div>

                <div className="cc-worker-list">
                  <div className="cc-worker-card">
                    <div className="cc-worker-cardHeader">
                      <div className="panelTitle" style={{ fontSize: 16 }}>{t('向量服务', 'Embeddings')}</div>
                    </div>
                    <div className="cc-grid cc-grid--compact">
                      <label className="cc-field">
                        <span className="cc-label">{t('向量提供方', 'Embedding Provider')}</span>
                        <select
                          className="input"
                          aria-label="embedding_provider"
                          value={profile.modules.providers.embedding_provider}
                          onChange={(event) => updateProviders('embedding_provider', event.target.value)}
                        >
                          <option value="">{t('自动推断', 'Auto')}</option>
                          <option value="siliconflow">SiliconFlow</option>
                          <option value="openai">OpenAI</option>
                          <option value="openrouter">OpenRouter</option>
                          <option value="deepseek">DeepSeek</option>
                        </select>
                        <span className="cc-help">{t('控制向量检索、索引和聚类使用的服务。', 'Used for retrieval, indexing, and clustering embeddings.')}</span>
                      </label>

                      <label className="cc-field">
                        <span className="cc-label">{t('向量地址', 'Embedding Base URL')}</span>
                        <input
                          className="input"
                          aria-label="embedding_base_url"
                          type="text"
                          value={profile.modules.providers.embedding_base_url}
                          placeholder="https://example.com/v1"
                          onChange={(event) => updateProviders('embedding_base_url', event.target.value)}
                        />
                        <span className="cc-help">{t('如需代理或兼容网关，可在这里覆盖。', 'Override when using a proxy or compatible gateway.')}</span>
                      </label>

                      <label className="cc-field">
                        <span className="cc-label">{t('向量密钥', 'Embedding API Key')}</span>
                        <input
                          className="input"
                          aria-label="embedding_api_key"
                          type="password"
                          value={profile.modules.providers.embedding_api_key}
                          onChange={(event) => updateProviders('embedding_api_key', event.target.value)}
                        />
                        <span className="cc-help">{t('向量服务独立密钥。', 'Dedicated embedding service API key.')}</span>
                      </label>

                      <label className="cc-field">
                        <span className="cc-label">{t('向量模型', 'Embedding Model')}</span>
                        <input
                          className="input"
                          aria-label="embedding_model"
                          type="text"
                          value={profile.modules.providers.embedding_model}
                          onChange={(event) => updateProviders('embedding_model', event.target.value)}
                        />
                        <span className="cc-help">{t('向量索引与检索默认模型。', 'Default model used for embeddings.')}</span>
                      </label>

                      <label className="cc-field">
                        <span className="cc-label">{t('SiliconFlow 密钥', 'SiliconFlow API Key')}</span>
                        <input
                          className="input"
                          aria-label="siliconflow_api_key"
                          type="password"
                          value={profile.modules.providers.siliconflow_api_key}
                          onChange={(event) => updateProviders('siliconflow_api_key', event.target.value)}
                        />
                        <span className="cc-help">{t('仅在向量提供方为 SiliconFlow 时使用。', 'Used when the embedding provider is SiliconFlow.')}</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          ) : null}

          {active === 'llm_workers' ? (
            <section className="panel">
              <div className="panelHeader">
                <div className="split">
                  <div className="panelTitle">{t('LLM 工作器', 'LLM Workers')}</div>
                  <div className="row">
                    <span className="pill">{t('整篇论文绑定', 'Paper-bound routing')}</span>
                    <span className="pill">{t(`总连接容量 ${enabledWorkerPaperCapacity}`, `Total Connection Capacity ${enabledWorkerPaperCapacity}`)}</span>
                    <button className="btn" type="button" onClick={addLlmWorker}>
                      {t('新增工作器', 'Add Worker')}
                    </button>
                  </div>
                </div>
              </div>
              <div className="panelBody">
                <div className="hint" style={{ marginBottom: 12 }}>
                  {localizedModuleDescription(
                    'llm_workers',
                    String(llmWorkersCatalog?.description ?? '').trim() ||
                      t(
                        '每篇论文会固定分配给一个工作器，论文内部的 LogicStep、Claim、grounding 等后续请求都会沿用同一个来源。',
                        'Each paper is pinned to one worker for its full extraction lifecycle, including nested logic, claim, and grounding calls.',
                      ),
                    t,
                  )}
                </div>

                {profile.modules.llm_workers.items.length ? (
                  <div className="cc-worker-list">
                    {profile.modules.llm_workers.items.map((worker, index) => {
                      const testState = workerTestStates[workerTestKey(worker, index)]
                      return (
                      <div key={`${worker.id}-${index}`} className="cc-worker-card">
                        <div className="cc-worker-cardHeader">
                          <div>
                            <div className="panelTitle" style={{ fontSize: 16 }}>
                              {t(`工作器 ${index + 1}`, `Worker ${index + 1}`)}
                            </div>
                            <div className="metaLine">{worker.id}</div>
                            {testState ? (
                              <div className="metaLine">
                                {testState.busy
                                  ? t('测试中...', 'Testing...')
                                  : testState.reachable
                                    ? t('连接正常', 'Connection OK')
                                    : testState.error
                                      ? t(`连接失败：${testState.error}`, `Connection failed: ${testState.error}`)
                                      : t('连接失败', 'Connection failed')}
                              </div>
                            ) : null}
                          </div>
                          <div className="row">
                            <button className="btn" type="button" onClick={() => void testLlmWorker(index)} disabled={Boolean(testState?.busy)}>
                              {testState?.busy ? t(`测试工作器 ${index + 1}...`, `Testing Worker ${index + 1}...`) : t(`测试工作器 ${index + 1}`, `Test Worker ${index + 1}`)}
                            </button>
                            <button className="btn" type="button" onClick={() => removeLlmWorker(index)}>
                              {t('移除', 'Remove')}
                            </button>
                          </div>
                        </div>

                        <div className="cc-grid cc-grid--compact">
                          <label className="cc-field">
                            <span className="cc-label">{t('显示名称', 'Label')}</span>
                            <input
                              className="input"
                              aria-label={`Worker ${index + 1} Label`}
                              type="text"
                              value={worker.label}
                              onChange={(event) => updateLlmWorker(index, 'label', event.target.value)}
                            />
                            <span className="cc-help">{t('用于运维界面显示，不影响实际请求。', 'Friendly label shown in the operations UI.')}</span>
                          </label>

                          <label className="cc-field">
                            <span className="cc-label">{t('基础地址', 'Base URL')}</span>
                            <input
                              className="input"
                              aria-label={`Worker ${index + 1} Base URL`}
                              type="text"
                              value={worker.base_url}
                              placeholder="https://example.com/v1"
                              onChange={(event) => updateLlmWorker(index, 'base_url', event.target.value)}
                            />
                            <span className="cc-help">{t('填写 OpenAI 兼容网关地址。', 'OpenAI-compatible gateway URL.')}</span>
                          </label>

                          <label className="cc-field">
                            <span className="cc-label">{t('接口密钥', 'API Key')}</span>
                            <input
                              className="input"
                              aria-label={`Worker ${index + 1} API Key`}
                              type="password"
                              value={worker.api_key}
                              onChange={(event) => updateLlmWorker(index, 'api_key', event.target.value)}
                            />
                            <span className="cc-help">{t('仅对这个工作器生效。', 'Only used for this worker.')}</span>
                          </label>

                          <label className="cc-field">
                            <span className="cc-label">{t('模型名', 'Model')}</span>
                            <input
                              className="input"
                              aria-label={`Worker ${index + 1} Model`}
                              type="text"
                              value={worker.model}
                              placeholder={t('留空则回退到全局默认模型', 'Leave empty to use the global default model')}
                              onChange={(event) => updateLlmWorker(index, 'model', event.target.value)}
                            />
                            <span className="cc-help">{t('不同来源可填写不同模型名。', 'Use per-worker model names when gateways differ.')}</span>
                          </label>

                          <label className="cc-field">
                            <span className="cc-label">{t('最大并发连接数', 'Max Concurrent Connections')}</span>
                            <input
                              className="input"
                              aria-label={`Worker ${index + 1} Parallel Papers`}
                              type="number"
                              min={1}
                              max={128}
                              step={1}
                              value={worker.max_concurrent}
                              onChange={(event) =>
                                updateLlmWorker(index, 'max_concurrent', Math.max(1, Math.min(128, Math.trunc(Number(event.target.value || worker.max_concurrent)))))
                              }
                            />
                            <span className="cc-help">{t('此工作器允许同时在途的 LLM HTTP 请求数上限。每篇论文内部会并行发起多个请求（由要点/复核/冲突并发的最大值决定），实际论文并发 ≈ 该值 ÷ 内部并发分母。例如内部并发为 4，设 32 则约能同时处理 8 篇。', 'Maximum simultaneous in-flight LLM HTTP requests for this worker. Each paper generates multiple concurrent requests internally (fan-out = max of claim/grounding/conflict workers). Effective paper concurrency ≈ this value ÷ fan-out. Example: fan-out 4 × 32 connections ≈ 8 papers.')}</span>
                          </label>

                          <label className="cc-field">
                            <span className="cc-label">{t('启用', 'Enabled')}</span>
                            <input
                              className="input"
                              aria-label={`Worker ${index + 1} Enabled`}
                              type="checkbox"
                              checked={worker.enabled}
                              onChange={(event) => updateLlmWorker(index, 'enabled', event.target.checked)}
                            />
                            <span className="cc-help">{t('关闭后不会再分配新论文。', 'Disabled workers stop receiving new papers.')}</span>
                          </label>
                        </div>
                      </div>
                    )})}
                  </div>
                ) : (
                  <div className="hint">
                    {t('当前还没有配置任何工作器。你可以先新增一个工作器，再填写地址、密钥和模型。', 'No workers configured yet. Add one to start routing papers across gateways.')}
                  </div>
                )}
              </div>
            </section>
          ) : null}

          {genericModuleId ? (
            <section className="panel">
              <div className="panelHeader">
                <div className="split">
                  <div className="panelTitle">
                    {localizedModuleLabel(genericModuleId, String(genericModuleCatalog?.label ?? humanizeToken(genericModuleId)), t)}
                  </div>
                  <span className="pill">{t('后续任务生效', 'Applies to next tasks')}</span>
                </div>
              </div>
              <div className="panelBody">
                {localizedModuleDescription(genericModuleId, String(genericModuleCatalog?.description ?? '').trim(), t) ? (
                  <div className="hint" style={{ marginBottom: 12 }}>
                    {localizedModuleDescription(genericModuleId, String(genericModuleCatalog?.description ?? '').trim(), t)}
                  </div>
                ) : null}
                {genericFieldModels.length ? (
                  <div className="cc-grid cc-grid--compact">
                    {genericFieldModels.map((field) => (
                      <label
                        key={field.anchor}
                        id={`cfg-${field.anchor.replace(/\./g, '-')}`}
                        className={`cc-field${flashAnchor === `cfg-${field.anchor.replace(/\./g, '-')}` ? ' is-flash' : ''}`}
                      >
                        <span className="cc-label">{localizedFieldLabel(field.anchor, field.label, t)}</span>
                        {field.kind === 'boolean' ? (
                          <input
                            className="input"
                            aria-label={localizedFieldLabel(field.anchor, field.label, t)}
                            type="checkbox"
                            checked={Boolean(field.value)}
                            onChange={(event) => updateGenericModule(genericModuleId, field.key, event.target.checked)}
                          />
                        ) : null}
                        {field.kind === 'number' ? (
                          <input
                            className="input"
                            aria-label={localizedFieldLabel(field.anchor, field.label, t)}
                            type="number"
                            min={field.min}
                            max={field.max}
                            step={field.step ?? 1}
                            value={typeof field.value === 'number' ? field.value : asNumber(field.value, 0)}
                            onChange={(event) =>
                              updateGenericModule(
                                genericModuleId,
                                field.key,
                                coerceGenericFieldValue(
                                  Array.isArray(genericModuleCatalog?.fields)
                                    ? (genericModuleCatalog?.fields ?? []).find((item) => String(item?.key ?? '').trim() === field.key)
                                    : undefined,
                                  field.key,
                                  event.target.value,
                                  field.value,
                                ),
                              )
                            }
                          />
                        ) : null}
                        {field.kind === 'select' ? (
                          <select
                            className="input"
                            aria-label={localizedFieldLabel(field.anchor, field.label, t)}
                            value={String(field.value ?? '')}
                            onChange={(event) => updateGenericModule(genericModuleId, field.key, event.target.value)}
                          >
                            {field.options.map((option) => (
                              <option key={`${field.anchor}-${option.value}`} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        ) : null}
                        {field.kind === 'textarea' ? (
                          <textarea
                            className="textarea"
                            aria-label={localizedFieldLabel(field.anchor, field.label, t)}
                            value={String(field.value ?? '')}
                            placeholder={field.placeholder || undefined}
                            onChange={(event) => updateGenericModule(genericModuleId, field.key, event.target.value)}
                          />
                        ) : null}
                        {field.kind === 'string' || field.kind === 'password' ? (
                          <input
                            className="input"
                            aria-label={localizedFieldLabel(field.anchor, field.label, t)}
                            type={field.kind === 'password' ? 'password' : 'text'}
                            value={String(field.value ?? '')}
                            placeholder={field.placeholder || undefined}
                            onChange={(event) => updateGenericModule(genericModuleId, field.key, event.target.value)}
                          />
                        ) : null}
                        <span className="cc-help">{localizedFieldDescription(field.anchor, field.description || humanizeToken(field.key), t)}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="hint">{t('当前模块没有可编辑字段。', 'No editable fields are available for this module.')}</div>
                )}
              </div>
            </section>
          ) : null}

          {active === 'schema' ? (
            <section className="cc-schema-wrap">
              <div className="panel">
                <div className="panelHeader">
                  <div className="split">
                    <div className="panelTitle">{t('抽取规则版本速切', 'Schema Version Switcher')}</div>
                    <span className="pill">{schemaVersionLoading ? t('加载中', 'Loading') : t('后续任务生效', 'Applies to next tasks')}</span>
                  </div>
                </div>
                <div className="panelBody cc-grid cc-grid--compact">
                  <label className="cc-field">
                    <span className="cc-label">{t('论文类型', 'Paper Type')}</span>
                    <select className="input" value={schemaPaperType} onChange={(event) => setSchemaPaperType(event.target.value as PaperType)}>
                      {SCHEMA_PAPER_TYPES.map((item) => (
                        <option key={item.value} value={item.value}>
                          {t(item.zh, item.en)}
                        </option>
                      ))}
                    </select>
                    <span className="cc-help">{t('按论文类型管理当前启用的抽取规则版本。', 'Manage the active schema version per paper type.')}</span>
                  </label>

                  <div className="cc-field">
                    <span className="cc-label">{t('当前激活版本', 'Active Version')}</span>
                    <div className="row" style={{ minHeight: 40, alignItems: 'center' }}>
                      <span className="pill">
                        {schemaSummary ? schemaVersionLabel(schemaSummary) : t('未加载', 'Not loaded')}
                      </span>
                    </div>
                    <span className="cc-help">
                      {t('切换版本不会改历史论文记录，只会影响后续导入、替换和重建。', 'Changing the version affects future ingest, replace, and rebuild tasks, not historical paper records.')}
                    </span>
                  </div>

                  <label id="cfg-schema-version-switch" className="cc-field">
                    <span className="cc-label">{t('切换到版本', 'Version to Activate')}</span>
                    <select className="input" value={schemaActivateVersion} onChange={(event) => setSchemaActivateVersion(event.target.value)}>
                      <option value="">{t('选择版本…', 'Select a version...')}</option>
                      {schemaVersions.map((item) => (
                        <option key={item.version} value={String(item.version)}>
                          {schemaVersionLabel(item)}
                        </option>
                      ))}
                    </select>
                    <span className="cc-help">{t('这里做快速切换；完整的版本命名、预设套用和规则编辑仍在下方。', 'Use this for fast switching. Full naming, preset application, and rule editing remain below.')}</span>
                  </label>

                  <div className="cc-field">
                    <span className="cc-label">{t('版本操作', 'Version Action')}</span>
                    <div className="row">
                      <button className="btn" disabled={schemaVersionBusy || !schemaActivateVersion} onClick={() => void activateSchemaVersion()}>
                        {schemaVersionBusy ? t('切换中...', 'Switching...') : t('激活版本', 'Activate Version')}
                      </button>
                      <button className="btn" disabled={schemaVersionLoading} onClick={() => void refreshSchemaOverview(schemaPaperType)}>
                        {t('刷新版本列表', 'Refresh Versions')}
                      </button>
                    </div>
                    <span className="cc-help">
                      {t('建议优先切到较新的均衡版（如 v8），再对目标论文执行重建。', 'For research papers, switching to a newer balanced schema such as v8 before rebuilding usually works better.')}
                    </span>
                  </div>
                </div>
              </div>

              <div className="panel">
                <div className="panelHeader">
                  <div className="panelTitle">{t('抽取策略助手索引', 'Extraction Policy Assistant Index')}</div>
                </div>
                <div className="panelBody cc-schema-index">
                  <div className="metaLine">
                    {t(
                      '该索引用于把助手跳转链接映射到抽取规则对应编辑区。',
                      'This index maps assistant jump links to schema edit areas.',
                    )}
                    <code> schema.rules_json </code>
                    {t('对应规则 JSON，', 'points to rule JSON and')}
                    <code> schema.prompts_json </code>
                    {t('对应提示词 JSON。', 'points to prompt JSON.')}
                  </div>
                  <div className="cc-schema-index-stats">
                    <span className="pill">{t('规则键', 'Rule Keys')}: {schemaRuleKeys.length}</span>
                    <span className="pill">{t('提示词键', 'Prompt Keys')}: {schemaPromptKeys.length}</span>
                    <button className="btn btnSmall" onClick={() => setShowSchemaKeyList((value) => !value)}>
                      {showSchemaKeyList ? t('隐藏键列表', 'Hide Key List') : t('显示键列表', 'Show Key List')}
                    </button>
                  </div>
                  {showSchemaKeyList ? (
                    <div className="cc-schema-index-grid">
                      <div className="cc-schema-index-block">
                        <div className="kicker">{t('规则键预览', 'Rule Keys Preview')}</div>
                        <div className="cc-key-list">
                          {schemaRulePreview.map((key) => (
                            <span key={`rk-${key}`} className="cc-key-pill">
                              {key}
                            </span>
                          ))}
                        </div>
                        {schemaRuleKeys.length > schemaRulePreview.length ? (
                          <div className="hint">
                            {t(`其余 ${schemaRuleKeys.length - schemaRulePreview.length} 项...`, `and ${schemaRuleKeys.length - schemaRulePreview.length} more...`)}
                          </div>
                        ) : null}
                      </div>
                      <div className="cc-schema-index-block">
                        <div className="kicker">{t('提示词键预览', 'Prompt Keys Preview')}</div>
                        <div className="cc-key-list">
                          {schemaPromptPreview.map((key) => (
                            <span key={`pk-${key}`} className="cc-key-pill">
                              {key}
                            </span>
                          ))}
                        </div>
                        {schemaPromptKeys.length > schemaPromptPreview.length ? (
                          <div className="hint">
                            {t(`其余 ${schemaPromptKeys.length - schemaPromptPreview.length} 项...`, `and ${schemaPromptKeys.length - schemaPromptPreview.length} more...`)}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
              <SchemaPage jumpTarget={schemaJumpTarget} jumpFocusKey={schemaJumpFocusKey} jumpNonce={jumpNonce} />
            </section>
          ) : null}
        </section>

        <button
          type="button"
          className={`cc-resizer${isResizingAssistant ? ' is-active' : ''}`}
          onPointerDown={startAssistantResize}
          aria-label={t('调整助手面板宽度', 'Resize assistant panel')}
          aria-orientation="vertical"
        />

        <aside className="cc-assistant">
          <section className="panel cc-chat-panel">
            <div className="panelHeader">
              <div className="split">
                <div className="panelTitle">{t('运维助手', 'LLM Ops Assistant')}</div>
                <span className="badge">{t('对话', 'Chat')}</span>
              </div>
            </div>
            <div className="panelBody cc-chat-body">
              <div className="cc-chat-scroll">
                {assistantTurns.length === 0 ? (
                  <div className="metaLine">
                    {t(
                      '描述你的目标，例如精度、召回、速度或并发，助手会给出相似性、抽取策略和运行参数建议。',
                      'Describe your target, such as precision, recall, speed, or concurrency. The assistant will propose similarity, schema, and runtime suggestions.',
                    )}
                  </div>
                ) : (
                  assistantTurns.map((turn) => (
                    <article key={turn.id} className="cc-chat-turn">
                      <div className="cc-chat-bubble cc-chat-bubble-user">
                        <div className="kicker">{t('你', 'You')}</div>
                        <div>{turn.goal}</div>
                      </div>

                      <div className="cc-chat-bubble cc-chat-bubble-assistant">
                        <div className="split">
                          <div className="kicker">{t('LogicKG 助手', 'LogicKG Assistant')}</div>
                          <span className={`badge${turn.used_llm ? ' badgeOk' : ''}`}>{turn.used_llm ? t('模型', 'LLM') : t('规则', 'Heuristic')}</span>
                        </div>
                        <div className="metaLine">{new Date(turn.created_at).toLocaleString()}</div>

                        {turn.error ? (
                          <div className="hint">{t('请求失败', 'Request failed')}: {turn.error}</div>
                        ) : (
                          <div className="cc-chat-suggestion-list">
                            {turn.suggestions.map((row, index) => (
                              <div key={`${turn.id}-${row.anchor}-${index}`} className="cc-chat-suggestion-card">
                                <div className="split">
                                  <button type="button" className="cc-link-btn" onClick={() => jumpToSuggestion(row)}>
                                    {localizedFieldLabel(row.anchor, row.anchor, t)}
                                  </button>
                                  <span className="badge">{localizedModuleLabel(row.module, row.module, t)}</span>
                                </div>
                                <div className="cc-suggestion-value">
                                  {t('建议值', 'Suggested')}: <code>{row.suggested_value}</code>
                                </div>
                                <div className="metaLine">{row.rationale}</div>
                                {row.focus_key ? (
                                  <div className="metaLine">
                                    {t('定位键', 'focus_key')}: <code>{row.focus_key}</code>
                                  </div>
                                ) : null}
                                {row.caution ? <div className="hint">{t('风险提示', 'Risk')}: {row.caution}</div> : null}
                                <div className="row">
                                  <button className="btn btnSmall" onClick={() => jumpToSuggestion(row)}>
                                    {t('跳转并高亮', 'Jump and Highlight')}
                                  </button>
                                  {row.anchor.startsWith('similarity.') || row.anchor.startsWith('runtime.') ? (
                                    <button className="btn btnSmall" onClick={() => applySuggestion(row)}>
                                      {t('应用参数', 'Apply Value')}
                                    </button>
                                  ) : null}
                                </div>
                              </div>
                            ))}
                            {turn.suggestions.length === 0 ? (
                              <div className="metaLine">{t('当前查询没有返回建议。', 'No suggestions returned for this query.')}</div>
                            ) : null}
                          </div>
                        )}
                      </div>
                    </article>
                  ))
                )}
              </div>

              <div className="cc-chat-composer">
                <textarea
                  className="textarea cc-chat-input"
                  value={goal}
                  onChange={(event) => setGoal(event.target.value)}
                  placeholder={t(
                      '例如：提高抽取精度并减少噪声要点',
                      'Example: tighten extraction precision and reduce noisy claims',
                    )}
                />
                <div className="row">
                  <button className="btn btnPrimary" disabled={assistantBusy} onClick={() => void runAssistant()}>
                    {assistantBusy ? t('思考中...', 'Thinking...') : t('发送', 'Send')}
                  </button>
                  <button
                    className="btn"
                    onClick={() => {
                      setAssistantTurns([])
                      if (typeof window !== 'undefined') window.localStorage.removeItem(CHAT_TURNS_STORAGE_KEY)
                    }}
                  >
                    {t('清空对话', 'Clear Chat')}
                  </button>
                </div>
                <div className="hint">
                  {t(
                      '建议支持跳转定位；相似性和运行参数可直接应用，抽取策略建议可跳转到对应编辑区。',
                      'Suggestions support jump links. Similarity and runtime parameters can be applied directly, while schema suggestions jump to the relevant editor.',
                    )}
                </div>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
