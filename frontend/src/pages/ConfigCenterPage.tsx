import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { apiGet, apiPost, apiPut } from '../api'
import { useI18n } from '../i18n'
import SchemaPage from './SchemaPage'
import './config-center.css'

type ModuleTab = 'discovery' | 'similarity' | 'schema'

type DiscoveryConfig = {
  domain: string
  dry_run: boolean
  max_gaps: number
  candidates_per_gap: number
  use_llm: boolean
  hop_order: number
  adjacent_samples: number
  random_samples: number
  rag_top_k: number
  prompt_optimize: boolean
  community_method: 'author_hop' | 'louvain' | 'hybrid'
  community_samples: number
  prompt_optimization_method: 'rl_bandit' | 'heuristic'
}

type SimilarityConfig = {
  group_clustering_method: 'agglomerative' | 'louvain' | 'hybrid'
  group_clustering_threshold: number
}

type ConfigProfile = {
  version: number
  updated_at?: string
  modules: {
    discovery: DiscoveryConfig
    similarity: SimilarityConfig
  }
}

type ConfigProfileResponse = {
  profile?: Partial<ConfigProfile>
}

type ConfigCatalogResponse = {
  modules?: Array<{
    id?: string
    label?: string
    fields?: Array<{ key?: string; anchor?: string; description?: string; current_value?: unknown }>
    rule_keys?: string[]
    prompt_keys?: string[]
  }>
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

const MODULE_ITEMS: Array<{ id: ModuleTab; label: { zh: string; en: string }; desc: { zh: string; en: string } }> = [
  {
    id: 'discovery',
    label: { zh: '科学发现', en: 'Discovery' },
    desc: { zh: '问题挖掘批处理参数。', en: 'Question mining batch parameters.' },
  },
  {
    id: 'similarity',
    label: { zh: '相似性', en: 'Similarity' },
    desc: { zh: '命题分组与聚类行为。', en: 'Proposition grouping and clustering behavior.' },
  },
  {
    id: 'schema',
    label: { zh: '抽取策略', en: 'Extraction Policy' },
    desc: { zh: 'Schema 规则与提示词控制。', en: 'Schema rules and prompt controls.' },
  },
]

function asNumber(value: unknown, fallback: number) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return n
}

function asBoolean(value: unknown, fallback: boolean) {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') {
    const t = value.trim().toLowerCase()
    if (t === 'true' || t === '1' || t === 'on' || t === 'yes') return true
    if (t === 'false' || t === '0' || t === 'off' || t === 'no') return false
  }
  return fallback
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

function normalizeTurn(raw: unknown): AssistantTurn | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Record<string, unknown>
  const id = String(row.id ?? '').trim()
  const goal = String(row.goal ?? '').trim()
  const createdAt = String(row.created_at ?? '').trim()
  if (!id || !goal || !createdAt) return null
  const suggestionsRaw = Array.isArray(row.suggestions) ? row.suggestions : []
  const suggestions: AssistantSuggestion[] = suggestionsRaw
    .filter((item) => item && typeof item === 'object')
    .map((item) => item as Record<string, unknown>)
    .map((item) => ({
      module: String(item.module ?? ''),
      key: String(item.key ?? ''),
      anchor: String(item.anchor ?? ''),
      suggested_value: String(item.suggested_value ?? ''),
      rationale: String(item.rationale ?? ''),
      focus_key: item.focus_key == null ? null : String(item.focus_key),
      caution: item.caution == null ? null : String(item.caution),
    }))
    .filter((item) => item.anchor.trim() && item.module.trim() && item.key.trim())

  return {
    id,
    created_at: createdAt,
    goal,
    used_llm: Boolean(row.used_llm),
    suggestions,
    error: row.error == null ? undefined : String(row.error),
  }
}

function loadStoredTurns(): AssistantTurn[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(CHAT_TURNS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeTurn).filter((x): x is AssistantTurn => Boolean(x)).slice(0, MAX_CHAT_TURNS)
  } catch {
    return []
  }
}

function loadStoredGoal() {
  if (typeof window === 'undefined') return 'Make extraction stricter and reduce noisy claims while keeping recall stable.'
  const raw = window.localStorage.getItem(CHAT_GOAL_STORAGE_KEY)
  const goal = String(raw ?? '').trim()
  return goal || 'Make extraction stricter and reduce noisy claims while keeping recall stable.'
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
  const discoveryRaw = raw?.modules?.discovery as Partial<DiscoveryConfig> | undefined
  const similarityRaw = raw?.modules?.similarity as Partial<SimilarityConfig> | undefined
  return {
    version: asNumber(raw?.version, 1),
    updated_at: String(raw?.updated_at ?? ''),
    modules: {
      discovery: {
        domain: String(discoveryRaw?.domain ?? 'granular_flow'),
        dry_run: asBoolean(discoveryRaw?.dry_run, true),
        max_gaps: Math.max(1, Math.min(64, asNumber(discoveryRaw?.max_gaps, 8))),
        candidates_per_gap: Math.max(1, Math.min(3, asNumber(discoveryRaw?.candidates_per_gap, 2))),
        use_llm: asBoolean(discoveryRaw?.use_llm, true),
        hop_order: Math.max(1, Math.min(3, asNumber(discoveryRaw?.hop_order, 2))),
        adjacent_samples: Math.max(0, Math.min(30, asNumber(discoveryRaw?.adjacent_samples, 6))),
        random_samples: Math.max(0, Math.min(30, asNumber(discoveryRaw?.random_samples, 2))),
        rag_top_k: Math.max(1, Math.min(8, asNumber(discoveryRaw?.rag_top_k, 4))),
        prompt_optimize: asBoolean(discoveryRaw?.prompt_optimize, true),
        community_method: (String(discoveryRaw?.community_method ?? 'hybrid') as DiscoveryConfig['community_method']) ?? 'hybrid',
        community_samples: Math.max(0, Math.min(30, asNumber(discoveryRaw?.community_samples, 4))),
        prompt_optimization_method: (String(
          discoveryRaw?.prompt_optimization_method ?? 'rl_bandit',
        ) as DiscoveryConfig['prompt_optimization_method']) ?? 'rl_bandit',
      },
      similarity: {
        group_clustering_method: (String(
          similarityRaw?.group_clustering_method ?? 'hybrid',
        ) as SimilarityConfig['group_clustering_method']) ?? 'hybrid',
        group_clustering_threshold: Math.max(0, Math.min(1, asNumber(similarityRaw?.group_clustering_threshold, 0.85))),
      },
    },
  }
}

function fallbackCatalog(): ConfigCatalogResponse {
  return {
    modules: [
      { id: 'discovery', label: 'Discovery', fields: [] },
      { id: 'similarity', label: 'Similarity', fields: [] },
      { id: 'schema', label: 'Extraction Policy', fields: [], rule_keys: [], prompt_keys: [] },
    ],
  }
}

export default function ConfigCenterPage() {
  const { locale, t } = useI18n()
  const [active, setActive] = useState<ModuleTab>('discovery')
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
  const [assistantWidth, setAssistantWidth] = useState<number | null>(() => loadStoredAssistantWidth())
  const [isResizingAssistant, setIsResizingAssistant] = useState(false)
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

      if (profileRes.status !== 'fulfilled') {
        throw profileRes.reason
      }

      setProfile(normalizeProfile(profileRes.value.profile))

      if (catalogRes.status === 'fulfilled') {
        setCatalog(catalogRes.value ?? fallbackCatalog())
      } else {
        setCatalog(fallbackCatalog())
        setWarning(t('当前后端未提供 Catalog 接口，核心配置编辑功能仍可使用。', 'Catalog endpoint is unavailable on the connected backend. Core config editing still works.'))
      }
    } catch (e: unknown) {
      setError(parseError(e))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(CHAT_TURNS_STORAGE_KEY, JSON.stringify(assistantTurns.slice(0, MAX_CHAT_TURNS)))
    } catch {
      // ignore persistence failures
    }
  }, [assistantTurns])

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

  const clampAssistantWidth = useCallback((rawWidth: number) => {
    const min = assistantMinWidth
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? (typeof window !== 'undefined' ? window.innerWidth : 1600)
    const max = Math.min(780, Math.max(min + 40, layoutWidth - 520))
    return Math.max(min, Math.min(max, Math.round(rawWidth)))
  }, [assistantMinWidth])

  function startAssistantResize(event: React.PointerEvent<HTMLButtonElement>) {
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
    const el = document.getElementById(domId)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(() => {
      setFlashAnchor((prev) => (prev === domId ? '' : prev))
    }, 1600)
  }

  function jumpToSuggestion(row: AssistantSuggestion) {
    const anchor = String(row.anchor ?? '')
    const focusKey = String(row.focus_key ?? '').trim() || null
    if (anchor.startsWith('discovery.')) {
      setActive('discovery')
      flashTo(anchor)
      return
    }
    if (anchor.startsWith('similarity.')) {
      setActive('similarity')
      flashTo(anchor)
      return
    }
    if (anchor.startsWith('schema.')) {
      setActive('schema')
      setSchemaJumpTarget(anchor)
      setSchemaJumpFocusKey(focusKey)
      setJumpNonce((v) => v + 1)
    }
  }

  function updateDiscovery<K extends keyof DiscoveryConfig>(key: K, value: DiscoveryConfig[K]) {
    setProfile((prev) => ({ ...prev, modules: { ...prev.modules, discovery: { ...prev.modules.discovery, [key]: value } } }))
  }

  function updateSimilarity<K extends keyof SimilarityConfig>(key: K, value: SimilarityConfig[K]) {
    setProfile((prev) => ({ ...prev, modules: { ...prev.modules, similarity: { ...prev.modules.similarity, [key]: value } } }))
  }

  async function saveProfile() {
    setSaving(true)
    setError('')
    setInfo('')
    try {
      const payload = { modules: profile.modules }
      const res = await apiPut<ConfigProfileResponse>('/config-center/profile', payload)
      setProfile(normalizeProfile(res.profile))
      setInfo(t('配置已保存。', 'Configuration profile saved.'))
    } catch (e: unknown) {
      setError(parseError(e))
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
      const rows = Array.isArray(res.suggestions) ? res.suggestions : []
      const turn: AssistantTurn = {
        id: makeTurnId(),
        created_at: new Date().toISOString(),
        goal: prompt,
        used_llm: Boolean(res.used_llm),
        suggestions: rows,
      }
      setAssistantTurns((prev) => [turn, ...prev].slice(0, MAX_CHAT_TURNS))
      setGoal('')
    } catch (e: unknown) {
      const msg = parseError(e)
      const turn: AssistantTurn = {
        id: makeTurnId(),
        created_at: new Date().toISOString(),
        goal: prompt,
        used_llm: false,
        suggestions: [],
        error: msg,
      }
      setAssistantTurns((prev) => [turn, ...prev].slice(0, MAX_CHAT_TURNS))
      setError(msg)
    } finally {
      setAssistantBusy(false)
    }
  }

  function applySuggestion(row: AssistantSuggestion) {
    const anchor = String(row.anchor ?? '')
    const value = String(row.suggested_value ?? '').trim()
    if (anchor.startsWith('discovery.')) {
      const key = anchor.slice('discovery.'.length) as keyof DiscoveryConfig
      if (key === 'domain' || key === 'community_method' || key === 'prompt_optimization_method') {
        updateDiscovery(key, value as DiscoveryConfig[typeof key])
      } else if (key === 'dry_run' || key === 'use_llm' || key === 'prompt_optimize') {
        updateDiscovery(key, asBoolean(value, profile.modules.discovery[key]) as DiscoveryConfig[typeof key])
      } else {
        updateDiscovery(key, asNumber(value, profile.modules.discovery[key] as number) as DiscoveryConfig[typeof key])
      }
      setActive('discovery')
      flashTo(anchor)
      setInfo(t(`已应用建议到 ${anchor}。请保存配置以持久化。`, `Applied suggestion to ${anchor}. Save profile to persist.`))
      return
    }
    if (anchor.startsWith('similarity.')) {
      const key = anchor.slice('similarity.'.length) as keyof SimilarityConfig
      if (key === 'group_clustering_method') {
        updateSimilarity(key, value as SimilarityConfig[typeof key])
      } else {
        updateSimilarity(key, asNumber(value, profile.modules.similarity[key] as number) as SimilarityConfig[typeof key])
      }
      setActive('similarity')
      flashTo(anchor)
      setInfo(t(`已应用建议到 ${anchor}。请保存配置以持久化。`, `Applied suggestion to ${anchor}. Save profile to persist.`))
    }
  }

  const schemaRuleKeys = useMemo(() => {
    const schema = (catalog.modules ?? []).find((m) => String(m?.id ?? '') === 'schema')
    return schema?.rule_keys ?? []
  }, [catalog.modules])

  const schemaPromptKeys = useMemo(() => {
    const schema = (catalog.modules ?? []).find((m) => String(m?.id ?? '') === 'schema')
    return schema?.prompt_keys ?? []
  }, [catalog.modules])

  const schemaRulePreview = useMemo(() => schemaRuleKeys.slice(0, 18), [schemaRuleKeys])
  const schemaPromptPreview = useMemo(() => schemaPromptKeys.slice(0, 18), [schemaPromptKeys])

  return (
    <div className="page cc-page">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">{t('配置中心', 'Config Center')}</h2>
          <div className="pageSubtitle">
            {t(
              '统一管理科学发现、聚类、抽取策略与提示词调优配置。',
              'Unified operations configuration for discovery, clustering, extraction policy, and prompt tuning.',
            )}
          </div>
          <div className="metaLine">{t('版本', 'Version')} v{profile.version} - {t('更新时间', 'Updated')} {profile.updated_at || '-'}</div>
        </div>
        <div className="pageActions">
          <button className="btn" disabled={loading} onClick={() => void refreshAll()}>
            {loading ? t('刷新中...', 'Refreshing...') : t('刷新', 'Refresh')}
          </button>
          <button className="btn btnPrimary" disabled={saving} onClick={() => void saveProfile()}>
            {saving ? t('保存中...', 'Saving...') : t('保存配置', 'Save Profile')}
          </button>
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}
      {warning && <div className="cc-warning-box">{warning}</div>}
      {info && <div className="infoBox">{info}</div>}

      <div
        ref={layoutRef}
        className={`cc-layout${active === 'schema' ? ' cc-layout--schema' : ''}`}
        style={{ ['--cc-assistant-w' as string]: `${effectiveAssistantWidth}px` }}
      >
        <section className="cc-main">
          <div className="cc-module-tabs" role="tablist" aria-label={t('配置模块', 'Config Modules')}>
            {MODULE_ITEMS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={active === item.id}
                className={`cc-module-tab${active === item.id ? ' is-active' : ''}`}
                onClick={() => setActive(item.id)}
                title={t(item.desc.zh, item.desc.en)}
              >
                <span>{t(item.label.zh, item.label.en)}</span>
                <small>{t(item.desc.zh, item.desc.en)}</small>
              </button>
            ))}
          </div>

          {active === 'discovery' && (
            <section className="panel">
              <div className="panelHeader">
                <div className="panelTitle">{t('科学发现参数', 'Discovery Parameters')}</div>
              </div>
              <div className="panelBody cc-grid">
                <label id="cfg-discovery-domain" className={`cc-field${flashAnchor === 'cfg-discovery-domain' ? ' is-flash' : ''}`}>
                  <span className="cc-label">{t('研究主题域（domain）', 'domain')}</span>
                  <input className="input" value={profile.modules.discovery.domain} onChange={(e) => updateDiscovery('domain', e.target.value)} />
                  <span className="cc-help">{t('用于筛选 gap seed 的研究主题或领域标识。', 'Topic or domain key used by gap seed filtering.')}</span>
                </label>

                <label id="cfg-discovery-max_gaps" className={`cc-field${flashAnchor === 'cfg-discovery-max_gaps' ? ' is-flash' : ''}`}>
                  <span className="cc-label">{t('候选空缺数上限（max_gaps）', 'max_gaps')}</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={64}
                    value={profile.modules.discovery.max_gaps}
                    onChange={(e) => updateDiscovery('max_gaps', Math.max(1, Math.min(64, Number(e.target.value || 8))))}
                  />
                  <span className="cc-help">{t('每次发现批处理中要处理的 gap seed 数量上限。', 'How many gap seeds are processed in each discovery batch.')}</span>
                </label>

                <label
                  id="cfg-discovery-candidates_per_gap"
                  className={`cc-field${flashAnchor === 'cfg-discovery-candidates_per_gap' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('每个空缺候选问题数（candidates_per_gap）', 'candidates_per_gap')}</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={3}
                    value={profile.modules.discovery.candidates_per_gap}
                    onChange={(e) => updateDiscovery('candidates_per_gap', Math.max(1, Math.min(3, Number(e.target.value || 2))))}
                  />
                  <span className="cc-help">{t('每个 gap seed 生成的问题候选数量。', 'Question candidates generated per gap.')}</span>
                </label>

                <label id="cfg-discovery-hop_order" className={`cc-field${flashAnchor === 'cfg-discovery-hop_order' ? ' is-flash' : ''}`}>
                  <span className="cc-label">{t('作者跳数深度（hop_order）', 'hop_order')}</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={3}
                    value={profile.modules.discovery.hop_order}
                    onChange={(e) => updateDiscovery('hop_order', Math.max(1, Math.min(3, Number(e.target.value || 2))))}
                  />
                  <span className="cc-help">{t('灵感采样时在作者关系图上的扩展跳数。', 'Author-hop graph expansion depth for inspiration sampling.')}</span>
                </label>

                <label
                  id="cfg-discovery-adjacent_samples"
                  className={`cc-field${flashAnchor === 'cfg-discovery-adjacent_samples' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('邻域采样数（adjacent_samples）', 'adjacent_samples')}</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={30}
                    value={profile.modules.discovery.adjacent_samples}
                    onChange={(e) => updateDiscovery('adjacent_samples', Math.max(0, Math.min(30, Number(e.target.value || 6))))}
                  />
                  <span className="cc-help">{t('从局部相邻图邻域抽取的采样数量。', 'Samples from adjacent local graph neighborhood.')}</span>
                </label>

                <label
                  id="cfg-discovery-random_samples"
                  className={`cc-field${flashAnchor === 'cfg-discovery-random_samples' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('随机探索采样数（random_samples）', 'random_samples')}</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={30}
                    value={profile.modules.discovery.random_samples}
                    onChange={(e) => updateDiscovery('random_samples', Math.max(0, Math.min(30, Number(e.target.value || 2))))}
                  />
                  <span className="cc-help">{t('用于提升覆盖多样性的随机探索采样数量。', 'Random exploration samples to improve diversity.')}</span>
                </label>

                <label id="cfg-discovery-rag_top_k" className={`cc-field${flashAnchor === 'cfg-discovery-rag_top_k' ? ' is-flash' : ''}`}>
                  <span className="cc-label">{t('RAG 证据片段数（rag_top_k）', 'rag_top_k')}</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={8}
                    value={profile.modules.discovery.rag_top_k}
                    onChange={(e) => updateDiscovery('rag_top_k', Math.max(1, Math.min(8, Number(e.target.value || 4))))}
                  />
                  <span className="cc-help">{t('注入到生成上下文中的证据片段数量。', 'Evidence chunk count injected into generation context.')}</span>
                </label>

                <label
                  id="cfg-discovery-community_method"
                  className={`cc-field${flashAnchor === 'cfg-discovery-community_method' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('社区采样策略（community_method）', 'community_method')}</span>
                  <select
                    className="input"
                    value={profile.modules.discovery.community_method}
                    onChange={(e) => updateDiscovery('community_method', e.target.value as DiscoveryConfig['community_method'])}
                  >
                    <option value="hybrid">{t('混合策略（hybrid）', 'hybrid')}</option>
                    <option value="louvain">{t('Louvain 社区（louvain）', 'louvain')}</option>
                    <option value="author_hop">{t('作者跳邻（author_hop）', 'author_hop')}</option>
                  </select>
                  <span className="cc-help">{t('用于选择灵感论文的社区采样策略。', 'Community strategy for selecting inspiration papers.')}</span>
                </label>

                <label
                  id="cfg-discovery-community_samples"
                  className={`cc-field${flashAnchor === 'cfg-discovery-community_samples' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('社区补充采样数（community_samples）', 'community_samples')}</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={30}
                    value={profile.modules.discovery.community_samples}
                    onChange={(e) => updateDiscovery('community_samples', Math.max(0, Math.min(30, Number(e.target.value || 4))))}
                  />
                  <span className="cc-help">{t('按当前社区策略额外补充的采样数量。', 'Additional samples from the selected community method.')}</span>
                </label>

                <label
                  id="cfg-discovery-prompt_optimization_method"
                  className={`cc-field${flashAnchor === 'cfg-discovery-prompt_optimization_method' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('提示词优化策略（prompt_optimization_method）', 'prompt_optimization_method')}</span>
                  <select
                    className="input"
                    value={profile.modules.discovery.prompt_optimization_method}
                    onChange={(e) => updateDiscovery('prompt_optimization_method', e.target.value as DiscoveryConfig['prompt_optimization_method'])}
                  >
                    <option value="rl_bandit">{t('Bandit 学习（rl_bandit）', 'rl_bandit')}</option>
                    <option value="heuristic">{t('启发式规则（heuristic）', 'heuristic')}</option>
                  </select>
                  <span className="cc-help">{t('候选生成阶段所使用的提示词优化方法。', 'Prompt optimizer policy during candidate generation.')}</span>
                </label>

                <label id="cfg-discovery-dry_run" className={`cc-field${flashAnchor === 'cfg-discovery-dry_run' ? ' is-flash' : ''}`}>
                  <span className="cc-label">{t('仅演练模式（dry_run）', 'dry_run')}</span>
                  <label className="pill cc-check">
                    <input type="checkbox" checked={profile.modules.discovery.dry_run} onChange={(e) => updateDiscovery('dry_run', e.target.checked)} />
                    <span>{t('只运行流程，不写入图谱产物', 'Run without writing graph artifacts')}</span>
                  </label>
                </label>

                <label id="cfg-discovery-use_llm" className={`cc-field${flashAnchor === 'cfg-discovery-use_llm' ? ' is-flash' : ''}`}>
                  <span className="cc-label">{t('启用大模型生成（use_llm）', 'use_llm')}</span>
                  <label className="pill cc-check">
                    <input type="checkbox" checked={profile.modules.discovery.use_llm} onChange={(e) => updateDiscovery('use_llm', e.target.checked)} />
                    <span>{t('启用 LLM 生成', 'Enable LLM generation')}</span>
                  </label>
                </label>

                <label
                  id="cfg-discovery-prompt_optimize"
                  className={`cc-field${flashAnchor === 'cfg-discovery-prompt_optimize' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('启用提示词优化循环（prompt_optimize）', 'prompt_optimize')}</span>
                  <label className="pill cc-check">
                    <input
                      type="checkbox"
                      checked={profile.modules.discovery.prompt_optimize}
                      onChange={(e) => updateDiscovery('prompt_optimize', e.target.checked)}
                    />
                    <span>{t('启用提示词优化迭代', 'Enable prompt optimization loop')}</span>
                  </label>
                </label>
              </div>
            </section>
          )}

          {active === 'similarity' && (
            <section className="panel">
              <div className="panelHeader">
                <div className="panelTitle">{t('相似性与聚类', 'Similarity and Clustering')}</div>
              </div>
              <div className="panelBody cc-grid cc-grid--compact">
                <label
                  id="cfg-similarity-group_clustering_method"
                  className={`cc-field${flashAnchor === 'cfg-similarity-group_clustering_method' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('命题分组方法（group_clustering_method）', 'group_clustering_method')}</span>
                  <select
                    className="input"
                    value={profile.modules.similarity.group_clustering_method}
                    onChange={(e) => updateSimilarity('group_clustering_method', e.target.value as SimilarityConfig['group_clustering_method'])}
                  >
                    <option value="hybrid">{t('混合策略（hybrid）', 'hybrid')}</option>
                    <option value="louvain">{t('Louvain 社区（louvain）', 'louvain')}</option>
                    <option value="agglomerative">{t('层次聚类（agglomerative）', 'agglomerative')}</option>
                  </select>
                  <span className="cc-help">{t('重建相似性时用于形成命题分组的方法。', 'How proposition groups are formed during similarity rebuild.')}</span>
                </label>

                <label
                  id="cfg-similarity-group_clustering_threshold"
                  className={`cc-field${flashAnchor === 'cfg-similarity-group_clustering_threshold' ? ' is-flash' : ''}`}
                >
                  <span className="cc-label">{t('分组阈值（group_clustering_threshold）', 'group_clustering_threshold')}</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={profile.modules.similarity.group_clustering_threshold}
                    onChange={(e) => updateSimilarity('group_clustering_threshold', Math.max(0, Math.min(1, Number(e.target.value || 0.85))))}
                  />
                  <span className="cc-help">{t('阈值越高，分组越紧、越保守。', 'Higher values produce tighter and more conservative clusters.')}</span>
                </label>
              </div>
            </section>
          )}

          {active === 'schema' && (
            <section className="cc-schema-wrap">
              <div className="panel">
                <div className="panelHeader">
                  <div className="panelTitle">{t('抽取策略助手索引', 'Extraction Policy Assistant Index')}</div>
                </div>
                <div className="panelBody cc-schema-index">
                  <div className="metaLine">
                    {t('该索引用于把助手跳转链接映射到 Schema 对应编辑区。', 'This index maps assistant jump links to schema edit areas.')}
                    <code> schema.rules_json </code>
                    {t('对应规则 JSON，', 'points to rule JSON and')}
                    <code> schema.prompts_json </code>
                    {t('对应提示词 JSON。', 'points to prompt JSON.')}
                  </div>
                  <div className="cc-schema-index-stats">
                    <span className="pill">{t('规则键', 'Rule Keys')}: {schemaRuleKeys.length}</span>
                    <span className="pill">{t('提示词键', 'Prompt Keys')}: {schemaPromptKeys.length}</span>
                    <button className="btn btnSmall" onClick={() => setShowSchemaKeyList((v) => !v)}>
                      {showSchemaKeyList ? t('隐藏键列表', 'Hide Key List') : t('显示键列表', 'Show Key List')}
                    </button>
                  </div>
                  {showSchemaKeyList && (
                    <div className="cc-schema-index-grid">
                      <div className="cc-schema-index-block">
                        <div className="kicker">{t('规则键预览', 'Rule Keys Preview')}</div>
                        <div className="cc-key-list">
                          {schemaRulePreview.map((k) => (
                            <span key={`rk-${k}`} className="cc-key-pill">
                              {k}
                            </span>
                          ))}
                        </div>
                        {schemaRuleKeys.length > schemaRulePreview.length && (
                          <div className="hint">{t(`其余 ${schemaRuleKeys.length - schemaRulePreview.length} 项...`, `and ${schemaRuleKeys.length - schemaRulePreview.length} more...`)}</div>
                        )}
                      </div>
                      <div className="cc-schema-index-block">
                        <div className="kicker">{t('提示词键预览', 'Prompt Keys Preview')}</div>
                        <div className="cc-key-list">
                          {schemaPromptPreview.map((k) => (
                            <span key={`pk-${k}`} className="cc-key-pill">
                              {k}
                            </span>
                          ))}
                        </div>
                        {schemaPromptKeys.length > schemaPromptPreview.length && (
                          <div className="hint">{t(`其余 ${schemaPromptKeys.length - schemaPromptPreview.length} 项...`, `and ${schemaPromptKeys.length - schemaPromptPreview.length} more...`)}</div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
              <SchemaPage jumpTarget={schemaJumpTarget} jumpFocusKey={schemaJumpFocusKey} jumpNonce={jumpNonce} />
            </section>
          )}
        </section>

        <button
          type="button"
          className={`cc-resizer${isResizingAssistant ? ' is-active' : ''}`}
          onPointerDown={startAssistantResize}
          aria-label="Resize assistant panel"
          aria-orientation="vertical"
        />

        <aside className="cc-assistant">
          <section className="panel cc-chat-panel">
            <div className="panelHeader">
              <div className="split">
                <div className="panelTitle">{t('LLM 运维助手', 'LLM Ops Assistant')}</div>
                <span className="badge">{t('对话', 'Chat')}</span>
              </div>
            </div>
            <div className="panelBody cc-chat-body">
              <div className="cc-chat-scroll">
                {assistantTurns.length === 0 ? (
                  <div className="metaLine">
                    {t('描述你的目标（精度、召回、速度），助手会给出参数建议和跳转链接。', 'Describe your target (precision, recall, speed). The assistant will propose parameters and jump links.')}
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
                          <div className="kicker">LogicKG Assistant</div>
                          <span className={`badge${turn.used_llm ? ' badgeOk' : ''}`}>{turn.used_llm ? 'LLM' : 'Heuristic'}</span>
                        </div>
                        <div className="metaLine">{new Date(turn.created_at).toLocaleString()}</div>

                        {turn.error ? (
                          <div className="hint">{t('请求失败', 'Request failed')}: {turn.error}</div>
                        ) : (
                          <div className="cc-chat-suggestion-list">
                            {turn.suggestions.map((row, idx) => (
                              <div key={`${turn.id}-${row.anchor}-${idx}`} className="cc-chat-suggestion-card">
                                <div className="split">
                                  <button type="button" className="cc-link-btn" onClick={() => jumpToSuggestion(row)}>
                                    {row.anchor}
                                  </button>
                                  <span className="badge">{row.module}</span>
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
                                  {(row.anchor.startsWith('discovery.') || row.anchor.startsWith('similarity.')) && (
                                    <button className="btn btnSmall" onClick={() => applySuggestion(row)}>
                                      {t('应用参数', 'Apply Value')}
                                    </button>
                                  )}
                                </div>
                              </div>
                            ))}
                            {turn.suggestions.length === 0 && <div className="metaLine">{t('当前查询没有返回建议。', 'No suggestions returned for this query.')}</div>}
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
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder={t('例如：提高图谱抽取精度并减少缺证据论断', 'Example: tighten graph extraction precision and reduce unsupported claims')}
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
                <div className="hint">{t('建议支持跳转定位；可直接应用参数并保存。', 'Suggestions support jump links. Parameters can be applied directly, then saved to persist.')}</div>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
