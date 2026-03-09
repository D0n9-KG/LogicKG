import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { apiBaseUrl, apiGet, apiPatch, apiPost } from '../api'
import MarkdownView from '../components/MarkdownView'
import SignalGraph, { type SignalGraphEdge, type SignalGraphNode } from '../components/SignalGraph'
import { splitOriginalTextForHighlight } from './originalTextHighlight'
import { formatOriginalTextMarkdown } from './originalTextFormatting'
import { TERMS } from '../ui/terms'

type PaperCore = {
  paper_id: string
  doi?: string
  year?: number
  title?: string
  paper_source?: string
  storage_dir?: string
  ingested?: boolean

  title_machine?: string
  year_machine?: number
  title_source?: string
  year_source?: string

  review_pending_task_id?: string | null
  review_resolved_task_id?: string | null
  review_needs_review?: boolean
  review_pending_count?: number

  phase1_quality?: Record<string, unknown>
  phase1_gate_passed?: boolean
  phase1_quality_tier?: string
  phase1_quality_tier_score?: number
}

type PaperDetail = {
  paper: PaperCore
  schema?: {
    paper_type: string
    version: number
    steps: Array<{ id: string; label_zh?: string; label_en?: string; enabled?: boolean; order?: number }>
    claim_kinds: Array<{ id: string; label_zh?: string; label_en?: string; enabled?: boolean }>
    rules?: Record<string, unknown>
  } | null
  stats: { chunk_count?: number; ref_count?: number }
  logic_steps?: Array<{
    step_type: string
    summary: string
    confidence?: number
    order?: number | null
    summary_machine?: string | null
    confidence_machine?: number | null
    summary_human?: string | null
    source?: string | null
    pending_machine_summary?: string | null
    pending_machine_confidence?: number | null
    evidence?: Array<{ chunk_id: string; section?: string | null; start_line?: number | null; end_line?: number | null; kind?: string | null; snippet?: string; weak?: boolean; source?: string | null }> | null
    evidence_machine?: Array<{ chunk_id: string; section?: string | null; start_line?: number | null; end_line?: number | null; kind?: string | null; snippet?: string; weak?: boolean; source?: string | null }> | null
    evidence_human?: Array<{ chunk_id: string; section?: string | null; start_line?: number | null; end_line?: number | null; kind?: string | null; snippet?: string; weak?: boolean; source?: string | null }> | null
  }>
  claims?: Array<{
    claim_id?: string | null
    claim_key: string
    text: string
    confidence?: number | null
    step_type?: string | null
    kinds?: string[] | null
    evidence?: Array<{ chunk_id: string; section?: string | null; start_line?: number | null; end_line?: number | null; kind?: string | null; snippet?: string; weak?: boolean; source?: string | null }> | null
    evidence_machine?: Array<{ chunk_id: string; section?: string | null; start_line?: number | null; end_line?: number | null; kind?: string | null; snippet?: string; weak?: boolean; source?: string | null }> | null
    evidence_human?: Array<{ chunk_id: string; section?: string | null; start_line?: number | null; end_line?: number | null; kind?: string | null; snippet?: string; weak?: boolean; source?: string | null }> | null
    targets?: Array<{ paper_id: string; doi?: string | null; title?: string | null; year?: number | null }> | null
    text_machine?: string | null
    confidence_machine?: number | null
    text_human?: string | null
    source?: string | null
    pending_machine_text?: string | null
    pending_machine_confidence?: number | null
  }>
  figures?: Array<{
    figure_id: string
    rel_path: string
    filename: string
    img_line?: number
    caption_text?: string | null
  }>
  outgoing_cites: Array<{
    cited_paper_id: string
    cited_doi?: string
    cited_title?: string
    total_mentions?: number
    ref_nums?: number[]
    purpose_labels?: string[]
    purpose_scores?: number[]
    purpose_labels_machine?: string[] | null
    purpose_scores_machine?: number[] | null
    purpose_labels_human?: string[] | null
    purpose_scores_human?: number[] | null
    purpose_source?: string | null
    pending_machine_purpose_labels?: string[] | null
    pending_machine_purpose_scores?: number[] | null
  }>
  unresolved: Array<{
    ref_id: string
    raw: string
    total_mentions?: number
    ref_nums?: number[]
  }>
}

type TaskInfo = {
  task_id: string
  status?: string
  progress?: number
  stage?: string
} & Record<string, unknown>

const PURPOSES = [
  'Survey',
  'Background',
  'ProblemSetup',
  'Theory',
  'MethodUse',
  'DataTool',
  'BaselineCompare',
  'SupportEvidence',
  'CritiqueLimit',
  'ExtendImprove',
  'FutureDirection',
]

const PURPOSE_LABELS: Record<string, string> = {
  Survey: '综述',
  Background: '背景',
  ProblemSetup: '问题设置',
  Theory: '理论',
  MethodUse: '方法使用',
  DataTool: '数据/工具',
  BaselineCompare: '基线对比',
  SupportEvidence: '支持证据',
  CritiqueLimit: '批判/局限',
  ExtendImprove: '扩展/改进',
  FutureDirection: '未来方向',
}

const STEP_TYPE_LABELS: Record<string, string> = {
  Background: '背景',
  Problem: '问题',
  Method: '方法',
  Experiment: '实验',
  Result: '结果',
  Conclusion: '结论',
}

function stepLabel(schema: PaperDetail['schema'] | null | undefined, stepType: string) {
  const steps = schema?.steps ?? []
  const s = steps.find((x) => String(x.id) === String(stepType))
  const zh = String(s?.label_zh ?? STEP_TYPE_LABELS[stepType] ?? stepType)
  const en = String(s?.label_en ?? '')
  if (en && en !== zh) return `${zh}(${en})`
  return zh
}

function kindLabel(schema: PaperDetail['schema'] | null | undefined, kindId: string) {
  const kinds = schema?.claim_kinds ?? []
  const k = kinds.find((x) => String(x.id) === String(kindId))
  const zh = String(k?.label_zh ?? kindId)
  const en = String(k?.label_en ?? '')
  if (en && en !== zh) return `${zh}(${en})`
  return zh
}

function clamp01(v: number) {
  if (Number.isNaN(v)) return 0
  return Math.max(0, Math.min(1, v))
}

function shorten(text: string | null | undefined, maxLen: number) {
  const t = (text ?? '').replace(/\s+/g, ' ').trim()
  if (!t) return ''
  if (t.length <= maxLen) return t
  return `${t.slice(0, maxLen - 1)}…`
}

function splitSubfigureCaption(captionText: string): string[] | null {
  const raw = String(captionText ?? '').trim()
  if (!raw) return null

  // Detect repeated subfigure markers like "(a) ... (b) ...", allowing full-width parentheses.
  const re = /(\(|（)\s*([a-z])\s*(\)|）)/gi
  const matches: Array<{ idx: number; label: string }> = []
  for (const m of raw.matchAll(re)) {
    const label = String(m[2] ?? '').toLowerCase()
    const idx = Number(m.index ?? -1)
    if (idx >= 0) matches.push({ idx, label })
  }
  if (matches.length < 2) return null

  // Keep unique labels in order; require at least 2 distinct labels to avoid false positives.
  const uniq: Array<{ idx: number; label: string }> = []
  const seen = new Set<string>()
  for (const x of matches) {
    if (seen.has(x.label)) continue
    seen.add(x.label)
    uniq.push(x)
  }
  if (uniq.length < 2) return null

  // Split into segments between markers.
  const segments: string[] = []
  for (let i = 0; i < uniq.length; i++) {
    const start = uniq[i].idx
    const end = i + 1 < uniq.length ? uniq[i + 1].idx : raw.length
    const seg = raw.slice(start, end).trim()
    if (seg) segments.push(seg)
  }
  return segments.length >= 2 ? segments : null
}

function taskStatusLabel(status: string | null | undefined) {
  const s = String(status ?? '')
  if (!s) return ''
  if (s === 'queued') return '排队中'
  if (s === 'running') return '进行中'
  if (s === 'succeeded') return '成功'
  if (s === 'failed') return '失败'
  if (s === 'canceled') return '已取消'
  return s
}

function taskStageLabel(stage: string | null | undefined) {
  const s = String(stage ?? '')
  if (!s) return ''
  if (s.includes('crossref')) return `${TERMS.crossref} 解析`
  if (s.includes('neo4j_clear')) return '清理 Neo4j'
  if (s.includes('neo4j_write')) return '写入 Neo4j'
  if (s.includes('llm')) return `${TERMS.llm} 抽取`
  if (s.includes('faiss')) return `${TERMS.faiss} 重建`
  if (s === 'done') return '完成'
  if (s === 'canceled') return '已取消'
  if (s === 'failed') return '失败'
  return s
}

type HighlightRange = { start: number; end: number } | null

function OriginalTextPanel({
  paperId,
  mode,
  onClose,
  highlightRange,
  onPopout,
}: {
  paperId: string
  mode: 'sidebar' | 'fullwidth' | 'modal'
  onClose?: () => void
  highlightRange?: HighlightRange
  onPopout?: () => void
}) {
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const hlRef = useRef<HTMLDivElement>(null)
  const fadeTimer = useRef<number | null>(null)
  const [fading, setFading] = useState(false)
  const prepareContentLoad = useCallback(() => {
    setContent(null)
    setLoading(true)
    setErr('')
  }, [])
  const resetFading = useCallback(() => {
    setFading(false)
  }, [])

  useEffect(() => {
    if (!paperId) return
    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect
    prepareContentLoad()
    fetch(`${apiBaseUrl()}/papers/${encodeURIComponent(paperId)}/content`)
      .then((res) => {
        if (!res.ok) throw new Error(res.status === 404 ? '该论文暂无原文 Markdown' : `加载失败 (${res.status})`)
        return res.text()
      })
      .then((text) => { if (!cancelled) setContent(text) })
      .catch((e: unknown) => { if (!cancelled) setErr(String((e as { message?: unknown } | null)?.message ?? e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [paperId, prepareContentLoad])

  // Scroll highlight into view within the scroll container only
  // Re-trigger when loading finishes (content may not be in DOM yet on first fire)
  useEffect(() => {
    if (!highlightRange || loading) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    resetFading()
    const raf = requestAnimationFrame(() => {
      const container = scrollContainerRef.current
      const el = hlRef.current
      if (container && el) {
        const containerRect = container.getBoundingClientRect()
        const elRect = el.getBoundingClientRect()
        const offset = elRect.top - containerRect.top + container.scrollTop - containerRect.height / 3
        container.scrollTo({ top: Math.max(0, offset), behavior: 'smooth' })
      }
    })
    if (fadeTimer.current) clearTimeout(fadeTimer.current)
    fadeTimer.current = window.setTimeout(() => setFading(true), 3000)
    return () => {
      cancelAnimationFrame(raf)
      if (fadeTimer.current) clearTimeout(fadeTimer.current)
    }
  }, [highlightRange, loading, resetFading])

  // Split content into 3 segments for highlighting
  const segments = useMemo(() => {
    return splitOriginalTextForHighlight(content ?? '', highlightRange)
  }, [content, highlightRange])

  const renderContent = () => {
    if (loading) return <div className="metaLine">加载中...</div>
    if (err) return <div className="errorBox">{err}</div>
    if (content === null && !loading && !err) return <div className="metaLine">暂无原文内容。</div>
    if (!content) return null

    if (segments) {
      return (
        <>
          {segments.before && <MarkdownView markdown={formatOriginalTextMarkdown(segments.before)} paperId={paperId} className="pdOriginalMarkdown" />}
          <div ref={hlRef} className={`pdHighlightBlock${fading ? ' pdHighlightBlock--fade' : ''}`}>
            <MarkdownView markdown={formatOriginalTextMarkdown(segments.highlight)} paperId={paperId} className="pdOriginalMarkdown" />
          </div>
          {segments.after && <MarkdownView markdown={formatOriginalTextMarkdown(segments.after)} paperId={paperId} className="pdOriginalMarkdown" />}
        </>
      )
    }
    return <MarkdownView markdown={formatOriginalTextMarkdown(content)} paperId={paperId} className="pdOriginalMarkdown" />
  }

  if (mode === 'modal') {
    return (
      <div className="modalOverlay" onClick={onClose}>
        <div className="modal" style={{ maxWidth: 900 }} onClick={(e) => e.stopPropagation()}>
          <div className="modalHeader">
            <div className="modalTitle">原文 Markdown</div>
            <button className="btn btnSmall" onClick={onClose}>关闭</button>
          </div>
          <div className="modalBody" ref={scrollContainerRef}>{renderContent()}</div>
        </div>
      </div>
    )
  }

  if (mode === 'fullwidth') {
    return (
      <div className="panel">
        <div className="panelHeader">
          <div className="split">
            <div className="panelTitle">原文 Markdown</div>
            {onPopout && <button className="btn btnSmall" onClick={onPopout}>弹出窗口</button>}
          </div>
        </div>
        <div className="panelBody" ref={scrollContainerRef}>{renderContent()}</div>
      </div>
    )
  }

  return (
    <div className="pdWorkspaceSidebar">
      <div className="pdSidebarHeader">
        <span className="panelTitle">原文</span>
        <div className="row" style={{ gap: 6 }}>
          {onPopout && <button className="btn btnSmall" onClick={onPopout}>弹出</button>}
          {onClose && <button className="btn btnSmall" onClick={onClose}>关闭</button>}
        </div>
      </div>
      <div className="pdSidebarBody" ref={scrollContainerRef}>
        {renderContent()}
      </div>
    </div>
  )
}

export default function PaperDetailPage() {
  const { paperId } = useParams()
  const id = paperId ? decodeURIComponent(paperId) : ''

  type PaperTab = 'logic' | 'claims' | 'cites' | 'figures' | 'content'
  type GraphMeta = {
    title: string
    detail: string
    tab?: PaperTab
  }
  const [searchParams, setSearchParams] = useSearchParams()
  const tab0 = String(searchParams.get('tab') || 'logic') as PaperTab
  const tab: PaperTab = (['logic', 'claims', 'cites', 'figures', 'content'] as const).includes(tab0) ? tab0 : 'logic'
  const isPinned = searchParams.get('pin') === '1'
  function selectTab(t: PaperTab) {
    const next = new URLSearchParams(searchParams)
    next.set('tab', t)
    setSearchParams(next, { replace: true })
  }
  function togglePin(force?: boolean) {
    const next = new URLSearchParams(searchParams)
    const val = force !== undefined ? force : !isPinned
    if (val) { next.set('pin', '1') } else { next.delete('pin') }
    setSearchParams(next, { replace: true })
  }

  const [highlightRange, setHighlightRange] = useState<HighlightRange>(null)
  const [showContentModal, setShowContentModal] = useState(false)
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState('paper:root')

  function locateEvidence(startLine?: number | null, endLine?: number | null) {
    if (typeof startLine !== 'number') return
    togglePin(true)
    setHighlightRange({ start: startLine, end: endLine ?? startLine })
  }

  // Reset highlight and modal when paper changes
  useEffect(() => { setHighlightRange(null); setShowContentModal(false) }, [id])
  useEffect(() => {
    setSelectedGraphNodeId('paper:root')
  }, [id])

  const [detail, setDetail] = useState<PaperDetail | null>(null)
  const [error, setError] = useState<string>('')
  const [busy, setBusy] = useState<string>('') // cite purpose update busy key
  const [info, setInfo] = useState<string>('')

  const [rebuildTaskId, setRebuildTaskId] = useState<string>('')
  const [rebuildTask, setRebuildTask] = useState<TaskInfo | null>(null)
  const [rebuildFaiss, setRebuildFaiss] = useState<boolean>(true)
  const [rebuildBusy, setRebuildBusy] = useState<boolean>(false)

  const [activeFigureGroup, setActiveFigureGroup] = useState<
    | {
        title: string
        caption?: string | null
        items: Array<{ src: string; title: string; filename: string }>
      }
    | null
  >(null)
  const [metaEditOpen, setMetaEditOpen] = useState<boolean>(false)
  const [metaTitle, setMetaTitle] = useState<string>('')
  const [metaYear, setMetaYear] = useState<string>('')
  const [reviewOpen, setReviewOpen] = useState<boolean>(false)
  const [reviewChoice, setReviewChoice] = useState<Record<string, 'keep_human' | 'use_machine' | 'clear'>>({})
  const [reviewBusy, setReviewBusy] = useState<boolean>(false)
  const [logicEdit, setLogicEdit] = useState<Record<string, boolean>>({})
  const [logicDraft, setLogicDraft] = useState<Record<string, string>>({})
  const [claimEdit, setClaimEdit] = useState<Record<string, boolean>>({})
  const [claimDraft, setClaimDraft] = useState<Record<string, string>>({})
  const [newClaimText, setNewClaimText] = useState<string>('')

  const [evidenceEditKind, setEvidenceEditKind] = useState<'claim' | 'logic'>('claim')
  const [evidenceEditKey, setEvidenceEditKey] = useState<string>('')
  const [evidenceEditTitle, setEvidenceEditTitle] = useState<string>('')
  const [evidenceQuery, setEvidenceQuery] = useState<string>('')
  const [evidenceBusy, setEvidenceBusy] = useState<boolean>(false)
  const [evidenceResults, setEvidenceResults] = useState<
    Array<{
      chunk_id: string
      section?: string | null
      start_line?: number | null
      end_line?: number | null
      kind?: string | null
      score?: number | null
      snippet?: string
      text?: string
      text_truncated?: boolean
    }>
  >([])
  const [evidenceSelected, setEvidenceSelected] = useState<Record<string, boolean>>({})
  const [evidenceExpanded, setEvidenceExpanded] = useState<Record<string, boolean>>({})

  // md state removed — OriginalTextPanel handles its own fetch

  async function refresh() {
    const r = await apiGet<PaperDetail>(`/graph/paper/${encodeURIComponent(id)}`)
    setDetail(r)
    setInfo('')
  }

  useEffect(() => {
    if (!id) return
    refresh().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    const p = detail?.paper
    if (!p) return
    setMetaTitle(String(p.title ?? ''))
    setMetaYear(p.year === undefined || p.year === null ? '' : String(p.year))
  }, [detail?.paper])

  useEffect(() => {
    if (!rebuildTaskId) return
    let alive = true
    let stopped = false
    let iv: ReturnType<typeof setInterval> | null = null
    const stop = () => {
      if (stopped) return
      stopped = true
      alive = false
      if (iv) clearInterval(iv)
      iv = null
    }
    const tick = async () => {
      const t = await apiGet<TaskInfo>(`/tasks/${encodeURIComponent(rebuildTaskId)}`)
      if (!alive) return
      setRebuildTask(t)
      const status = String(t?.status ?? '')
      if (status && !['queued', 'running'].includes(status)) {
        await refresh()
        stop()
      }
    }
    tick().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
    iv = setInterval(() => tick().catch(() => {}), 1200)
    return () => {
      stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuildTaskId])

  const title = useMemo(() => detail?.paper?.title ?? detail?.paper?.paper_source ?? id, [detail, id])
  const paperIdForImages = useMemo(() => String(detail?.paper?.paper_id ?? id), [detail?.paper?.paper_id, id])
  const stats = useMemo(() => {
    const p = detail?.paper
    const s = detail?.stats ?? {}
    return {
      paperId: p?.paper_id ?? id,
      doi: p?.doi ?? '',
      year: p?.year ?? '',
      chunks: s.chunk_count ?? 0,
      refs: s.ref_count ?? 0,
      figures: (detail?.figures ?? []).length,
    }
  }, [detail, id])

  const figureGroups = useMemo(() => {
    const figs = (detail?.figures ?? []).slice().sort((a, b) => Number(a.img_line ?? 0) - Number(b.img_line ?? 0))
    if (!figs.length) return []

    const base = apiBaseUrl()
    const paperId = String(detail?.paper?.paper_id ?? id)

    function relToSrc(relPath: string): string {
      const rel = String(relPath ?? '').split('/').map((p) => encodeURIComponent(p)).join('/')
      return `${base}/papers/${encodeURIComponent(paperId)}/images/${rel}`
    }

    function extractFigureKey(captionText: string): string {
      const t = String(captionText ?? '').trim()
      if (!t) return ''
      const m = /^(fig\.?|figure|图)\s*(\d+)/i.exec(t)
      if (!m) return ''
      return `fig:${m[2]}`
    }

    const out: Array<{
      key: string
      title: string
      caption?: string | null
      items: Array<{ src: string; title: string; filename: string; imgLine: number }>
    }> = []

    let current: (typeof out)[number] | null = null
    let lastImgLine = 0
    const MAX_GAP = 6
    const MAX_KEY_SPAN = 25

    for (const f of figs) {
      const imgLine = Number(f.img_line ?? 0) || 0
      const caption = String(f.caption_text ?? '').trim()
      const key = extractFigureKey(caption)
      const withinGap = !!current && imgLine > 0 && lastImgLine > 0 && imgLine - lastImgLine <= MAX_GAP
      const withinKeySpan = !!current && !!current.key && imgLine > 0 && lastImgLine > 0 && imgLine - lastImgLine <= MAX_KEY_SPAN

      const item = {
        src: relToSrc(f.rel_path),
        title: caption ? caption.split('\n')[0] : f.filename,
        filename: f.filename,
        imgLine,
      }

      if (key) {
        if (current && current.key === key && (withinGap || withinKeySpan)) {
          current.items.push(item)
          if (!current.caption && caption) current.caption = caption
          if (caption && (!current.title || current.title === current.items[0]?.filename)) current.title = caption.split('\n')[0] || current.title
        } else {
          current = { key, title: caption.split('\n')[0] || f.filename, caption: caption || null, items: [item] }
          out.push(current)
        }
      } else if (current && (withinGap || withinKeySpan)) {
        current.items.push(item)
        if (!current.caption && caption) current.caption = caption
      } else {
        current = { key: '', title: caption ? caption.split('\n')[0] : f.filename, caption: caption || null, items: [item] }
        out.push(current)
      }

      if (imgLine) lastImgLine = imgLine
    }

    // Heuristic: if a captionless image block is immediately followed by a keyed figure,
    // treat it as panels of that figure (MinerU sometimes outputs images first, caption later).
    const merged: typeof out = []
    for (const g of out) {
      const prev = merged[merged.length - 1]
      const prevLastLine = prev?.items?.[prev.items.length - 1]?.imgLine ?? 0
      const nextFirstLine = g.items?.[0]?.imgLine ?? 0
      const canMergePrevIntoThis =
        !!prev &&
        !prev.key &&
        !String(prev.caption ?? '').trim() &&
        !!g.key &&
        prev.items.length > 0 &&
        nextFirstLine > 0 &&
        prevLastLine > 0 &&
        nextFirstLine - prevLastLine <= MAX_GAP + 4

      if (canMergePrevIntoThis) {
        merged.pop()
        g.items = [...prev.items, ...g.items]
      }

      merged.push(g)
    }

    return merged.map((g) => {
      const multi = g.items.length > 1
      const title0 = g.title || g.items[0]?.filename || 'Figure'
      return {
        ...g,
        title: multi ? `${title0}（${g.items.length} 张）` : title0,
      }
    })
  }, [detail?.figures, detail?.paper?.paper_id, id])

  const reviewPendingCount = useMemo(() => Number(detail?.paper?.review_pending_count ?? 0) || 0, [detail?.paper?.review_pending_count])
  const reviewNeedsReview = useMemo(
    () => Boolean(detail?.paper?.review_needs_review) && reviewPendingCount > 0,
    [detail?.paper?.review_needs_review, reviewPendingCount],
  )

  const reviewItems = useMemo(() => {
    if (!detail) return []
    const items: Array<{
      id: string
      kind: string
      key: string
      label: string
      humanTitle: string
      humanText: string
      machineTitle: string
      machineText: string
      hint?: string
    }> = []

    const p = detail.paper
    if (p.title_source && p.title_source !== 'machine') {
      items.push({
        id: `meta_title|title`,
        kind: 'meta_title',
        key: 'title',
        label: '标题',
        humanTitle: `人工 (${p.title_source === 'cleared' ? '清空' : '修改'})`,
        humanText: p.title_source === 'cleared' ? '' : String(p.title ?? ''),
        machineTitle: '机器候选',
        machineText: String(p.title_machine ?? ''),
        hint: '仅对你人工改过/清空过的字段需要裁决；未改动字段已直接用新机器结果覆盖。',
      })
    }
    if (p.year_source && p.year_source !== 'machine') {
      items.push({
        id: `meta_year|year`,
        kind: 'meta_year',
        key: 'year',
        label: '年份',
        humanTitle: `人工 (${p.year_source === 'cleared' ? '清空' : '修改'})`,
        humanText: p.year_source === 'cleared' ? '' : String(p.year ?? ''),
        machineTitle: '机器候选',
        machineText: p.year_machine === undefined || p.year_machine === null ? '' : String(p.year_machine),
      })
    }

    for (const s of detail.logic_steps ?? []) {
      const src = String(s.source ?? 'machine')
      if (!['human', 'cleared'].includes(src)) continue
      items.push({
        id: `logic_step|${String(s.step_type ?? '')}`,
        kind: 'logic_step',
        key: String(s.step_type ?? ''),
        label: `逻辑链 · ${stepLabel(detail.schema ?? null, String(s.step_type ?? ''))}`,
        humanTitle: `人工 (${src === 'cleared' ? '清空' : '修改'})`,
        humanText: src === 'cleared' ? '' : String(s.summary ?? ''),
        machineTitle: '机器候选',
        machineText: String(s.pending_machine_summary ?? s.summary_machine ?? ''),
      })
    }

    for (const c of detail.claims ?? []) {
      const src = String(c.source ?? 'machine')
      if (!['human', 'cleared'].includes(src)) continue
      items.push({
        id: `claim|${String(c.claim_key ?? '')}`,
        kind: 'claim',
        key: String(c.claim_key ?? ''),
        label: `要点 · ${String(c.claim_key ?? '').slice(0, 8)}`,
        humanTitle: `人工 (${src === 'cleared' ? '清空' : '修改'})`,
        humanText: src === 'cleared' ? '' : String(c.text ?? ''),
        machineTitle: '机器候选',
        machineText: String(c.pending_machine_text ?? c.text_machine ?? ''),
      })
    }

    function formatPurposes(labels: string[] | null | undefined, scores: number[] | null | undefined) {
      const ls = (labels ?? []).map((x) => PURPOSE_LABELS[x] ?? x)
      const ss = (scores ?? []).map((x) => Number(x).toFixed(2))
      if (ls.length === 0) return ''
      if (ss.length === 0) return ls.join(', ')
      return `${ls.join(', ')}\n${ss.join(', ')}`
    }

    for (const o of detail.outgoing_cites ?? []) {
      const src = String(o.purpose_source ?? 'machine')
      if (!['human', 'cleared'].includes(src)) continue
      const citedTitle = o.cited_title ? shorten(o.cited_title, 64) : o.cited_doi ? `doi:${o.cited_doi}` : o.cited_paper_id
      items.push({
        id: `cite_purpose|${String(o.cited_paper_id ?? '')}`,
        kind: 'cite_purpose',
        key: String(o.cited_paper_id ?? ''),
        label: `引用目的 · ${shorten(citedTitle, 60)}`,
        humanTitle: `人工 (${src === 'cleared' ? '清空' : '修改'})`,
        humanText: src === 'cleared' ? '' : formatPurposes(o.purpose_labels_human ?? o.purpose_labels, o.purpose_scores_human ?? o.purpose_scores),
        machineTitle: '机器候选',
        machineText: formatPurposes(o.pending_machine_purpose_labels ?? o.purpose_labels_machine, o.pending_machine_purpose_scores ?? o.purpose_scores_machine),
      })
    }

    return items
  }, [detail])

  const paperGraph = useMemo(() => {
    const nodes = new Map<string, SignalGraphNode>()
    const edges = new Map<string, SignalGraphEdge>()
    const metaMap = new Map<string, GraphMeta>()

    if (!detail) return { nodes: [] as SignalGraphNode[], edges: [] as SignalGraphEdge[], metaMap }

    const putNode = (node: SignalGraphNode, meta: GraphMeta) => {
      nodes.set(node.id, node)
      metaMap.set(node.id, meta)
    }

    const putEdge = (edge: SignalGraphEdge) => {
      edges.set(edge.id, edge)
    }

    const rootId = 'paper:root'
    putNode(
      {
        id: rootId,
        label: shorten(detail.paper.title ?? detail.paper.paper_source ?? detail.paper.paper_id, 46),
        kind: 'root',
        weight: 1,
      },
      {
        title: detail.paper.title ?? detail.paper.paper_source ?? detail.paper.paper_id,
        detail: `论文ID ${detail.paper.paper_id}${detail.paper.doi ? ` | DOI ${detail.paper.doi}` : ''}`,
      },
    )

    const logicIdByType = new Map<string, string>()
    const logicSteps = detail.logic_steps ?? []
    for (let idx = 0; idx < logicSteps.length; idx += 1) {
      const step = logicSteps[idx]
      const stepType = String(step.step_type ?? '').trim() || `logic-${idx + 1}`
      const nodeId = `logic:${stepType}:${idx}`
      logicIdByType.set(stepType, nodeId)

      putNode(
        {
          id: nodeId,
          label: shorten(step.summary || stepType, 34),
          kind: 'logic',
          weight: 0.28,
        },
        {
          title: stepLabel(detail.schema, stepType),
          detail: shorten(step.summary ?? '', 220),
          tab: 'logic',
        },
      )

      putEdge({
        id: `${rootId}->${nodeId}`,
        source: rootId,
        target: nodeId,
        kind: 'contains',
        weight: 0.65,
      })
    }

    const claims = detail.claims ?? []
    for (let idx = 0; idx < claims.length; idx += 1) {
      const claim = claims[idx]
      const claimKey = String(claim.claim_key ?? '').trim() || `claim-${idx + 1}`
      const claimNodeId = `claim:${claimKey}`
      const confidence = Number(claim.confidence ?? 0)

      putNode(
        {
          id: claimNodeId,
          label: shorten(claim.text || claimKey, 34),
          kind: 'claim',
          weight: clamp01(Number.isFinite(confidence) ? 0.2 + confidence * 0.7 : 0.3),
        },
        {
          title: claim.step_type ? `${stepLabel(detail.schema, String(claim.step_type))} / Claim` : 'Claim',
          detail: shorten(claim.text, 220),
          tab: 'claims',
        },
      )

      const stepType = String(claim.step_type ?? '').trim()
      const linkedLogic = stepType ? logicIdByType.get(stepType) : undefined
      putEdge({
        id: `${linkedLogic ?? rootId}->${claimNodeId}`,
        source: linkedLogic ?? rootId,
        target: claimNodeId,
        kind: 'supports',
        weight: clamp01(Number.isFinite(confidence) ? 0.4 + confidence * 0.5 : 0.45),
      })
    }

    const cites = detail.outgoing_cites ?? []
    for (let idx = 0; idx < cites.length; idx += 1) {
      const cite = cites[idx]
      const citeId = `cite:${cite.cited_paper_id}`
      const label = cite.cited_title ?? cite.cited_doi ?? cite.cited_paper_id
      putNode(
        {
          id: citeId,
          label: shorten(label, 34),
          kind: 'citation',
          weight: clamp01(0.25 + Math.min(1, Number(cite.total_mentions ?? 0) / 6) * 0.6),
        },
        {
          title: label,
          detail: `引用次数 ${cite.total_mentions ?? 0} | ${(cite.purpose_labels ?? []).join(', ') || '未标注'}`,
          tab: 'cites',
        },
      )

      putEdge({
        id: `${rootId}->${citeId}`,
        source: rootId,
        target: citeId,
        kind: 'cites',
        weight: clamp01(0.28 + Math.min(1, Number(cite.total_mentions ?? 0) / 8) * 0.58),
      })
    }

    return { nodes: Array.from(nodes.values()).slice(0, 120), edges: Array.from(edges.values()).slice(0, 220), metaMap }
  }, [detail])

  const selectedGraphMeta = useMemo(
    () => paperGraph.metaMap.get(selectedGraphNodeId),
    [paperGraph.metaMap, selectedGraphNodeId],
  )

  function handleSelectPaperGraphNode(nodeId: string) {
    setSelectedGraphNodeId(nodeId)
    if (!nodeId) return
    const meta = paperGraph.metaMap.get(nodeId)
    if (meta?.tab) selectTab(meta.tab)
  }

  function reviewChoiceOf(id: string) {
    return reviewChoice[id] ?? 'keep_human'
  }

  function setReviewChoiceOf(id: string, decision: 'keep_human' | 'use_machine' | 'clear') {
    setReviewChoice((m) => {
      if (decision === 'keep_human') {
        if (!m[id]) return m
        const copy = { ...m }
        delete copy[id]
        return copy
      }
      return { ...m, [id]: decision }
    })
  }

  async function updatePurpose(citedPaperId: string, labels: string[], scores: number[]) {
    setBusy(citedPaperId)
    setError('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/cites/${encodeURIComponent(citedPaperId)}/purpose`, {
        action: 'set',
        labels,
        scores,
      })
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy('')
    }
  }

  async function setCitePurposeUseMachine(citedPaperId: string) {
    setBusy(citedPaperId)
    setError('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/cites/${encodeURIComponent(citedPaperId)}/purpose`, { action: 'use_machine' })
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy('')
    }
  }

  async function setCitePurposeClear(citedPaperId: string) {
    setBusy(citedPaperId)
    setError('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/cites/${encodeURIComponent(citedPaperId)}/purpose`, { action: 'clear' })
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy('')
    }
  }

  async function saveMetadata() {
    setError('')
    setInfo('')
    try {
      const year = metaYear.trim() ? Number(metaYear.trim()) : null
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/metadata`, {
        action: 'set',
        title: metaTitle,
        year: year === null || Number.isNaN(year) ? undefined : year,
      })
      setMetaEditOpen(false)
      await refresh()
      setInfo('已保存元数据修改。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function restoreMachineMetadata(fields: Array<'title' | 'year'>) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/metadata`, {
        action: 'use_machine',
        fields,
      })
      await refresh()
      setInfo('已恢复机器生成的元数据。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function clearMetadata(fields: Array<'title' | 'year'>) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/metadata`, {
        action: 'clear',
        fields,
      })
      await refresh()
      setInfo('已清空（不保留）所选元数据字段。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function saveLogic(stepType: string) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/logic/${encodeURIComponent(stepType)}`, {
        action: 'set',
        summary: logicDraft[stepType] ?? '',
      })
      setLogicEdit((m) => ({ ...m, [stepType]: false }))
      await refresh()
      setInfo(`已保存：${stepLabel(detail?.schema ?? null, stepType)}`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function restoreMachineLogic(stepType: string) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/logic/${encodeURIComponent(stepType)}`, { action: 'use_machine' })
      await refresh()
      setInfo(`已恢复机器：${stepLabel(detail?.schema ?? null, stepType)}`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function clearLogic(stepType: string) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/logic/${encodeURIComponent(stepType)}`, { action: 'clear' })
      await refresh()
      setInfo(`已清空：${stepLabel(detail?.schema ?? null, stepType)}`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function addClaim() {
    const text = newClaimText.trim()
    if (!text) return
    setError('')
    setInfo('')
    try {
      await apiPost<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/claims`, { text })
      setNewClaimText('')
      await refresh()
      setInfo('已新增要点。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function saveClaim(claimKey: string) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/claims/${encodeURIComponent(claimKey)}`, {
        action: 'set',
        text: claimDraft[claimKey] ?? '',
      })
      setClaimEdit((m) => ({ ...m, [claimKey]: false }))
      await refresh()
      setInfo('已保存要点修改。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function restoreMachineClaim(claimKey: string) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/claims/${encodeURIComponent(claimKey)}`, { action: 'use_machine' })
      await refresh()
      setInfo('已恢复机器要点。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function clearClaim(claimKey: string) {
    setError('')
    setInfo('')
    try {
      await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/claims/${encodeURIComponent(claimKey)}`, { action: 'clear' })
      await refresh()
      setInfo('已清空该要点（不保留）。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function searchEvidence(q: string) {
    const query = (q ?? '').trim()
    if (!query) {
      setEvidenceResults([])
      return
    }
    setEvidenceBusy(true)
    setError('')
    try {
      const res = await apiGet<{
        chunks: Array<{
          chunk_id: string
          section?: string | null
          start_line?: number
          end_line?: number
          kind?: string
          score?: number
          snippet?: string
          text?: string
          text_truncated?: boolean
        }>
      }>(
        `/papers/${encodeURIComponent(id)}/chunks/search?q=${encodeURIComponent(query)}&limit=80`,
      )
      setEvidenceResults(res.chunks ?? [])
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setEvidenceBusy(false)
    }
  }

  function openClaimEvidenceEditor(claim: NonNullable<PaperDetail['claims']>[number]) {
    const key = String(claim.claim_key ?? '')
    const initial =
      (claim.evidence_human && claim.evidence_human.length > 0 ? claim.evidence_human : claim.evidence_machine && claim.evidence_machine.length > 0 ? claim.evidence_machine : claim.evidence) ?? []
    const sel: Record<string, boolean> = {}
    for (const e of initial) {
      const cid = String((e as { chunk_id?: unknown } | null)?.chunk_id ?? '')
      if (cid) sel[cid] = true
    }
    setEvidenceEditKind('claim')
    setEvidenceEditKey(key)
    setEvidenceEditTitle(`要点 · ${key.slice(0, 8)}`)
    setEvidenceSelected(sel)
    setEvidenceExpanded({})
    const q = String(claim.text ?? '').trim().slice(0, 120)
    setEvidenceQuery(q)
    searchEvidence(q).catch(() => {})
  }

  function openLogicEvidenceEditor(step: NonNullable<PaperDetail['logic_steps']>[number]) {
    const stepType = String(step.step_type ?? '')
    if (!stepType) return
    const initial =
      (step.evidence_human && step.evidence_human.length > 0 ? step.evidence_human : step.evidence_machine && step.evidence_machine.length > 0 ? step.evidence_machine : step.evidence) ?? []
    const sel: Record<string, boolean> = {}
    for (const e of initial) {
      const cid = String((e as { chunk_id?: unknown } | null)?.chunk_id ?? '')
      if (cid) sel[cid] = true
    }
    setEvidenceEditKind('logic')
    setEvidenceEditKey(stepType)
    setEvidenceEditTitle(`逻辑步骤 · ${stepLabel(detail?.schema ?? null, stepType)}`)
    setEvidenceSelected(sel)
    setEvidenceExpanded({})
    const q = String(step.summary ?? '').trim().slice(0, 120)
    setEvidenceQuery(q)
    searchEvidence(q).catch(() => {})
  }

  function closeEvidenceEditor() {
    if (evidenceBusy) return
    setEvidenceEditKey('')
    setEvidenceEditTitle('')
    setEvidenceResults([])
    setEvidenceSelected({})
    setEvidenceExpanded({})
  }

  async function saveEvidence(action: 'set' | 'use_machine' | 'clear') {
    if (!evidenceEditKey) return
    setError('')
    setInfo('')
    try {
      const chunk_ids = Object.entries(evidenceSelected)
        .filter(([, v]) => !!v)
        .map(([k]) => k)
      if (evidenceEditKind === 'claim') {
        await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/claims/${encodeURIComponent(evidenceEditKey)}/evidence`, {
          action,
          chunk_ids,
        })
      } else {
        await apiPatch<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/logic_steps/${encodeURIComponent(evidenceEditKey)}/evidence`, {
          action,
          chunk_ids,
        })
      }
      closeEvidenceEditor()
      await refresh()
      setInfo(action === 'set' ? '已保存证据(Evidence)。' : action === 'use_machine' ? '已恢复机器证据(Evidence)。' : '已清空证据(Evidence)。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function applyReview() {
    if (!detail?.paper) return
    const pendingCount = Number(detail.paper.review_pending_count ?? 0) || 0
    if (pendingCount <= 0) {
      setReviewOpen(false)
      return
    }
    const decisions: Array<{ kind: string; key: string; decision: string }> = []
    for (const [k, v] of Object.entries(reviewChoice)) {
      if (v === 'keep_human') continue
      const [kind, key] = k.split('|', 2)
      if (!kind || !key) continue
      decisions.push({ kind, key, decision: v })
    }
    setError('')
    setInfo('')
    try {
      setReviewBusy(true)
      await apiPost<Record<string, unknown>>(`/papers/${encodeURIComponent(id)}/review/apply`, { decisions })
      setReviewOpen(false)
      setReviewChoice({})
      await refresh()
      setInfo('已应用裁决。')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setReviewBusy(false)
    }
  }

  async function startRebuild() {
    setRebuildBusy(true)
    setError('')
    setRebuildTask(null)
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/rebuild/paper', { paper_id: id, rebuild_faiss: rebuildFaiss })
      setRebuildTaskId(res.task_id ?? '')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setRebuildBusy(false)
    }
  }

  if (!id) return <div className="page">Missing paper id</div>

  return (
    <div className={`page paperDetailPage${isPinned ? ' paperDetailPage--wide' : ''}`}>
      <div className="pageHeader paperDetailHeader">
        <div>
          <h2 className="pageTitle">论文</h2>
          <div className="pageSubtitle">{title}</div>
        </div>
        <div className="pageActions paperDetailActions">
          <span className="pill">
            <span className="kicker">年份</span> {stats.year}
          </span>
          <span className="pill">
            <span className="kicker">片段</span> {stats.chunks}
          </span>
          <span className="pill">
            <span className="kicker">引用</span> {stats.refs}
          </span>
          <span className="pill">
            <span className="kicker">图片</span> {stats.figures}
          </span>
          <button className="btn" disabled={!detail} onClick={() => setMetaEditOpen((v) => !v)}>
            {metaEditOpen ? '关闭元数据编辑' : '编辑元数据'}
          </button>
          {reviewNeedsReview && (
            <button className="btn btnDanger" onClick={() => setReviewOpen(true)}>
              待裁决 {reviewPendingCount}
            </button>
          )}
          <button className="btn btnPrimary" disabled={rebuildBusy} onClick={startRebuild}>
            {rebuildBusy ? '提交中…' : '重建（异步）'}
          </button>
          {detail && (
            <select
              className="btn"
              defaultValue=""
              onChange={(e) => {
                const fmt = e.target.value
                if (!fmt) return
                e.target.value = ''
                window.open(`${apiBaseUrl()}/papers/${encodeURIComponent(id)}/export?format=${fmt}`, '_blank')
              }}
            >
              <option value="" disabled>导出…</option>
              <option value="json">JSON</option>
              <option value="csv">CSV (Claims)</option>
              <option value="bibtex">BibTeX</option>
            </select>
          )}
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}
      {info && <div className="infoBox paperDetailInfo">{info}</div>}

      {detail && (
        <div className="paperDetailSummary">
          <div className="paperDetailSummaryCard">
            <div className="kicker">Paper</div>
            <div className="paperDetailSummaryValue">
              <code>{stats.paperId}</code>
            </div>
            <div className="metaLine">Current node id</div>
          </div>
          <div className="paperDetailSummaryCard">
            <div className="kicker">DOI</div>
            <div className="paperDetailSummaryValue">{stats.doi ? '已关联' : '待补充'}</div>
            <div className="metaLine">{stats.doi || 'No DOI yet'}</div>
          </div>
          <div className="paperDetailSummaryCard">
            <div className="kicker">Coverage</div>
            <div className="paperDetailSummaryValue">
              {stats.chunks} / {stats.refs} / {stats.figures}
            </div>
            <div className="metaLine">Chunks / Cites / Figures</div>
          </div>
          <div className="paperDetailSummaryCard">
            <div className="kicker">Review</div>
            <div className="paperDetailSummaryValue">{reviewPendingCount}</div>
            <div className="metaLine">{reviewNeedsReview ? 'Need human arbitration' : 'No pending review'}</div>
          </div>
          {detail.paper.ingested && (
            <div className="paperDetailSummaryCard">
              <div className="kicker">Quality</div>
              <div className="paperDetailSummaryValue" style={{ color: detail.paper.phase1_gate_passed ? '#22c55e' : '#ef4444' }}>
                {detail.paper.phase1_gate_passed ? '✓ Pass' : '✗ Fail'}
              </div>
              <div className="metaLine">
                {detail.paper.phase1_quality_tier || '—'}
                {typeof detail.paper.phase1_quality_tier_score === 'number' ? ` (${detail.paper.phase1_quality_tier_score.toFixed(1)})` : ''}
              </div>
            </div>
          )}
          {rebuildTaskId && (
            <div className="paperDetailSummaryCard">
              <div className="kicker">Rebuild Task</div>
              <div className="paperDetailSummaryValue">{Math.round(clamp01(Number(rebuildTask?.progress ?? 0)) * 100)}%</div>
              <div className="metaLine">{taskStatusLabel(String(rebuildTask?.status ?? '')) || 'Queued'}</div>
            </div>
          )}
        </div>
      )}

      {detail && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="panelHeader">
            <div className="split">
              <div className="panelTitle">论文知识图谱视图</div>
              <span className="pill">
                <span className="kicker">节点</span> {paperGraph.nodes.length}
              </span>
            </div>
          </div>
          <div className="panelBody">
            <SignalGraph
              nodes={paperGraph.nodes}
              edges={paperGraph.edges}
              selectedId={selectedGraphNodeId}
              onSelect={handleSelectPaperGraphNode}
              height={420}
            />
            <div className="split" style={{ marginTop: 10 }}>
              <div className="metaLine">
                {selectedGraphMeta
                  ? `${selectedGraphMeta.title} | ${shorten(selectedGraphMeta.detail, 180)}`
                  : '点击图谱节点可高亮关联信息，并自动切换到对应子模块。'}
              </div>
              <div className="row" style={{ gap: 8 }}>
                {selectedGraphMeta?.tab && (
                  <button className="btn btnSmall" onClick={() => selectedGraphMeta.tab && selectTab(selectedGraphMeta.tab)}>
                    打开{selectedGraphMeta.tab}
                  </button>
                )}
                <button className="btn btnSmall" onClick={() => setSelectedGraphNodeId('')}>
                  清空选中
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!detail ? (
        <div className="panel paperDetailLoading">
          <div className="panelBody">加载中…</div>
        </div>
      ) : (
        <>
           <div className="row paperDetailMetaRow">
             <span className="pill">
               <span className="kicker">论文ID</span> <code>{stats.paperId}</code>
             </span>
            {stats.doi && (
              <span className="pill">
                <span className="kicker">DOI</span> <code>{stats.doi}</code>
              </span>
            )}
            <label className="pill" style={{ gap: 8 }}>
              <input type="checkbox" name="paper_rebuild_faiss" checked={rebuildFaiss} onChange={(e) => setRebuildFaiss(e.target.checked)} />
              <span className="kicker">重建 FAISS</span>
            </label>
           {rebuildTaskId && (
             <span className="pill">
               <span className="kicker">任务</span> <code>{rebuildTaskId}</code> · {taskStatusLabel(String(rebuildTask?.status ?? ''))} ·{' '}
               {Math.round(clamp01(Number(rebuildTask?.progress ?? 0)) * 100)}% · {taskStageLabel(String(rebuildTask?.stage ?? ''))}
             </span>
           )}
         </div>

         <div className="row paperDetailTabRow">
           <span className="kicker">页面</span>
           <button className={`chip ${tab === 'logic' ? 'chipActive' : ''}`} onClick={() => selectTab('logic')}>
             逻辑链
           </button>
           <button className={`chip ${tab === 'claims' ? 'chipActive' : ''}`} onClick={() => selectTab('claims')}>
             要点
           </button>
           <button className={`chip ${tab === 'cites' ? 'chipActive' : ''}`} onClick={() => selectTab('cites')}>
             引用
           </button>
           <button className={`chip ${tab === 'figures' ? 'chipActive' : ''}`} onClick={() => selectTab('figures')}>
             图片
           </button>
           {!isPinned && (
             <button className={`chip ${tab === 'content' ? 'chipActive' : ''}`} onClick={() => selectTab('content')}>
               原文
             </button>
           )}
           <button
             className={`pdPinBtn${isPinned ? ' pdPinBtn--active' : ''}`}
             onClick={() => togglePin()}
             title={isPinned ? '关闭原文侧边栏' : '固定原文侧边栏'}
           >
             {isPinned ? '📌 取消固定' : '📌 固定原文'}
           </button>
         </div>

         {!detail.paper.ingested && stats.chunks === 0 && (
           <div className="infoBox paperDetailCallout">
             <div style={{ fontWeight: 850, marginBottom: 6 }}>该论文目前仅包含元数据（{TERMS.stub}），尚未导入 MinerU Markdown。</div>
             <div className="metaLine">建议回到"图谱"页，在节点信息抽屉中上传该论文的 MinerU 输出进行补全导入。</div>
             </div>
           )}

           {reviewNeedsReview && (
             <div className="infoBox paperDetailCallout">
               <div className="split">
                 <div>
                   <div style={{ fontWeight: 850, marginBottom: 6 }}>有 {reviewPendingCount} 项需要裁决（仅包含人工改过的内容）。</div>
                   <div className="metaLine">点击进入左右对比视图，选择保留人工 / 改用机器 / 清空重写。</div>
                 </div>
                 <button className="btn btnPrimary" onClick={() => setReviewOpen(true)}>
                   开始裁决
                 </button>
               </div>
             </div>
           )}

           {detail.paper.ingested && detail.paper.phase1_gate_passed === false && detail.paper.phase1_quality && (
             <div className="infoBox paperDetailCallout" style={{ borderLeft: '4px solid #ef4444' }}>
               <div style={{ fontWeight: 850, marginBottom: 6 }}>质量门控未通过 — {detail.paper.phase1_quality_tier || 'unknown'}</div>
               {Array.isArray((detail.paper.phase1_quality as Record<string, unknown>)?.gate_fail_reasons) && (
                 <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                   {((detail.paper.phase1_quality as Record<string, unknown>).gate_fail_reasons as unknown[]).map((r, i) => (
                     <li key={i} className="metaLine">{String(r ?? '')}</li>
                   ))}
                 </ul>
               )}
             </div>
           )}

           {metaEditOpen && (
             <div className="panel paperDetailMetaPanel">
               <div className="panelHeader">
                 <div className="split">
                   <div className="panelTitle">元数据编辑</div>
                   <span className="badge" title={`title=${detail.paper.title_source} year=${detail.paper.year_source}`}>
                     {detail.paper.title_source === 'human' || detail.paper.year_source === 'human' ? '含人工修改' : '机器/默认'}
                   </span>
                 </div>
               </div>
               <div className="panelBody">
                 <div className="stack">
                   <div>
                     <div className="metaLine" style={{ marginBottom: 6 }}>
                       标题
                     </div>
                    <input className="input" name="paper_meta_title" value={metaTitle} onChange={(e) => setMetaTitle(e.target.value)} placeholder="标题" />
                   </div>
                   <div>
                     <div className="metaLine" style={{ marginBottom: 6 }}>
                       年份
                     </div>
                    <input className="input" name="paper_meta_year" value={metaYear} onChange={(e) => setMetaYear(e.target.value)} placeholder="年份（可空）" />
                   </div>
                   <div className="row">
                     <button className="btn btnPrimary" onClick={saveMetadata}>
                       保存
                     </button>
                     <button className="btn" onClick={() => setMetaEditOpen(false)}>
                       取消
                     </button>
                     <button className="btn" onClick={() => restoreMachineMetadata(['title', 'year'])}>
                       恢复机器
                     </button>
                     <button className="btn btnDanger" onClick={() => clearMetadata(['title', 'year'])}>
                       清空（不保留）
                     </button>
                   </div>
                   <div className="hint">提示：清空后你可以在此重新手写。</div>
                 </div>
               </div>
             </div>
           )}

            <div className={`pdWorkspace${isPinned && tab !== 'content' ? ' pdWorkspace--pinned' : ''}`}>
            <div className="pdWorkspaceMain stack paperDetailContentStack">
              {tab === 'logic' && (
               <div className="panel pdReadPanel pdReadPanel--logic">
                 <div className="panelHeader">
                   <div className="panelTitle">逻辑步骤</div>
                 </div>
                <div className="panelBody">
                  <div className="logicTimeline">
                    {(detail.logic_steps ?? [])
                      .slice()
                      .sort((a, b) => (a.order ?? 999) - (b.order ?? 999))
                      .map((s, idx, arr) => {
                      const total = arr.length
                      const isLast = idx === total - 1
                      const evList = (s.evidence ?? []) as Array<{ chunk_id: string; snippet?: string; weak?: boolean; start_line?: number | null; end_line?: number | null }>
                      return (
                        <div key={`${s.step_type}:${idx}`} className="logicStep">
                          <div className="logicStepIndicator">
                            <div className={`logicStepNum logicStepNum--${s.step_type}`}>{idx + 1}</div>
                            {!isLast && <div className="logicStepConnector" />}
                          </div>
                          <div className="logicStepContent">
                            <div className={`itemCard logicStepCard logicStepCard--${s.step_type}`}>
                              <div className="split">
                                <div className="itemTitle">
                                  {stepLabel(detail.schema ?? null, s.step_type)}
                                  <span className="metaLine" style={{ marginLeft: 8, display: 'inline' }}>{idx + 1}/{total}</span>
                                </div>
                                <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
                                  <span className="badge" title="机器置信度">
                                    {(Number(s.confidence ?? 0) || 0).toFixed(2)}
                                  </span>
                                  <span className={s.source === 'human' ? 'badge badgeOk' : s.source === 'cleared' ? 'badge badgeDanger' : 'badge'} title={`source=${s.source}`}>
                                    {s.source === 'human' ? '人工' : s.source === 'cleared' ? '清空' : '机器'}
                                  </span>
                                  <button className="btn btnSmall" onClick={() => openLogicEvidenceEditor(s)}>
                                    证据(Evidence)
                                  </button>
                                  <button
                                    className="btn btnSmall"
                                    onClick={() => {
                                      const open = !logicEdit[s.step_type]
                                      setLogicEdit((m) => ({ ...m, [s.step_type]: open }))
                                      if (open) setLogicDraft((m) => ({ ...m, [s.step_type]: String(s.summary ?? '') }))
                                    }}
                                  >
                                    {logicEdit[s.step_type] ? '关闭编辑' : '编辑'}
                                  </button>
                                </div>
                              </div>
                              {!logicEdit[s.step_type] ? (
                                <div>
                                  <div className="itemBody">
                                    <MarkdownView markdown={s.summary || '（空）'} paperId={paperIdForImages} />
                                  </div>
                                  {evList.length > 0 && (
                                    <div style={{ marginTop: 10 }}>
                                      <div className="metaLine">证据 ({evList.length})</div>
                                      <div className="list" style={{ marginTop: 8 }}>
                                        {evList.map((e) => (
                                          <div key={e.chunk_id} className={`itemCard itemCard--evidence${typeof e.start_line === 'number' ? ' itemCard--clickable' : ''}`} onClick={() => locateEvidence(e.start_line, e.end_line)}>
                                            <div className="itemMeta">
                                              <code>{e.chunk_id}</code> {e.weak ? <span className="badge badgeWarn">弱</span> : null}
                                              {typeof e.start_line === 'number' && <span> · 行 {e.start_line}-{e.end_line ?? e.start_line}</span>}
                                              {typeof e.start_line === 'number' && <button className="evidenceLocateBtn" onClick={(ev) => { ev.stopPropagation(); locateEvidence(e.start_line, e.end_line) }}>定位原文</button>}
                                            </div>
                                            <div className="itemBody">
                                              <MarkdownView markdown={String(e.snippet ?? '')} paperId={paperIdForImages} />
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ) : (
                                <div style={{ marginTop: 10 }}>
                                  <textarea
                                    className="textarea"
                                    name={`logic_draft_${s.step_type}`}
                                    value={logicDraft[s.step_type] ?? ''}
                                    onChange={(e) => setLogicDraft((m) => ({ ...m, [s.step_type]: e.target.value }))}
                                  />
                                  <div className="row" style={{ marginTop: 10 }}>
                                    <button className="btn btnPrimary" onClick={() => saveLogic(s.step_type)}>保存</button>
                                    <button className="btn" onClick={() => restoreMachineLogic(s.step_type)}>恢复机器</button>
                                    <button className="btn btnDanger" onClick={() => clearLogic(s.step_type)}>清空（不保留）</button>
                                  </div>
                                  {reviewNeedsReview && s.source !== 'machine' && (
                                    <div className="hint" style={{ marginTop: 8 }}>
                                      本项在上次重建后需要裁决：机器候选可在"待裁决"抽屉中查看对比。
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  {(detail.logic_steps ?? []).length === 0 && <div className="metaLine">暂无逻辑步骤。</div>}
                </div>
              </div>
            )}

            {tab === 'claims' && (
              <div className="panel pdReadPanel pdReadPanel--claims">
                <div className="panelHeader">
                  <div className="split">
                    <div className="panelTitle">要点</div>
                    <button className="btn btnSmall" onClick={addClaim} disabled={!newClaimText.trim()}>
                      新增
                    </button>
                  </div>
                </div>
                <div className="panelBody">
                  <div className="itemCard" style={{ marginBottom: 12 }}>
                    <div className="itemTitle">新增要点（人工）</div>
                    <textarea className="textarea" name="claim_new_text" value={newClaimText} onChange={(e) => setNewClaimText(e.target.value)} placeholder="输入一条要点…" />
                    <div className="hint">保存后会生成稳定的 claim_key，用于后续重建对齐与裁决。</div>
                  </div>
                  <div className="list">
                    {(() => {
                      const claims = detail.claims ?? []
                      const grouped: Record<string, NonNullable<PaperDetail['claims']>[number][]> = {}
                      for (const c of claims) {
                        const st = String(c.step_type ?? '') || '_ungrouped'
                        if (!grouped[st]) grouped[st] = []
                        grouped[st].push(c)
                      }
                      const entries = Object.entries(grouped)
                      return entries.map(([st, items]) => (
                        <div key={st}>
                          <div className={`claimsGroupDivider claimsGroupDivider--${st === '_ungrouped' ? 'ungrouped' : st}`}>
                            {st === '_ungrouped' ? '未分类' : stepLabel(detail.schema ?? null, st)}
                            {' '}({items.length})
                          </div>
                          {items.map((c) => {
                            const key = c.claim_key
                            const src = String(c.source ?? 'machine')
                            const isEditing = !!claimEdit[key]
                            const kinds = (c.kinds ?? []) as string[]
                            const evidence = (c.evidence ?? []) as Array<{ chunk_id: string; snippet?: string; weak?: boolean; start_line?: number | null; end_line?: number | null }>
                            const targets = (c.targets ?? []) as Array<{ paper_id: string; doi?: string | null; title?: string | null }>
                            return (
                              <div key={key} className={`itemCard claimCard${src === 'human' ? ' claimCard--human' : ''}${src === 'cleared' ? ' claimCard--cleared' : ''}`}>
                                <div className="split">
                                  <div className="itemTitle" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                                    要点 <code>{key}</code>
                                    <span className={src === 'human' ? 'badge badgeOk' : src === 'cleared' ? 'badge badgeDanger' : 'badge'}>{src === 'human' ? '人工' : src === 'cleared' ? '清空' : '机器'}</span>
                                    {kinds.slice(0, 6).map((k) => (
                                      <span key={k} className="badge" title={k}>{kindLabel(detail.schema ?? null, k)}</span>
                                    ))}
                                  </div>
                                  <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
                                    <span className="badge" title="机器置信度">{(Number(c.confidence ?? 0) || 0).toFixed(2)}</span>
                                    <button className="btn btnSmall" onClick={() => openClaimEvidenceEditor(c)}>证据(Evidence)</button>
                                    <button className="btn btnSmall" onClick={() => { const open = !isEditing; setClaimEdit((m) => ({ ...m, [key]: open })); if (open) setClaimDraft((m) => ({ ...m, [key]: String(c.text ?? '') })) }}>
                                      {isEditing ? '关闭编辑' : '编辑'}
                                    </button>
                                  </div>
                                </div>
                                {!isEditing ? (
                                  <div>
                                    <div className="itemBody"><MarkdownView markdown={c.text || '（空）'} paperId={paperIdForImages} /></div>
                                    {evidence.length > 0 && (
                                      <div style={{ marginTop: 10 }}>
                                        <div className="metaLine">证据 ({evidence.length})</div>
                                        <div className="list" style={{ marginTop: 8 }}>
                                          {evidence.map((e) => (
                                            <div key={e.chunk_id} className={`itemCard itemCard--evidence${typeof e.start_line === 'number' ? ' itemCard--clickable' : ''}`} onClick={() => locateEvidence(e.start_line, e.end_line)}>
                                              <div className="itemMeta">
                                                <code>{e.chunk_id}</code> {e.weak ? <span className="badge badgeWarn">弱</span> : null}
                                                {typeof e.start_line === 'number' && <span> · 行 {e.start_line}-{e.end_line ?? e.start_line}</span>}
                                                {typeof e.start_line === 'number' && <button className="evidenceLocateBtn" onClick={(ev) => { ev.stopPropagation(); locateEvidence(e.start_line, e.end_line) }}>定位原文</button>}
                                              </div>
                                              <div className="itemBody"><MarkdownView markdown={String(e.snippet ?? '')} paperId={paperIdForImages} /></div>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                    {targets.length > 0 && (
                                      <div style={{ marginTop: 10 }}>
                                        <div className="metaLine">对齐目标(Targets)</div>
                                        <div className="list" style={{ marginTop: 8 }}>
                                          {targets.map((t) => (
                                            <div key={t.paper_id} className="itemCard itemCard--evidence">
                                              <div className="itemMeta"><code>{t.paper_id}</code> {t.doi ? ` · ${t.doi}` : ''}</div>
                                              <div className="itemBody">{t.title ?? ''}</div>
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <div style={{ marginTop: 10 }}>
                                    <textarea className="textarea" name={`claim_draft_${key}`} value={claimDraft[key] ?? ''} onChange={(e) => setClaimDraft((m) => ({ ...m, [key]: e.target.value }))} />
                                    <div className="row" style={{ marginTop: 10 }}>
                                      <button className="btn btnPrimary" onClick={() => saveClaim(key)}>保存</button>
                                      <button className="btn" onClick={() => restoreMachineClaim(key)}>恢复机器</button>
                                      <button className="btn btnDanger" onClick={() => clearClaim(key)}>清空（不保留）</button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      ))
                    })()}
                  </div>
                  {(detail.claims ?? []).length === 0 && <div className="metaLine">暂无要点。</div>}
                </div>
              </div>
            )}

            {tab === 'cites' && (
              <>
              <div className="panel">
                <div className="panelHeader">
                  <div className="panelTitle">引用（出站）</div>
                </div>
                <div className="panelBody">
                  <div className="list">
                    {detail.outgoing_cites.map((c) => (
                      <div key={c.cited_paper_id} className="itemCard">
                        <div className="split">
                          <div className="itemTitle" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                            {c.cited_title ?? c.cited_doi ?? c.cited_paper_id}
                            <span className={c.purpose_source === 'human' ? 'badge badgeOk' : c.purpose_source === 'cleared' ? 'badge badgeDanger' : 'badge'}>
                              {c.purpose_source === 'human' ? '人工' : c.purpose_source === 'cleared' ? '清空' : '机器'}
                            </span>
                          </div>
                          <div className="row" style={{ gap: 8, justifyContent: 'flex-end' }}>
                            <button className="btn btnSmall" disabled={busy === c.cited_paper_id} onClick={() => setCitePurposeUseMachine(c.cited_paper_id)}>
                              恢复机器
                            </button>
                            <button className="btn btnSmall btnDanger" disabled={busy === c.cited_paper_id} onClick={() => setCitePurposeClear(c.cited_paper_id)}>
                              清空
                            </button>
                          </div>
                        </div>
                        <div className="itemMeta">
                          引用次数 {c.total_mentions ?? 0} · 引用编号 {(c.ref_nums ?? []).join(', ')}
                        </div>
                        <div className="row" style={{ marginTop: 10, gap: 8 }}>
                          {PURPOSES.map((p) => {
                            const selected = (c.purpose_labels ?? []).includes(p)
                            return (
                              <button
                                key={p}
                                className={`chip ${selected ? 'chipActive' : ''}`}
                                disabled={busy === c.cited_paper_id}
                                onClick={() => {
                                  const curLabels = c.purpose_labels ?? []
                                  const curScores = c.purpose_scores ?? []
                                  let labels = curLabels.slice()
                                  let scores = curScores.slice()
                                  const idx = labels.indexOf(p)
                                  if (idx >= 0) {
                                    labels.splice(idx, 1)
                                    scores.splice(idx, 1)
                                  } else {
                                    if (labels.length >= 3) return
                                    labels = [...labels, p]
                                    scores = [...scores, 0.6]
                                  }
                                  updatePurpose(c.cited_paper_id, labels, scores)
                                }}
                              >
                                {PURPOSE_LABELS[p] ?? p}
                              </button>
                            )
                          })}
                        </div>
                        <div className="itemMeta" style={{ marginTop: 8 }}>
                          标签 {(c.purpose_labels ?? []).map((p) => PURPOSE_LABELS[p] ?? p).join(', ')} · 置信度{' '}
                          {(c.purpose_scores ?? []).map((s) => s.toFixed(2)).join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                  {detail.outgoing_cites.length === 0 && <div className="metaLine">暂无出站引用。</div>}
                </div>
              </div>

              <div className="panel">
                <div className="panelHeader">
                  <div className="panelTitle">未解析</div>
                </div>
                <div className="panelBody">
                  <div className="list">
                    {detail.unresolved.map((u) => (
                      <div key={u.ref_id} className="itemCard">
                        <div className="itemTitle">
                          引用条目 <code>{u.ref_id}</code>
                        </div>
                        <div className="itemBody">
                          <MarkdownView markdown={u.raw} />
                        </div>
                        <div className="itemMeta">
                          引用次数 {u.total_mentions ?? 0} · 引用编号 {(u.ref_nums ?? []).join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                  {detail.unresolved.length === 0 && <div className="metaLine">无</div>}
                </div>
              </div>
              </>
            )}

            {tab === 'figures' && (
              <div className="panel">
                <div className="panelHeader">
                  <div className="split">
                    <div className="panelTitle">图片</div>
                    <span className="pill">
                      <span className="kicker">数量</span> {(detail.figures ?? []).length}
                    </span>
                  </div>
                </div>
                <div className="panelBody">
                  <div className="figureGrid">
                    {figureGroups.map((g, idx) => {
                      const thumb = g.items[0]
                      const caption = g.caption ?? null
                      const title0 = g.title
                      const cardTitle = shorten(title0 || thumb?.filename, 92) || thumb?.filename || 'Figure'
                      const cardCaption = shorten(caption || thumb?.filename, 160)
                      return (
                        <div
                          key={`${g.key || 'x'}:${thumb?.src || ''}:${idx}`}
                          className="figureCard"
                          onClick={() => setActiveFigureGroup({ title: title0 || thumb?.filename || 'Figure', caption, items: g.items })}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') setActiveFigureGroup({ title: title0 || thumb?.filename || 'Figure', caption, items: g.items })
                          }}
                        >
                          {thumb ? <img className="figureThumb" src={thumb.src} alt={cardTitle} loading="lazy" /> : null}
                          <div className="figureCaption">
                            <div style={{ fontWeight: 700, marginBottom: 6 }}>{cardTitle}</div>
                            <div style={{ opacity: 0.86 }}>{cardCaption}</div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  {figureGroups.length === 0 && <div className="metaLine">未找到图片。</div>}
                  <div className="hint">点击缩略图放大；图注从 md 相邻文本/图注块抽取。</div>
                </div>
              </div>
            )}

            {tab === 'content' && (
              <OriginalTextPanel paperId={id} mode="fullwidth" highlightRange={highlightRange} onPopout={() => setShowContentModal(true)} />
            )}
          </div>
          {isPinned && tab !== 'content' && (
            <OriginalTextPanel paperId={id} mode="sidebar" onClose={() => togglePin(false)} highlightRange={highlightRange} onPopout={() => setShowContentModal(true)} />
          )}
          </div>
        </>
      )}

      {showContentModal && (
        <OriginalTextPanel paperId={id} mode="modal" onClose={() => setShowContentModal(false)} highlightRange={highlightRange} />
      )}

      {activeFigureGroup && (
        <div className="modalOverlay" onClick={() => setActiveFigureGroup(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">{shorten(activeFigureGroup.title, 140)}</div>
              <button className="btn btnSmall" onClick={() => setActiveFigureGroup(null)}>
                关闭
              </button>
            </div>
            <div className="modalBody">
              {activeFigureGroup.caption && (
                <div className="metaLine" style={{ marginBottom: 10 }}>
                  {(() => {
                    const segments = splitSubfigureCaption(activeFigureGroup.caption ?? '')
                    if (!segments) return <MarkdownView markdown={activeFigureGroup.caption} paperId={paperIdForImages} />
                    return (
                      <div className="stack" style={{ gap: 8 }}>
                        <div className="kicker">子图说明</div>
                        {segments.map((s, idx) => (
                          <div key={`${idx}:${s.slice(0, 16)}`}>
                            <MarkdownView markdown={s} paperId={paperIdForImages} />
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                </div>
              )}
              <div className="stack" style={{ gap: 14 }}>
                {activeFigureGroup.items.map((it, idx) => (
                  <div key={`${it.src}:${idx}`}>
                    <div className="metaLine" style={{ marginBottom: 8 }}>
                      <code>{it.filename}</code>
                    </div>
                    <img className="modalFigure" src={it.src} alt={it.title} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {evidenceEditKey && (
        <div className="modalOverlay" onClick={() => closeEvidenceEditor()}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">{evidenceEditTitle || '证据(Evidence) 编辑'}</div>
              <button className="btn btnSmall" disabled={evidenceBusy} onClick={() => closeEvidenceEditor()}>
                关闭
              </button>
            </div>
            <div className="modalBody">
              <div className="row">
                <input className="input" name="evidence_search_query" value={evidenceQuery} onChange={(e) => setEvidenceQuery(e.target.value)} placeholder="搜索证据 chunk（输入关键词；可直接用当前文本）" />
                <button className="btn" disabled={evidenceBusy || !evidenceQuery.trim()} onClick={() => searchEvidence(evidenceQuery).catch(() => {})}>
                  {evidenceBusy ? '搜索中…' : '搜索'}
                </button>
              </div>
              <div className="hint" style={{ marginTop: 10 }}>
                复选框不限数量；保存后会作为"人工证据"覆盖机器证据，并在重建后可继续保留。
              </div>
              <div className="list" style={{ marginTop: 12 }}>
                {evidenceResults.map((c) => {
                  const cid = String(c.chunk_id ?? '')
                  const selected = !!evidenceSelected[cid]
                  const expanded = !!evidenceExpanded[cid]
                  return (
                    <div key={cid} className="itemCard" style={{ background: selected ? 'rgba(124,255,203,0.06)' : undefined }}>
                      <div className="split">
                        <div className="itemMeta">
                          <code>{cid}</code>
                          {c.section ? <span> · {c.section}</span> : null}
                          {typeof c.start_line === 'number' ? <span> · L{c.start_line}-{c.end_line}</span> : null}
                        </div>
                        <div className="row" style={{ gap: 8 }}>
                          {c.text ? (
                            <button className="btn btnSmall" onClick={() => setEvidenceExpanded((m) => ({ ...m, [cid]: !expanded }))}>
                              {expanded ? '收起' : '展开'}
                            </button>
                          ) : null}
                          <label className="row" style={{ gap: 8 }}>
                            <input
                              type="checkbox"
                              name={`evidence_select_${cid}`}
                              checked={selected}
                              onChange={(e) => setEvidenceSelected((m) => ({ ...m, [cid]: e.target.checked }))}
                            />
                            <span className="kicker">选中</span>
                          </label>
                        </div>
                      </div>
                      <div className="itemBody">
                        <MarkdownView markdown={String(c.snippet ?? '')} paperId={paperIdForImages} />
                      </div>
                      {expanded && c.text && (
                        <div className="itemBody" style={{ marginTop: 10, opacity: 0.92 }}>
                          <MarkdownView markdown={`${c.text}${c.text_truncated ? '\n…[TRUNCATED]' : ''}`} paperId={paperIdForImages} />
                        </div>
                      )}
                    </div>
                  )
                })}
                {evidenceResults.length === 0 && <div className="metaLine">暂无结果。你可以输入更具体的关键词再搜索。</div>}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button className="btn btnPrimary" disabled={evidenceBusy} onClick={() => saveEvidence('set').catch(() => {})}>
                  保存
                </button>
                <button className="btn" disabled={evidenceBusy} onClick={() => saveEvidence('use_machine').catch(() => {})}>
                  恢复机器
                </button>
                <button className="btn btnDanger" disabled={evidenceBusy} onClick={() => saveEvidence('clear').catch(() => {})}>
                  清空（不保留）
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {reviewOpen && detail && (
        <div className="drawerOverlay" onClick={() => !reviewBusy && setReviewOpen(false)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawerHeader">
              <div className="split">
                <div>
                  <div className="drawerTitle">待裁决</div>
                  <div className="drawerSubtitle">
                    仅显示你此前人工改动过的项（机器已重建）。三选：保留人工 / 改用机器 / 清空重写。
                  </div>
                </div>
                <div className="row">
                  <span className="pill">
                    <span className="kicker">项</span> {reviewItems.length}
                  </span>
                  <button className="btn btnSmall" disabled={reviewBusy} onClick={() => setReviewOpen(false)}>
                    关闭
                  </button>
                </div>
              </div>
            </div>
            <div className="drawerBody">
              {reviewItems.length === 0 ? (
                <div className="metaLine">暂无需要裁决的项。</div>
              ) : (
                <div className="stack">
                  {reviewItems.map((it) => {
                    const choice = reviewChoiceOf(it.id)
                    return (
                      <div key={it.id} className="reviewItem">
                        <div className="reviewItemHeader">
                          <div className="reviewItemLabel">{it.label}</div>
                          <div className="row" style={{ gap: 8 }}>
                            <button
                              className={`chip ${choice === 'keep_human' ? 'chipActive' : ''}`}
                              disabled={reviewBusy}
                              onClick={() => setReviewChoiceOf(it.id, 'keep_human')}
                            >
                              保留人工
                            </button>
                            <button
                              className={`chip ${choice === 'use_machine' ? 'chipActive' : ''}`}
                              disabled={reviewBusy}
                              onClick={() => setReviewChoiceOf(it.id, 'use_machine')}
                            >
                              改用机器
                            </button>
                            <button
                              className={`chip ${choice === 'clear' ? 'chipActive' : ''}`}
                              disabled={reviewBusy}
                              onClick={() => setReviewChoiceOf(it.id, 'clear')}
                            >
                              清空重写
                            </button>
                          </div>
                        </div>
                        {it.hint && <div className="metaLine">{it.hint}</div>}
                        <div className="reviewDiff">
                          <div className="reviewCol">
                            <div className="reviewColTitle">{it.humanTitle}</div>
                            <div className="reviewText">{it.humanText || <span className="reviewEmpty">（空）</span>}</div>
                          </div>
                          <div className="reviewCol">
                            <div className="reviewColTitle">{it.machineTitle}</div>
                            <div className="reviewText">{it.machineText || <span className="reviewEmpty">（空）</span>}</div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
            <div className="drawerFooter">
              <div className="metaLine">
                默认全部保留人工；只有你改动选择的项会写入裁决决策。完成后会标记本次重建已审阅。
              </div>
              <div className="row">
                <button className="btn btnPrimary" disabled={reviewBusy} onClick={applyReview}>
                  {reviewBusy ? '应用中…' : '应用裁决'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
