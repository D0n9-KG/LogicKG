import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useI18n, type UILocale } from '../i18n'
import type { AskItem, GraphEdgeData, GraphNodeData } from '../state/types'
import { apiGet } from '../api'
import { buildEvidenceNodeId } from '../loaders/ask'
import { buildNodeAskQuestion } from '../nodeAskPrompt'
import {
  buildFusionEvidenceStats,
  buildGenericNodeContext,
  buildNodeContentState,
  filterEvidenceRows,
  rankRelationRows,
} from './rightPanelModel'
import { paperRefForAskScope } from '../paperRefs'
import { loadScope, saveScope } from '../scope'
import { ASK_STORE_EVENT, ASK_STORE_KEY, getCurrentAskSession, readAskModuleStateFromStorage } from '../state/askSessions'
import { useGlobalState } from '../state/store'
import type { AskModuleState } from '../state/types'
import { assistantTurnText, buildEvidenceStats, toConversationTurns } from '../panels/askPanelModel'

type PaperPreviewApi = {
  logic_steps?: Array<{ step_type?: string; summary?: string }>
  claims?: Array<{ step_type?: string; text?: string }>
}

type LocalizedText = {
  zh: string
  en: string
}

function pickText(locale: UILocale, text: LocalizedText): string {
  return locale === 'zh-CN' ? text.zh : text.en
}

const KIND_LABELS: Record<string, LocalizedText> = {
  textbook: { zh: '教材', en: 'Textbook' },
  chapter: { zh: '章节', en: 'Chapter' },
  community: { zh: '社区', en: 'Community' },
  paper: { zh: '论文', en: 'Paper' },
  logic: { zh: '逻辑步骤', en: 'Logic Step' },
  claim: { zh: '论断', en: 'Claim' },
  prop: { zh: '命题', en: 'Proposition' },
  group: { zh: '命题组', en: 'Proposition Group' },
  entity: { zh: '实体', en: 'Entity' },
  citation: { zh: '被引文献', en: 'Citation' },
}

const RELATION_LABELS: Record<string, LocalizedText> = {
  cites: { zh: '引用', en: 'Cites' },
  supports: { zh: '支持', en: 'Supports' },
  challenges: { zh: '挑战', en: 'Challenges' },
  supersedes: { zh: '替代', en: 'Supersedes' },
  similar: { zh: '相似', en: 'Similar' },
  maps_to: { zh: '映射', en: 'Maps To' },
  relates_to: { zh: '关联', en: 'Relates To' },
  contains: { zh: '包含', en: 'Contains' },
  evidenced_by: { zh: '证据', en: 'Evidenced By' },
}

function normalizeText(value: unknown): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function kindLabel(kind: string, locale: UILocale) {
  const raw = String(kind ?? '')
  const key = raw === 'proposition' ? 'prop' : raw
  const label = KIND_LABELS[key]
  return label ? pickText(locale, label) : key || 'unknown'
}

function relationLabel(kind: string, locale: UILocale) {
  const key = String(kind ?? '')
  const label = RELATION_LABELS[key]
  return label ? pickText(locale, label) : key || 'unknown'
}

function formatIntentLabel(intent: string, locale: UILocale) {
  const key = normalizeText(intent)
  if (!key) return ''
  if (key === 'foundational') return locale === 'zh-CN' ? '基础知识' : 'Foundational'
  if (key === 'paper_detail') return locale === 'zh-CN' ? '论文细节' : 'Paper Detail'
  if (key === 'hybrid_explanation') return locale === 'zh-CN' ? '混合解释' : 'Hybrid Explanation'
  if (key === 'comparison') return locale === 'zh-CN' ? '比较问题' : 'Comparison'
  return key
}

function prettyValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '-'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-'
  return String(value)
}

function formatMetric(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-'
  return Number(value).toFixed(digits)
}

function shortText(value: unknown, max = 120): string {
  const text = normalizeText(value)
  if (!text) return ''
  if (text.length <= max) return text
  return `${text.slice(0, Math.max(1, max - 3))}...`
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => normalizeText(item)).filter(Boolean)
}

function communityMemberNodeId(memberId: string, memberKind: string): string {
  const kind = normalizeText(memberKind)
  if (kind === 'claim') return `claim:${memberId}`
  if (kind === 'entity' || kind === 'knowledge_entity') return `entity:${memberId}`
  if (kind === 'paper') return `paper:${memberId}`
  if (kind === 'chapter') return `chapter:${memberId}`
  if (kind === 'textbook') return `textbook:${memberId}`
  return kind ? `${kind}:${memberId}` : memberId
}

export function groundingLocationLabel(
  row: NonNullable<AskItem['grounding']>[number] | undefined,
  locale: UILocale,
): string {
  if (!row) return ''
  const parts: string[] = []
  const chunkId = normalizeText(row.chunk_id)
  const chapterId = normalizeText(row.chapter_id)
  const textbookId = normalizeText(row.textbook_id)
  const startLine = Number.isFinite(Number(row.start_line)) ? Number(row.start_line) : null
  const endLine = Number.isFinite(Number(row.end_line)) ? Number(row.end_line) : null
  if (chunkId) parts.push(chunkId)
  else if (chapterId) parts.push(chapterId)
  else if (textbookId) parts.push(textbookId)
  if (startLine !== null && endLine !== null) parts.push(`${locale === 'zh-CN' ? '行' : 'Lines'} ${startLine}-${endLine}`)
  else if (startLine !== null) parts.push(`${locale === 'zh-CN' ? '行' : 'Line'} ${startLine}`)
  return parts.join(' | ')
}

function sourceFromMdPath(mdPath: unknown): string {
  const raw = normalizeText(mdPath)
  if (!raw) return ''
  const parts = raw.replace(/\\/g, '/').split('/').filter(Boolean)
  if (!parts.length) return ''
  const last = parts[parts.length - 1]
  if (/\.md$/i.test(last) && parts.length >= 2) return normalizeText(parts[parts.length - 2])
  return normalizeText(last)
}

function betterGroundingLocationLabel(
  row: NonNullable<AskItem['grounding']>[number] | undefined,
  locale: UILocale,
): string {
  if (!row) return ''
  const parts: string[] = []
  const chunkId = normalizeText(row.chunk_id)
  const chapterId = normalizeText(row.chapter_id)
  const textbookId = normalizeText(row.textbook_id)
  const startLine = Number.isFinite(Number(row.start_line)) && Number(row.start_line) > 0 ? Number(row.start_line) : null
  const endLine = Number.isFinite(Number(row.end_line)) && Number(row.end_line) > 0 ? Number(row.end_line) : null
  if (chunkId) parts.push(chunkId)
  else if (chapterId) parts.push(chapterId)
  else if (textbookId) parts.push(textbookId)
  if (startLine !== null && endLine !== null) parts.push(`${locale === 'zh-CN' ? '\u884c' : 'Lines'} ${startLine}-${endLine}`)
  else if (startLine !== null) parts.push(`${locale === 'zh-CN' ? '\u884c' : 'Line'} ${startLine}`)
  return parts.join(' | ')
}

function summarizeAskTurn(item: AskItem, locale: UILocale): string {
  return shortText(assistantTurnText(item, locale), 180)
}

function loadAskSnapshot(): AskModuleState | null {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') return null
  return readAskModuleStateFromStorage(localStorage.getItem(ASK_STORE_KEY))
}

type Props = {
  collapsed: boolean
  floating?: boolean
  onToggle: () => void
}

export default function RightPanel({ collapsed, floating = false, onToggle }: Props) {
  const { state, dispatch, switchModule } = useGlobalState()
  const { locale, t } = useI18n()
  const { activeModule, ask, selectedNode, graphElements } = state
  const navigate = useNavigate()

  const [askDetailTab, setAskDetailTab] = useState<'summary' | 'node' | 'evidence'>('summary')
  const [showRaw, setShowRaw] = useState(false)
  const [evidenceQuery, setEvidenceQuery] = useState('')
  const [snapshot, setSnapshot] = useState<AskModuleState | null>(() => loadAskSnapshot())
  const [paperPreview, setPaperPreview] = useState<{ logic: string[]; claims: string[] } | null>(null)
  const [paperPreviewLoading, setPaperPreviewLoading] = useState(false)
  const [paperPreviewError, setPaperPreviewError] = useState('')
  const [, setScopeVersion] = useState(0)

  useEffect(() => {
    const timer = window.setTimeout(() => setShowRaw(false), 0)
    return () => window.clearTimeout(timer)
  }, [activeModule, selectedNode?.id])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (activeModule !== 'ask') {
        setAskDetailTab('summary')
        setEvidenceQuery('')
        return
      }
      if (selectedNode) setAskDetailTab('node')
    }, 0)
    return () => window.clearTimeout(timer)
  }, [activeModule, selectedNode])

  useEffect(() => {
    function refreshSnapshot() {
      setSnapshot(loadAskSnapshot())
    }
    refreshSnapshot()
    window.addEventListener('storage', refreshSnapshot)
    window.addEventListener(ASK_STORE_EVENT, refreshSnapshot)
    return () => {
      window.removeEventListener('storage', refreshSnapshot)
      window.removeEventListener(ASK_STORE_EVENT, refreshSnapshot)
    }
  }, [])

  useEffect(() => {
    const refreshScope = () => setScopeVersion((v) => v + 1)
    window.addEventListener('storage', refreshScope)
    window.addEventListener('logickg:scope_changed', refreshScope)
    return () => {
      window.removeEventListener('storage', refreshScope)
      window.removeEventListener('logickg:scope_changed', refreshScope)
    }
  }, [])

  const askCurrentSession = useMemo(() => {
    return getCurrentAskSession(ask) ?? (snapshot ? getCurrentAskSession(snapshot) : null)
  }, [ask, snapshot])

  const askCurrent = useMemo(() => {
    return (
      (askCurrentSession?.currentId
        ? askCurrentSession.history.find((item) => item.id === askCurrentSession.currentId)
        : undefined) ?? askCurrentSession?.history[0]
    )
  }, [askCurrentSession])

  const askTurns = useMemo(
    () => toConversationTurns(askCurrentSession?.history ?? [], askCurrentSession?.currentId ?? null).slice(-12),
    [askCurrentSession],
  )

  const askContext = useMemo(() => {
    if (activeModule !== 'ask') return null

    const nodes = graphElements.filter((element) => element.group === 'nodes').map((element) => element.data as GraphNodeData)
    const edges = graphElements.filter((element) => element.group === 'edges').map((element) => element.data as GraphEdgeData)
    const nodeMap = new Map(nodes.map((node) => [node.id, node]))
    const selectedData = selectedNode ? nodeMap.get(selectedNode.id) ?? null : null
    const evidence = askCurrent?.evidence ?? []

    const counts = {
      paper: 0,
      textbook: 0,
      chapter: 0,
      community: 0,
      logic: 0,
      claim: 0,
      proposition: 0,
      entity: 0,
      citation: 0,
    }
    for (const node of nodes) {
      if (node.kind === 'paper') counts.paper += 1
      else if (node.kind === 'textbook') counts.textbook += 1
      else if (node.kind === 'chapter') counts.chapter += 1
      else if (node.kind === 'community') counts.community += 1
      else if (node.kind === 'logic') counts.logic += 1
      else if (node.kind === 'claim') counts.claim += 1
      else if (node.kind === 'proposition' || node.kind === 'prop') counts.proposition += 1
      else if (node.kind === 'entity') counts.entity += 1
      else if (node.kind === 'citation') counts.citation += 1
    }

    const selectedRelations = selectedNode
      ? edges.filter((edge) => String(edge.source ?? '') === selectedNode.id || String(edge.target ?? '') === selectedNode.id)
      : []

    return {
      nodes,
      edges,
      nodeMap,
      evidence,
      selectedData,
      selectedRelations,
      counts,
    }
  }, [activeModule, askCurrent?.evidence, graphElements, selectedNode])

  const askEvidenceStats = useMemo(() => buildEvidenceStats(askCurrent?.evidence ?? []), [askCurrent?.evidence])
  const askFusionStats = useMemo(() => buildFusionEvidenceStats(askCurrent?.fusionEvidence ?? []), [askCurrent?.fusionEvidence])
  const askFilteredEvidence = useMemo(
    () => filterEvidenceRows(askCurrent?.evidence ?? [], evidenceQuery, 24),
    [askCurrent?.evidence, evidenceQuery],
  )

  const askSubgraphRelationRows = useMemo(() => {
    if (!askContext) return [] as Array<{ kind: string; label: string; count: number }>
    const relationCounts = new Map<string, number>()
    for (const edge of askContext.edges) {
      const kind = normalizeText(edge.kind) || 'relates_to'
      relationCounts.set(kind, (relationCounts.get(kind) ?? 0) + 1)
    }
    return rankRelationRows(
      Array.from(relationCounts.entries()).map(([kind, count]) => ({ kind, label: relationLabel(kind, locale), count })),
      10,
    )
  }, [askContext, locale])

  const askSelectedRelationRows = useMemo(() => {
    if (!askContext) return [] as Array<{ kind: string; label: string; count: number }>
    const relationCounts = new Map<string, number>()
    for (const edge of askContext.selectedRelations) {
      const kind = normalizeText(edge.kind) || 'relates_to'
      relationCounts.set(kind, (relationCounts.get(kind) ?? 0) + 1)
    }
    return rankRelationRows(
      Array.from(relationCounts.entries()).map(([kind, count]) => ({ kind, label: relationLabel(kind, locale), count })),
      8,
    )
  }, [askContext, locale])

  const genericContext = useMemo(() => {
    if (activeModule === 'ask') return null
    const nodes = graphElements.filter((element) => element.group === 'nodes').map((element) => element.data as GraphNodeData)
    const edges = graphElements.filter((element) => element.group === 'edges').map((element) => element.data as GraphEdgeData)
    return buildGenericNodeContext({ selectedNode, nodes, edges })
  }, [activeModule, graphElements, selectedNode])

  const genericPaperId = useMemo(() => {
    if (!genericContext) return ''
    return paperRefForAskScope({
      id: normalizeText(genericContext.center?.id ?? genericContext.raw.selectedNode.id),
      kind: normalizeText(genericContext.center?.kind ?? genericContext.raw.selectedNode.kind),
      paperId: normalizeText(genericContext.center?.paperId ?? genericContext.raw.selectedNode.paperId),
    })
  }, [genericContext])

  const askScopePaperIds = (() => {
    const scope = loadScope()
    if (scope.mode !== 'papers') return [] as string[]
    return (scope.paperIds ?? []).map(String).filter(Boolean)
  })()

  const currentInAskScope = useMemo(() => {
    if (!genericPaperId) return false
    return askScopePaperIds.includes(genericPaperId)
  }, [askScopePaperIds, genericPaperId])

  useEffect(() => {
    if (activeModule === 'ask' || !genericPaperId) {
      const timer = window.setTimeout(() => {
        setPaperPreview(null)
        setPaperPreviewError('')
        setPaperPreviewLoading(false)
      }, 0)
      return () => window.clearTimeout(timer)
    }

    let cancelled = false
    const startTimer = window.setTimeout(() => {
      setPaperPreviewLoading(true)
      setPaperPreviewError('')
    }, 0)
    apiGet<PaperPreviewApi>(`/graph/paper/${encodeURIComponent(genericPaperId)}`)
      .then((res) => {
        if (cancelled) return
        const logic = (res.logic_steps ?? [])
          .map((row) => shortText(`${normalizeText(row.step_type)} ${normalizeText(row.summary)}`, 110))
          .filter(Boolean)
        const claims = (res.claims ?? [])
          .map((row) => shortText(`${normalizeText(row.step_type)} ${normalizeText(row.text)}`, 110))
          .filter(Boolean)
        setPaperPreview({ logic: logic.slice(0, 3), claims: claims.slice(0, 3) })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setPaperPreview(null)
        setPaperPreviewError(String((error as { message?: unknown } | null)?.message ?? error))
      })
      .finally(() => {
        if (!cancelled) setPaperPreviewLoading(false)
      })

    return () => {
      cancelled = true
      window.clearTimeout(startTimer)
    }
  }, [activeModule, genericPaperId])

  const findEvidenceTarget = (row: NonNullable<AskItem['evidence']>[number], index: number): GraphNodeData | null => {
    if (!askContext) return null
    const evidenceNode = askContext.nodeMap.get(buildEvidenceNodeId(row, index))
    if (evidenceNode) return evidenceNode

    const paperTitle = normalizeText(row.paper_title)
    const paperId = normalizeText(row.paper_id)
    if (paperId) {
      const direct = askContext.nodeMap.get(`paper:${paperId}`)
      if (direct) return direct
      const byPaperId = askContext.nodes.find((node) => normalizeText(node.paperId) === paperId)
      if (byPaperId) return byPaperId
    }

    const source = normalizeText(row.paper_source) || sourceFromMdPath(row.md_path)
    if (source) {
      const direct = askContext.nodeMap.get(`paper_source:${source}`)
      if (direct) return direct
      const byLabel = askContext.nodes.find((node) => normalizeText(node.label) === source)
      if (byLabel) return byLabel
    }
    if (paperTitle) {
      const byTitle = askContext.nodes.find((node) => normalizeText(node.label) === paperTitle)
      if (byTitle) return byTitle
    }
    return null
  }

  function selectGraphNode(node: GraphNodeData | null) {
    if (!node) return
    dispatch({
      type: 'SET_SELECTED',
      node: {
        id: node.id,
        kind: node.kind,
        label: node.label,
        description: node.description,
        paperId: node.paperId,
        textbookId: node.textbookId,
        chapterId: node.chapterId,
        propId: node.propId,
      },
    })
  }

  function askFromCurrentNode() {
    if (!genericContext) return
    const node = genericContext.center ?? genericContext.raw.selectedNode
    const nodeKind = normalizeText(node.kind) || 'node'
    const nodeLabel = normalizeText(node.label) || normalizeText(node.id)
    const paperId = genericPaperId
    const question = buildNodeAskQuestion(nodeKind, nodeLabel, locale)

    dispatch({ type: 'ASK_SET_DRAFT', question, k: 8 })
    dispatch({ type: 'ASK_SET_CURRENT', id: null })
    if (paperId) {
      saveScope({ mode: 'papers', paperIds: [paperId] })
    } else {
      saveScope({ mode: 'all' })
    }
    switchModule('ask')
  }

  function addCurrentNodeToAskScope() {
    if (!genericPaperId) return
    const current = loadScope()
    const paperIds = current.mode === 'papers' ? current.paperIds ?? [] : []
    const next = Array.from(new Set([...paperIds.map(String).filter(Boolean), genericPaperId]))
    saveScope({ mode: 'papers', paperIds: next })
  }

  function removeCurrentNodeFromAskScope() {
    if (!genericPaperId) return
    const current = loadScope()
    if (current.mode !== 'papers') return
    const next = (current.paperIds ?? []).map(String).filter((id) => id && id !== genericPaperId)
    if (next.length) {
      saveScope({ mode: 'papers', paperIds: next })
    } else {
      saveScope({ mode: 'all' })
    }
  }

  function askFromSelectedScope() {
    const count = askScopePaperIds.length
    const nodeLabel = normalizeText(genericContext?.center?.label ?? genericContext?.raw.selectedNode.label ?? '')
    const question =
      count > 0
        ? t(
            `请基于当前选中的 ${count} 篇论文做对比总结，给出共识、差异与证据链。${nodeLabel ? ` 参考节点：${nodeLabel}` : ''}`,
            `Compare and summarize the ${count} selected papers, highlighting consensus, differences, and evidence chains.${nodeLabel ? ` Reference node: ${nodeLabel}` : ''}`,
          )
        : t(
            `请基于当前图谱节点做总结，并给出可验证证据链。${nodeLabel}`,
            `Summarize based on the current graph context and provide a verifiable evidence chain.${nodeLabel ? ` ${nodeLabel}` : ''}`,
          )
    dispatch({ type: 'ASK_SET_DRAFT', question, k: 8 })
    dispatch({ type: 'ASK_SET_CURRENT', id: null })
    if (count > 0) {
      saveScope({ mode: 'papers', paperIds: askScopePaperIds })
    } else if (genericPaperId) {
      saveScope({ mode: 'papers', paperIds: [genericPaperId] })
    } else {
      saveScope({ mode: 'all' })
    }
    switchModule('ask')
  }

  function clearAskScope() {
    saveScope({ mode: 'all' })
  }

  const panelClass = ['kgPanel', 'kgPanel--right', floating ? 'kgPanel--floating kgPanel--floating-right' : '']
    .filter(Boolean)
    .join(' ')

  if (collapsed) {
    return (
      <aside className="kgPanel kgPanel--right">
        <div className="kgPanelIcon" onClick={onToggle} title={t('展开右侧信息面板', 'Expand right info panel')}>
          <button className="kgPanelIconBtn" type="button">
            {'>'}
          </button>
        </div>
      </aside>
    )
  }

  if (activeModule === 'ask') {
    const current = askCurrent
    const evidence = askContext?.evidence ?? []
    const counts = askContext?.counts ?? {
      paper: 0,
      textbook: 0,
      chapter: 0,
      community: 0,
      logic: 0,
      claim: 0,
      proposition: 0,
      entity: 0,
      citation: 0,
    }
    const selected = askContext?.selectedData ?? null
    const selectedRelations = askContext?.selectedRelations ?? []
    const graphNodeCount = askContext?.nodes.length ?? 0
    const graphEdgeCount = askContext?.edges.length ?? 0
    const density = graphNodeCount > 0 ? graphEdgeCount / Math.max(graphNodeCount, 1) : 0
    const relationPeak = askSubgraphRelationRows.reduce((max, row) => Math.max(max, row.count), 1)
    const selectedRelationPeak = askSelectedRelationRows.reduce((max, row) => Math.max(max, row.count), 1)
    const scoreBucketPeak = askEvidenceStats.scoreBuckets.reduce((max, row) => Math.max(max, row.count), 1)
    const lineCoverage =
      askEvidenceStats.lineStart !== null && askEvidenceStats.lineEnd !== null
        ? `${askEvidenceStats.lineStart}-${askEvidenceStats.lineEnd}`
        : '-'
    const currentRecord = (current ?? {}) as Record<string, unknown>
    const queryPlanRecord =
      currentRecord.queryPlan && typeof currentRecord.queryPlan === 'object'
        ? (currentRecord.queryPlan as Record<string, unknown>)
        : {}
    const askIntent = formatIntentLabel(
      normalizeText(currentRecord.intent) || normalizeText(queryPlanRecord.intent),
      locale,
    )
    const askRetrievalPlan = normalizeText(currentRecord.retrievalPlan) || normalizeText(queryPlanRecord.retrieval_plan)
    const structuredEvidence = Array.isArray(current?.structuredEvidence) ? current.structuredEvidence : []
    const grounding = Array.isArray(current?.grounding) ? current.grounding : []
    const groundingBySourceId = new Map<string, NonNullable<AskItem['grounding']>[number][]>()
    for (const row of grounding) {
      const sourceId = normalizeText(row.source_id)
      if (!sourceId) continue
      const rows = groundingBySourceId.get(sourceId) ?? []
      const quote = normalizeText(row.quote)
      const existingIndex = rows.findIndex((item) => normalizeText(item.quote) === quote)
      if (existingIndex >= 0) {
        const currentLocation = betterGroundingLocationLabel(rows[existingIndex], locale)
        const nextLocation = betterGroundingLocationLabel(row, locale)
        if (!currentLocation && nextLocation) rows[existingIndex] = row
      } else {
        rows.push(row)
      }
      groundingBySourceId.set(sourceId, rows)
    }

    const selectedRecord = (selected ?? {}) as Record<string, unknown>
    const selectedNodeRecord = (selectedNode ?? {}) as Record<string, unknown>
    const selectedNodeContent = buildNodeContentState({
      label: selected?.label ?? selectedNode?.label,
      description:
        normalizeText(selectedRecord.description) ||
        normalizeText(selectedRecord.summary) ||
        normalizeText(selectedRecord.text) ||
        normalizeText(selectedRecord.snippet) ||
        normalizeText(selectedNodeRecord.description),
      maxChars: 260,
    })
    const nodeContentText = selectedNodeContent.full

    return (
      <aside className={panelClass}>
        <div className="kgPanelHeader">
          <span className="kgPanelTitle">{t('问答上下文', 'Ask Context')}</span>
          <button className="kgPanelCollapseBtn" type="button" onClick={onToggle} title={t('折叠', 'Collapse')}>
            {'>'}
          </button>
        </div>
        <div className="kgPanelContent">
          <div className="kgPanelBody">
            {current ? (
              <div className="kgStack kgAskRightStack">
                <div className="kgAskRightTabs" role="tablist" aria-label={t('问答详情标签页', 'Ask detail tabs')}>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={askDetailTab === 'summary'}
                    className={`kgAskRightTab${askDetailTab === 'summary' ? ' is-active' : ''}`}
                    onClick={() => setAskDetailTab('summary')}
                  >
                    {t('概览', 'Overview')}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={askDetailTab === 'node'}
                    className={`kgAskRightTab${askDetailTab === 'node' ? ' is-active' : ''}`}
                    onClick={() => setAskDetailTab('node')}
                  >
                    {t('节点详情', 'Node Details')}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={askDetailTab === 'evidence'}
                    className={`kgAskRightTab${askDetailTab === 'evidence' ? ' is-active' : ''}`}
                    onClick={() => setAskDetailTab('evidence')}
                  >
                    {t('证据清单', 'Evidence List')}
                  </button>
                </div>

                {askDetailTab === 'summary' && (
                  <div className="kgStack kgAskRightPanel">
                    <div className="kgInfoHero">
                      <div className="kgInfoHeroTitle">{current.question}</div>
                      <div className="kgInfoHeroMeta">
                        <span className="kgTag">{t('状态', 'Status')}: {current.status}</span>
                        <span className="kgTag">k={current.k}</span>
                        {askIntent && <span className="kgTag">{askIntent}</span>}
                        {askRetrievalPlan && <span className="kgTag">{askRetrievalPlan}</span>}
                        <span className="kgTag">{t('教材锚点', 'Textbook Anchors')}: {askFusionStats.total}</span>
                        <span className="kgTag">
                          {t('双证据', 'Dual Evidence')}: {current.dualEvidenceCoverage ? t('已覆盖', 'Covered') : t('未覆盖', 'Missing')}
                        </span>
                        {current.retrievalMode && <span className="kgTag">{t('检索模式', 'Mode')}: {current.retrievalMode}</span>}
                        <span className="kgTag">{t('证据', 'Evidence')}: {evidence.length}</span>
                        <span className="kgTag">
                          {t('子图', 'Subgraph')}: {graphNodeCount}N / {graphEdgeCount}E
                        </span>
                      </div>
                      <div className="kgInfoDescription">{summarizeAskTurn(current, locale)}</div>
                      {current.notice && <div className="kgInfoDescription">{current.notice}</div>}
                    </div>

                    {current.status === 'running' && (
                      <div className="kgCard" style={{ marginBottom: 0 }}>
                        <div className="kgCardTitle">{t('正在检索与推理', 'Searching and Reasoning')}</div>
                        <div className="kgCardBody">{t('系统正在构建问答子图并整理证据，请稍候。', 'Building the QA subgraph and organizing evidence. Please wait.')}</div>
                      </div>
                    )}

                    {current.status === 'error' && (
                      <div className="kgCard" style={{ marginBottom: 0 }}>
                        <div className="kgCardTitle">{t('请求失败', 'Request Failed')}</div>
                        <div className="kgCardBody" style={{ color: 'var(--danger)' }}>
                          {current.error || t('未知错误', 'Unknown error')}
                        </div>
                      </div>
                    )}

                    {current.status === 'done' && !normalizeText(current.answer) && (
                      <div className="kgCard" style={{ marginBottom: 0 }}>
                        <div className="kgCardTitle">{t('结果提示', 'Result Notice')}</div>
                        <div className="kgCardBody">{assistantTurnText(current, locale)}</div>
                      </div>
                    )}
                    <div className="kgSectionTitle">{t('子图指标', 'Subgraph Metrics')}</div>
                    <div className="kgInfoMetricGrid kgAskMetricGrid">
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('论文节点', 'Paper Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.paper}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('逻辑节点', 'Logic Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.logic}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('论断节点', 'Claim Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.claim}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('社区节点', 'Community Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.community}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('引用节点', 'Citation Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.citation}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('证据来源数', 'Evidence Sources')}</div>
                        <div className="kgInfoMetricValue">{askEvidenceStats.sourceCount}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('平均得分', 'Avg Score')}</div>
                        <div className="kgInfoMetricValue">{formatMetric(askEvidenceStats.avgScore, 3)}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('图密度(E/N)', 'Graph Density (E/N)')}</div>
                        <div className="kgInfoMetricValue">{formatMetric(density, 2)}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('行号覆盖', 'Line Coverage')}</div>
                        <div className="kgInfoMetricValue">{lineCoverage}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('教材节点', 'Textbook Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.textbook}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('章节节点', 'Chapter Nodes')}</div>
                        <div className="kgInfoMetricValue">{counts.chapter}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('融合实体', 'Fused Entities')}</div>
                        <div className="kgInfoMetricValue">{counts.entity}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('锚定章节', 'Anchored Chapters')}</div>
                        <div className="kgInfoMetricValue">{askFusionStats.chapterCount}</div>
                      </div>
                    </div>

                    <div className="kgSectionTitle">{t('教材锚点覆盖', 'Textbook Anchor Coverage')}</div>
                    <div className="kgInfoMetricGrid kgAskMetricGrid">
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('锚点条目', 'Anchor Rows')}</div>
                        <div className="kgInfoMetricValue">{askFusionStats.total}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('教材数', 'Textbooks')}</div>
                        <div className="kgInfoMetricValue">{askFusionStats.textbookCount}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('关联论文数', 'Paper Sources')}</div>
                        <div className="kgInfoMetricValue">{askFusionStats.paperSourceCount}</div>
                      </div>
                      <div className="kgInfoMetricCard">
                        <div className="kgInfoMetricLabel">{t('锚点平均分', 'Anchor Avg Score')}</div>
                        <div className="kgInfoMetricValue">{formatMetric(askFusionStats.avgScore, 3)}</div>
                      </div>
                    </div>

                    {askFusionStats.topChapters.length > 0 && (
                      <>
                        <div className="kgSectionTitle">{t('重点锚定章节', 'Top Anchored Chapters')}</div>
                        <div className="kgInfoSection kgAskBarList">
                          {askFusionStats.topChapters.map((row) => (
                            <div key={`ask-anchor-${row.chapterId}`} className="kgAskBarRow">
                              <span className="kgAskBarLabel" title={row.textbookTitle || row.chapterId}>
                                {row.label}
                              </span>
                              <div className="kgAskBarTrack">
                                <div
                                  className="kgAskBarFill"
                                  style={{
                                    width: `${Math.max(
                                      8,
                                      (row.count / Math.max(askFusionStats.topChapters[0]?.count ?? 1, 1)) * 100,
                                    )}%`,
                                  }}
                                />
                              </div>
                              <span className="kgAskBarValue">{row.count}</span>
                            </div>
                          ))}
                        </div>
                      </>
                    )}

                    <div className="kgSectionTitle">{t('关系分布', 'Relation Distribution')}</div>
                    <div className="kgInfoSection kgAskBarList">
                      {askSubgraphRelationRows.map((row) => (
                        <div key={`ask-relation-${row.kind}`} className="kgAskBarRow">
                          <span className="kgAskBarLabel">{row.label}</span>
                          <div className="kgAskBarTrack">
                            <div
                              className="kgAskBarFill"
                              style={{ width: `${Math.max(6, (row.count / Math.max(relationPeak, 1)) * 100)}%` }}
                            />
                          </div>
                          <span className="kgAskBarValue">{row.count}</span>
                        </div>
                      ))}
                      {askSubgraphRelationRows.length === 0 && <div className="text-faint">{t('暂无子图关系数据。', 'No relation data in subgraph yet.')}</div>}
                    </div>

                    {(structuredEvidence.length > 0 || grounding.length > 0) && (
                      <>
                        <div className="kgSectionTitle">{t('结构化证据', 'Structured Evidence')}</div>
                        <div className="kgInfoSection kgStack" style={{ gap: 8 }}>
                          {structuredEvidence.slice(0, 6).map((row, index) => {
                            const rowRecord = row as Record<string, unknown>
                            const rowKind = normalizeText(row.kind || 'structured')
                            const communityId = normalizeText(rowRecord.community_id || (rowKind === 'community' ? row.source_id : ''))
                            const sourceId = normalizeText(row.source_id || row.proposition_id || communityId)
                            const title = normalizeText(row.text || row.source_id || row.proposition_id || communityId || row.kind || `structured-${index + 1}`)
                            const groundingRows = sourceId ? groundingBySourceId.get(sourceId) ?? [] : []
                            const communityKeywords = asStringList(rowRecord.keyword_texts)
                            const representativeMembers = asStringList(rowRecord.member_ids)
                              .map((memberId, memberIndex) => {
                                const memberKind = asStringList(rowRecord.member_kinds)[memberIndex] || ''
                                const graphNode = askContext?.nodeMap.get(communityMemberNodeId(memberId, memberKind))
                                const claimRow = (current.structuredKnowledge?.claims ?? []).find((claim) => normalizeText(claim.claim_id) === memberId)
                                const fusionRow = (current.fusionEvidence ?? []).find((fusionRow) => normalizeText(fusionRow.entity_id) === memberId)
                                return {
                                  memberId,
                                  memberKind: memberKind || normalizeText(graphNode?.kind),
                                  memberLabel:
                                    normalizeText(graphNode?.label)
                                    || normalizeText(claimRow?.text)
                                    || normalizeText(fusionRow?.entity_name)
                                    || memberId,
                                  groundingRows: groundingBySourceId.get(memberId) ?? [],
                                }
                              })
                              .filter((member) => normalizeText(member.memberLabel))

                            if (rowKind === 'community' && communityId) {
                              return (
                                <div key={`structured-${sourceId || index}`} className="kgInfoNeighborCard">
                                  <div className="kgInfoNeighborTitle">{title}</div>
                                  <div className="kgInfoNeighborMeta">
                                    {rowKind} | {communityId}
                                    {row.paper_source ? ` | ${row.paper_source}` : ''}
                                    {row.chapter_id ? ` | ${row.chapter_id}` : ''}
                                  </div>
                                  {communityKeywords.length > 0 && (
                                    <div className="kgStack" style={{ gap: 2, marginTop: 6 }}>
                                      <div className="kgInfoNeighborMeta">{t('社区关键词', 'Community Keywords')}</div>
                                      <div className="kgInfoNeighborMeta">{communityKeywords.join(', ')}</div>
                                    </div>
                                  )}
                                  {representativeMembers.length > 0 && (
                                    <div className="kgStack" style={{ gap: 6, marginTop: 6 }}>
                                      <div className="kgInfoNeighborMeta">{t('代表成员', 'Representative Members')}</div>
                                      {representativeMembers.slice(0, 4).map((member) => (
                                        <div key={`member-${communityId}-${member.memberId}`} className="kgStack" style={{ gap: 2 }}>
                                          <div className="kgInfoNeighborMeta">
                                            {kindLabel(member.memberKind || 'entity', locale)} | {member.memberLabel}
                                          </div>
                                          {member.groundingRows.slice(0, 2).map((groundingRow, groundingIndex) => (
                                            <div key={`member-grounding-${communityId}-${member.memberId}-${groundingIndex}`} className="kgStack" style={{ gap: 2 }}>
                                              <div className="kgInfoNeighborMeta">{normalizeText(groundingRow.quote)}</div>
                                              {betterGroundingLocationLabel(groundingRow, locale) && (
                                                <div className="kgInfoNeighborMeta">{betterGroundingLocationLabel(groundingRow, locale)}</div>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )
                            }

                            return (
                              <div key={`structured-${sourceId || index}`} className="kgInfoNeighborCard">
                                <div className="kgInfoNeighborTitle">{title}</div>
                                <div className="kgInfoNeighborMeta">
                                  {rowKind}
                                  {row.paper_source ? ` | ${row.paper_source}` : ''}
                                  {row.chapter_id ? ` | ${row.chapter_id}` : ''}
                                </div>
                                {groundingRows.slice(0, 2).map((groundingRow, groundingIndex) => (
                                  <div key={`grounding-${sourceId || index}-${groundingIndex}`} className="kgStack" style={{ gap: 2 }}>
                                    <div className="kgInfoNeighborMeta">{normalizeText(groundingRow.quote)}</div>
                                    {betterGroundingLocationLabel(groundingRow, locale) && (
                                      <div className="kgInfoNeighborMeta">{betterGroundingLocationLabel(groundingRow, locale)}</div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )
                          })}
                          {structuredEvidence.length === 0 &&
                            grounding.slice(0, 4).map((row, index) => (
                              <div key={`grounding-only-${index}`} className="kgStack" style={{ gap: 2 }}>
                                <div className="kgInfoNeighborMeta">{normalizeText(row.quote)}</div>
                                {betterGroundingLocationLabel(row, locale) && (
                                  <div className="kgInfoNeighborMeta">{betterGroundingLocationLabel(row, locale)}</div>
                                )}
                              </div>
                            ))}
                        </div>
                      </>
                    )}

                    {askTurns.length > 0 && (
                      <>
                        <div className="kgSectionTitle">{t('最近会话', 'Recent Sessions')}</div>
                        <div className="kgInfoSection kgAskTurnList">
                          {askTurns.map((item) => (
                            <button
                              key={`right-ask-turn-${item.id}`}
                              type="button"
                              className={`kgListItem kgAskTurnItem${item.active ? ' is-active' : ''}`}
                              onClick={() => dispatch({ type: 'ASK_SET_CURRENT', id: item.id })}
                            >
                              <div className="kgListItemMain">
                                <div className="kgListItemTitle">{item.question}</div>
                                <div className="kgListItemMeta">
                                  <span className="kgTag">{t('状态', 'Status')}: {item.status}</span>
                                  <span className="kgTag">k={item.k}</span>
                                  <span>{new Date(item.createdAt).toLocaleTimeString()}</span>
                                </div>
                              </div>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}

                {askDetailTab === 'node' && (
                  <div className="kgStack kgAskRightPanel">
                    {selectedNode ? (
                      <>
                        <div className="kgInfoHero">
                          <div className="kgInfoHeroTitle">{prettyValue(selected?.label ?? selectedNode.label)}</div>
                          <div className="kgInfoHeroMeta">
                            <span className="kgTag">{kindLabel(selected?.kind ?? selectedNode.kind, locale)}</span>
                            <span className="kgTag">ID: {selectedNode.id}</span>
                            {typeof selected?.year === 'number' && <span className="kgTag">{t('年份', 'Year')}: {selected.year}</span>}
                            {typeof selected?.confidence === 'number' && (
                              <span className="kgTag">{t('置信度', 'Confidence')}: {formatMetric(selected.confidence, 3)}</span>
                            )}
                          </div>
                        </div>

                        <div className="kgSectionTitle">{t('基础属性', 'Basic Attributes')}</div>
                        <div className="kgInfoSection">
                          <div className="kgInfoLine">
                            <span>paperId</span>
                            <b>{prettyValue(selected?.paperId ?? selectedNode.paperId)}</b>
                          </div>
                          <div className="kgInfoLine">
                            <span>textbookId</span>
                            <b>{prettyValue(selected?.textbookId ?? selectedNode.textbookId)}</b>
                          </div>
                          <div className="kgInfoLine">
                            <span>chapterId</span>
                            <b>{prettyValue(selected?.chapterId ?? selectedNode.chapterId)}</b>
                          </div>
                          <div className="kgInfoLine">
                            <span>year</span>
                            <b>{prettyValue(selected?.year)}</b>
                          </div>
                          <div className="kgInfoLine">
                            <span>confidence</span>
                            <b>{typeof selected?.confidence === 'number' ? formatMetric(selected.confidence, 3) : '-'}</b>
                          </div>
                          <div className="kgInfoLine">
                            <span>{t('关联边数', 'Connected Edges')}</span>
                            <b>{selectedRelations.length}</b>
                          </div>
                        </div>

                        <div className="kgSectionTitle">{t('节点内容', 'Node Content')}</div>
                        <div className="kgInfoSection kgAskNodeContent">
                          {nodeContentText ? (
                            <div className="kgAskNodeContentText is-expanded">{nodeContentText}</div>
                          ) : (
                            <div className="text-faint">{t('当前节点暂无可展示的内容字段。', 'No displayable content is available for this node.')}</div>
                          )}
                        </div>

                        <div className="kgSectionTitle">{t('关系构成', 'Relation Breakdown')}</div>
                        <div className="kgInfoSection kgAskBarList">
                          {askSelectedRelationRows.map((row) => (
                            <div key={`ask-selected-rel-${row.kind}`} className="kgAskBarRow">
                              <span className="kgAskBarLabel">{row.label}</span>
                              <div className="kgAskBarTrack">
                                <div
                                  className="kgAskBarFill"
                                  style={{ width: `${Math.max(6, (row.count / Math.max(selectedRelationPeak, 1)) * 100)}%` }}
                                />
                              </div>
                              <span className="kgAskBarValue">{row.count}</span>
                            </div>
                          ))}
                          {askSelectedRelationRows.length === 0 && <div className="text-faint">{t('选中节点暂无关系统计。', 'No relation stats for the selected node yet.')}</div>}
                        </div>
                      </>
                    ) : (
                      <div className="kgInfoSection text-faint">
                        {t(
                          '在中间子图中点击任意节点后，这里会展示节点属性、内容预览和关系构成。',
                          'Click a node in the subgraph to view its attributes, content preview, and relation breakdown here.',
                        )}
                      </div>
                    )}
                  </div>
                )}

                {askDetailTab === 'evidence' && (
                  <div className="kgStack kgAskRightPanel">
                    <div className="kgInfoSection">
                      <label className="kgLabel" htmlFor="ask-evidence-query">
                        {t('证据检索', 'Evidence Search')}
                      </label>
                      <input
                        id="ask-evidence-query"
                        className="kgInput"
                        placeholder={t('按论文标题、来源、ID 或 snippet 关键词筛选', 'Filter by title, source, ID, or snippet keyword')}
                        value={evidenceQuery}
                        onChange={(event) => setEvidenceQuery(event.target.value)}
                      />
                      <div className="kgInfoNeighborMeta">
                        {t('显示', 'Showing')} {askFilteredEvidence.length} / {evidence.length} {t('条证据', 'evidence rows')}
                      </div>
                    </div>

                    <div className="kgSectionTitle">{t('证据质量分布', 'Evidence Score Distribution')}</div>
                    <div className="kgInfoSection kgAskBarList">
                      {askEvidenceStats.scoreBuckets.map((bucket) => (
                        <div key={`ask-score-bucket-${bucket.key}`} className="kgAskBarRow">
                          <span className="kgAskBarLabel">{bucket.label}</span>
                          <div className="kgAskBarTrack">
                            <div
                              className="kgAskBarFill"
                              style={{ width: `${Math.max(6, (bucket.count / Math.max(scoreBucketPeak, 1)) * 100)}%` }}
                            />
                          </div>
                          <span className="kgAskBarValue">{bucket.count}</span>
                        </div>
                      ))}
                      {askEvidenceStats.scored === 0 && <div className="text-faint">{t('暂无可评分证据。', 'No scored evidence yet.')}</div>}
                    </div>

                    <div className="kgSectionTitle">{t('证据清单', 'Evidence List')}</div>
                    <div className="kgStack kgAskEvidenceList">
                      {askFilteredEvidence.length ? (
                        askFilteredEvidence.map((row, idx) => {
                          const target = findEvidenceTarget(row, idx)
                          const paperTitle = normalizeText(row.paper_title)
                          const paperId = normalizeText(row.paper_id) || normalizeText(target?.paperId)
                          const source = normalizeText(row.paper_source) || sourceFromMdPath(row.md_path)
                          const openPaperId = paperId || source
                          const scoreValue = Number(row.score)
                          const scoreText = Number.isFinite(scoreValue) ? scoreValue.toFixed(3) : '-'
                          const range =
                            Number.isFinite(row.start_line) && Number.isFinite(row.end_line)
                              ? `${row.start_line}-${row.end_line}`
                              : Number.isFinite(row.start_line)
                                ? String(row.start_line)
                                : '-'
                          const snippet = shortText(row.snippet, 260)

                          return (
                            <div
                              key={`${paperTitle || paperId || source || 'evidence'}-${idx}`}
                              className="kgInfoNeighborCard kgAskEvidenceCard"
                            >
                              <div className="kgInfoNeighborTitle">
                                {paperTitle || source || paperId || `${t('证据', 'Evidence')} ${idx + 1}`}
                              </div>
                              <div className="kgInfoNeighborMeta">{t('得分', 'Score')}: {scoreText} | {t('行号', 'Line')}: {range}</div>
                              {row.md_path && <div className="kgInfoNeighborMeta">{t('路径', 'Path')}: {row.md_path}</div>}
                              {snippet && <div className="kgAskEvidenceSnippet">{snippet}</div>}
                              <div className="kgRow" style={{ marginTop: 6 }}>
                                <button
                                  className="kgBtn kgBtn--sm"
                                  type="button"
                                  disabled={!target}
                                  onClick={() => selectGraphNode(target)}
                                  title={target ? t('在中间子图定位证据节点', 'Locate this evidence node in subgraph') : t('当前子图没有对应节点', 'No matching node in current subgraph')}
                                >
                                  {t('定位图节点', 'Locate Node')}
                                </button>
                                <button
                                  className="kgBtn kgBtn--sm kgBtn--primary"
                                  type="button"
                                  disabled={!openPaperId}
                                  onClick={() => navigate(`/paper/${encodeURIComponent(openPaperId)}`)}
                                >
                                  {t('打开论文', 'Open Paper')}
                                </button>
                              </div>
                            </div>
                          )
                        })
                      ) : (
                        <div className="kgInfoSection text-faint">{t('没有匹配的证据条目，请调整检索关键词。', 'No matching evidence items. Try a different keyword.')}</div>
                      )}
                    </div>
                  </div>
                )}

                <div className="kgRow" style={{ flexWrap: 'wrap' }}>
                  <button className="kgBtn kgBtn--sm" type="button" onClick={() => setShowRaw((value) => !value)}>
                    {showRaw ? t('隐藏原始数据', 'Hide Raw Data') : t('查看原始数据', 'View Raw Data')}
                  </button>
                  <button className="kgBtn kgBtn--sm" type="button" onClick={() => dispatch({ type: 'SET_SELECTED', node: null })}>
                    {t('清除选中', 'Clear Selection')}
                  </button>
                </div>

                {showRaw && (
                  <pre className="kgInfoRaw">
                    {JSON.stringify(
                      {
                        current,
                        selectedNode,
                        graph: {
                          nodes: graphNodeCount,
                          edges: graphEdgeCount,
                        },
                        evidenceStats: askEvidenceStats,
                      },
                      null,
                      2,
                    )}
                  </pre>
                )}
              </div>
            ) : (
              <div className="kgStack">
                <div className="kgCard">
                  <div className="kgCardTitle">{t('问答会话面板', 'Ask Session Panel')}</div>
                  <div className="kgCardBody">
                    {t('左侧发起提问后，这里会展示会话状态、子图指标、节点详情与证据清单。', 'After you ask from the left panel, this area shows session state, subgraph metrics, node details, and evidence list.')}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>
    )
  }

  return (
    <aside className={panelClass}>
      <div className="kgPanelHeader">
        <span className="kgPanelTitle">{t('节点分析', 'Node Analysis')}</span>
        <button className="kgPanelCollapseBtn" type="button" onClick={onToggle} title={t('折叠', 'Collapse')}>
          {'>'}
        </button>
      </div>
      <div className="kgPanelContent">
        <div className="kgPanelBody">
          {genericContext ? (
            <div className="kgStack">
              {(() => {
                const heroKind = genericContext.center?.kind ?? genericContext.raw.selectedNode.kind
                const heroTitle =
                  heroKind === 'paper'
                    ? normalizeText(genericContext.center?.description || genericContext.raw.selectedNode.description)
                      || normalizeText(genericContext.center?.label || genericContext.raw.selectedNode.label)
                    : normalizeText(genericContext.center?.label || genericContext.raw.selectedNode.label)
                const heroSource =
                  heroKind === 'paper' ? normalizeText(genericContext.center?.label || genericContext.raw.selectedNode.label) : ''
                const heroDescription = normalizeText(genericContext.center?.description || genericContext.raw.selectedNode.description)

                return (
                  <div className="kgInfoHero">
                    <div className="kgInfoHeroTitle">{heroTitle}</div>
                    <div className="kgInfoHeroMeta">
                      <span className="kgTag">{kindLabel(heroKind, locale)}</span>
                      {heroSource && <span className="kgTag">{t('标号', 'Source')}: {heroSource}</span>}
                      <span className="kgTag">ID: {genericContext.raw.selectedNode.id}</span>
                      {genericContext.center?.qualityTier && <span className="kgTag">{t('层级', 'Tier')} {genericContext.center.qualityTier}</span>}
                      {typeof genericContext.qualityScore === 'number' && <span className="kgTag">{t('置信', 'Confidence')} {genericContext.qualityScore}%</span>}
                      {typeof genericContext.center?.year === 'number' && <span className="kgTag">{genericContext.center.year}</span>}
                      <span className="kgTag">{t('问答范围', 'Ask Scope')}: {askScopePaperIds.length}</span>
                    </div>
                    {heroKind !== 'paper' && heroDescription && <div className="kgInfoDescription">{heroDescription}</div>}
                  </div>
                )
              })()}

              <div className="kgRow" style={{ flexWrap: 'wrap', gap: 6 }}>
                {genericPaperId && (
                  <button
                    className="kgBtn kgBtn--primary kgBtn--sm"
                    type="button"
                    onClick={() => navigate(`/paper/${encodeURIComponent(genericPaperId)}`)}
                  >
                    {t('打开论文详情', 'Open Paper Detail')}
                  </button>
                )}
                {genericPaperId && (
                  <button
                    className="kgBtn kgBtn--sm"
                    type="button"
                    onClick={() => navigate(`/paper/${encodeURIComponent(genericPaperId)}?tab=logic`)}
                  >
                    {t('查看逻辑步骤', 'View Logic Steps')}
                  </button>
                )}
                {genericPaperId && (
                  <button
                    className="kgBtn kgBtn--sm"
                    type="button"
                    onClick={() => navigate(`/paper/${encodeURIComponent(genericPaperId)}?tab=claims`)}
                  >
                    {t('查看论断', 'View Claims')}
                  </button>
                )}
                {genericPaperId && !currentInAskScope && (
                  <button className="kgBtn kgBtn--sm" type="button" onClick={addCurrentNodeToAskScope}>
                    {t('加入问答选集', 'Add to Ask Scope')}
                  </button>
                )}
                {genericPaperId && currentInAskScope && (
                  <button className="kgBtn kgBtn--sm" type="button" onClick={removeCurrentNodeFromAskScope}>
                    {t('移出问答选集', 'Remove from Ask Scope')}
                  </button>
                )}
                <button className="kgBtn kgBtn--sm" type="button" onClick={askFromSelectedScope}>
                  {t('按选集中提问', 'Ask with Current Scope')}
                </button>
                <button className="kgBtn kgBtn--sm" type="button" onClick={askFromCurrentNode} disabled={!genericPaperId}>
                  {t('从节点发问', 'Ask From Node')}
                </button>
                {askScopePaperIds.length > 0 && (
                  <button className="kgBtn kgBtn--sm" type="button" onClick={clearAskScope}>
                    {t('清空问答选集', 'Clear Ask Scope')}
                  </button>
                )}
              </div>

              {askScopePaperIds.length > 0 && (
                <>
                  <div className="kgSectionTitle">{t('当前 RAG 节点清单', 'Current RAG Node Scope')}</div>
                  <div className="kgInfoSection">
                    <div className="kgInfoNeighborMeta">{t('已选', 'Selected')} {askScopePaperIds.length} {t('个 paper 节点用于 RAG。', 'paper nodes for RAG.')}</div>
                    {askScopePaperIds.slice(0, 8).map((paperId) => (
                      <div key={`rag-scope-${paperId}`} className="kgInfoNeighborMeta">
                        • {paperId}
                      </div>
                    ))}
                    {askScopePaperIds.length > 8 && (
                      <div className="kgInfoNeighborMeta">... {t('其余', 'remaining')} {askScopePaperIds.length - 8} {t('个', '')}</div>
                    )}
                  </div>
                </>
              )}

              <div className="kgInfoMetricGrid">
                <div className="kgInfoMetricCard">
                  <div className="kgInfoMetricLabel">{t('连接度', 'Degree')}</div>
                  <div className="kgInfoMetricValue">{genericContext.degree}</div>
                </div>
                <div className="kgInfoMetricCard">
                  <div className="kgInfoMetricLabel">{t('邻居数', 'Neighbor Count')}</div>
                  <div className="kgInfoMetricValue">{genericContext.neighborCount}</div>
                </div>
                <div className="kgInfoMetricCard">
                  <div className="kgInfoMetricLabel">{t('入边/出边', 'In/Out Edges')}</div>
                  <div className="kgInfoMetricValue">
                    {genericContext.inCount}/{genericContext.outCount}
                  </div>
                </div>
                <div className="kgInfoMetricCard">
                  <div className="kgInfoMetricLabel">{t('子节点', 'Child Nodes')}</div>
                  <div className="kgInfoMetricValue">{genericContext.childNeighbors.length}</div>
                </div>
                <div className="kgInfoMetricCard">
                  <div className="kgInfoMetricLabel">{t('父节点', 'Parent Nodes')}</div>
                  <div className="kgInfoMetricValue">{genericContext.parentNeighbors.length}</div>
                </div>
                <div className="kgInfoMetricCard">
                  <div className="kgInfoMetricLabel">{t('时间跨度', 'Time Span')}</div>
                  <div className="kgInfoMetricValue">{genericContext.timelineRange}</div>
                </div>
              </div>

              <div className="kgSectionTitle">{t('证据链时间线', 'Evidence Timeline')}</div>
              <div className="kgInfoSection kgTimelineList">
                {genericContext.timeline.map((item) => (
                  <div key={item.key} className="kgTimelineRow">
                    <div className="kgTimelineYear">{item.year ?? t('未知', 'Unknown')}</div>
                    <div className="kgTimelineTrack">
                      <div
                        className="kgTimelineBar"
                        style={{ width: `${Math.max(8, (item.total / Math.max(genericContext.timelinePeak, 1)) * 100)}%` }}
                      />
                      <div className="kgTimelineMeta">
                        {item.total} {t('条关系', 'relations')} | {t('引用', 'Cites')} {item.cites} | {t('支持', 'Supports')} {item.supports} | {t('挑战', 'Challenges')} {item.challenges}
                      </div>
                      {item.samples.map((sample, idx) => (
                        <div key={`${item.key}-${idx}`} className="kgTimelineSample">
                          {sample}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                {genericContext.timeline.length === 0 && <div className="text-faint">{t('暂无可展示的时间线证据。', 'No timeline evidence to display.')}</div>}
              </div>

              <div className="kgSectionTitle">{t('关系分布', 'Relation Distribution')}</div>
              <div className="kgInfoSection">
                {genericContext.relationRows.map((row) => (
                  <div key={row.kind} className="kgInfoLine">
                    <span>{relationLabel(row.kind, locale)}</span>
                    <b>{row.count}</b>
                  </div>
                ))}
                {genericContext.relationRows.length === 0 && <div className="text-faint">{t('暂无关系数据。', 'No relation data yet.')}</div>}
              </div>

              <div className="kgSectionTitle">{t('子节点信息', 'Child Node Details')}</div>
              <div className="kgInfoSection kgInfoNeighborList">
                {genericContext.childNeighbors.map((neighbor) => (
                  <div key={neighbor.id} className="kgInfoNeighborCard">
                    <div className="kgInfoNeighborTitle">{neighbor.label}</div>
                    <div className="kgInfoNeighborMeta">
                      {kindLabel(neighbor.kind, locale)} | {t('连接', 'links')} {neighbor.links} | {t('入/出', 'in/out')} {neighbor.inCount}/{neighbor.outCount}
                    </div>
                    <div className="kgInfoNeighborMeta">{t('关系', 'Relations')}: {neighbor.relations.map((kind) => relationLabel(kind, locale)).join(', ') || '-'}</div>
                  </div>
                ))}
                {genericContext.childNeighbors.length === 0 && <div className="text-faint">{t('暂无子节点信息。', 'No child node details yet.')}</div>}
              </div>

              <div className="kgSectionTitle">{t('父节点信息', 'Parent Node Details')}</div>
              <div className="kgInfoSection kgInfoNeighborList">
                {genericContext.parentNeighbors.map((neighbor) => (
                  <div key={neighbor.id} className="kgInfoNeighborCard">
                    <div className="kgInfoNeighborTitle">{neighbor.label}</div>
                    <div className="kgInfoNeighborMeta">
                      {kindLabel(neighbor.kind, locale)} | {t('连接', 'links')} {neighbor.links} | {t('入/出', 'in/out')} {neighbor.inCount}/{neighbor.outCount}
                    </div>
                    <div className="kgInfoNeighborMeta">{t('关系', 'Relations')}: {neighbor.relations.map((kind) => relationLabel(kind, locale)).join(', ') || '-'}</div>
                  </div>
                ))}
                {genericContext.parentNeighbors.length === 0 && <div className="text-faint">{t('暂无父节点信息。', 'No parent node details yet.')}</div>}
              </div>

              <div className="kgSectionTitle">{t('相邻节点', 'Neighbor Nodes')}</div>
              <div className="kgInfoSection kgInfoNeighborList">
                {genericContext.neighbors.map((neighbor) => (
                  <div key={neighbor.id} className="kgInfoNeighborCard">
                    <div className="kgInfoNeighborTitle">{neighbor.label}</div>
                    <div className="kgInfoNeighborMeta">
                      {kindLabel(neighbor.kind, locale)} | {t('连接', 'links')} {neighbor.links} | {t('入/出', 'in/out')} {neighbor.inCount}/{neighbor.outCount}
                    </div>
                    <div className="kgInfoNeighborMeta">{t('关系', 'Relations')}: {neighbor.relations.map((kind) => relationLabel(kind, locale)).join(', ') || '-'}</div>
                  </div>
                ))}
                {genericContext.neighbors.length === 0 && <div className="text-faint">{t('暂无相邻节点。', 'No neighboring nodes yet.')}</div>}
              </div>

              <div className="kgSectionTitle">{t('节点属性', 'Node Properties')}</div>
              <div className="kgInfoSection">
                <div className="kgInfoLine">
                  <span>paperId</span>
                  <b>{prettyValue(genericContext.center?.paperId ?? genericContext.raw.selectedNode.paperId)}</b>
                </div>
                <div className="kgInfoLine">
                  <span>textbookId</span>
                  <b>{prettyValue(genericContext.center?.textbookId ?? genericContext.raw.selectedNode.textbookId)}</b>
                </div>
                <div className="kgInfoLine">
                  <span>propId</span>
                  <b>{prettyValue(genericContext.center?.propId ?? genericContext.raw.selectedNode.propId)}</b>
                </div>
                <div className="kgInfoLine">
                  <span>state</span>
                  <b>{prettyValue(genericContext.center?.state)}</b>
                </div>
                <div className="kgInfoLine">
                  <span>mentions</span>
                  <b>{prettyValue(genericContext.center?.mentions)}</b>
                </div>
                <div className="kgInfoLine">
                  <span>year</span>
                  <b>{prettyValue(genericContext.center?.year)}</b>
                </div>
                <div className="kgInfoLine">
                  <span>resolvedPaperId</span>
                  <b>{prettyValue(genericPaperId)}</b>
                </div>
              </div>

              {genericPaperId && (
                <>
                  <div className="kgSectionTitle">{t('逻辑 / 论断入口', 'Logic / Claim Entry')}</div>
                  <div className="kgInfoSection">
                    <div className="kgInfoLine">
                      <span>{t('论文', 'Paper')}</span>
                      <b>{genericPaperId}</b>
                    </div>
                    {paperPreviewLoading && <div className="kgInfoNeighborMeta">{t('正在加载逻辑步骤与论断...', 'Loading logic steps and claims...')}</div>}
                    {!paperPreviewLoading && paperPreviewError && (
                      <div className="kgInfoNeighborMeta" style={{ color: 'var(--danger)' }}>
                        {t('加载失败', 'Load failed')}: {paperPreviewError}
                      </div>
                    )}
                    {!paperPreviewLoading && !paperPreviewError && paperPreview && (
                      <>
                        <div className="kgInfoNeighborMeta">{t('逻辑步骤', 'Logic steps')}: {paperPreview.logic.length}</div>
                        {paperPreview.logic.map((line, idx) => (
                          <div key={`logic-preview-${idx}`} className="kgInfoNeighborMeta">
                            L{idx + 1}. {line}
                          </div>
                        ))}
                        <div className="kgInfoNeighborMeta" style={{ marginTop: 4 }}>
                          {t('论断', 'Claims')}: {paperPreview.claims.length}
                        </div>
                        {paperPreview.claims.map((line, idx) => (
                          <div key={`claim-preview-${idx}`} className="kgInfoNeighborMeta">
                            C{idx + 1}. {line}
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                </>
              )}

              <div className="kgRow" style={{ flexWrap: 'wrap' }}>
                {(genericContext.center?.textbookId || genericContext.raw.selectedNode.textbookId) && (
                  <button
                    className="kgBtn kgBtn--sm"
                    type="button"
                    onClick={() =>
                      dispatch({
                        type: 'TEXTBOOKS_SELECT',
                        textbookId: String(genericContext.center?.textbookId ?? genericContext.raw.selectedNode.textbookId ?? ''),
                        chapterId: null,
                      })
                    }
                  >
                    {t('定位教材节点', 'Locate Textbook Node')}
                  </button>
                )}
                <button className="kgBtn kgBtn--sm" type="button" onClick={() => setShowRaw((v) => !v)}>
                  {showRaw ? t('隐藏原始属性', 'Hide Raw Properties') : t('查看原始属性', 'View Raw Properties')}
                </button>
                <button className="kgBtn kgBtn--sm" type="button" onClick={() => dispatch({ type: 'SET_SELECTED', node: null })}>
                  {t('清除选中', 'Clear Selection')}
                </button>
              </div>

              {showRaw && <pre className="kgInfoRaw">{JSON.stringify(genericContext.raw, null, 2)}</pre>}
            </div>
          ) : (
            <div className="kgStack">
              <div className="kgCard">
                <div className="kgCardTitle">{t('节点分析面板', 'Node Analysis Panel')}</div>
                <div className="kgCardBody">
                  {t('在图谱中点击节点后，这里会展示属性、关系分布、证据链时间线和跳转操作。', 'After selecting a node in the graph, this panel shows properties, relation distribution, evidence timeline, and quick actions.')}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
