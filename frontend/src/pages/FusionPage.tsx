import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiGet } from '../api'
import FusionGraph, { type FusionEdge, type FusionGraphApi, type FusionNode } from '../components/FusionGraph'

type PaperRow = {
  paper_id: string
  title?: string
  paper_source?: string
  doi?: string
  year?: number
}

type TextbookRow = {
  textbook_id: string
  title: string
  authors?: string[]
  year?: number | null
}

type ChapterRow = {
  chapter_id: string
  chapter_num: number
  title: string
  entity_count: number
  relation_count: number
}

type TextbookDetail = {
  textbook_id: string
  title: string
  chapters: ChapterRow[]
}

type EntityRow = {
  entity_id: string
  name: string
  entity_type: string
  description?: string
}

type RelationRow = {
  source_id: string
  target_id: string
  rel_type: string
}

type ChapterData = {
  entities: EntityRow[]
  relations: RelationRow[]
}

type PaperDetailSummary = {
  logic_steps?: Array<{ step_type?: string; summary?: string }>
  claims?: Array<{ text?: string; step_type?: string; confidence?: number | null }>
}

type LinkCandidate = {
  paper: PaperRow
  score: number
  matchedEntities: string[]
}

function normalizeText(value: string | null | undefined) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function shortText(value: string | null | undefined, max = 80) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  if (text.length <= max) return text
  return `${text.slice(0, Math.max(1, max - 3))}...`
}

function scorePaperByEntities(paper: PaperRow, entities: EntityRow[]): LinkCandidate | null {
  const title = normalizeText(paper.title)
  const source = normalizeText(paper.paper_source)
  const haystack = `${title} ${source}`.trim()
  if (!haystack) return null

  let score = 0
  const matched = new Set<string>()
  for (const entity of entities) {
    const keyword = normalizeText(entity.name)
    if (!keyword || keyword.length < 2) continue
    if (title.includes(keyword)) {
      score += 3
      matched.add(entity.name)
      continue
    }
    const parts = keyword.split(' ').filter((part) => part.length > 2)
    let hit = 0
    for (const part of parts) {
      if (haystack.includes(part)) hit += 1
    }
    if (hit > 0) {
      score += Math.min(2, hit)
      matched.add(entity.name)
    }
  }
  if (!score || matched.size === 0) return null
  return { paper, score, matchedEntities: Array.from(matched) }
}

function useAnimatedNumber(target: number, duration = 760) {
  const [display, setDisplay] = useState(target)
  const prevRef = useRef(target)

  useEffect(() => {
    const start = prevRef.current
    const end = target
    if (start === end) {
      return
    }
    const total = Math.max(120, duration)
    const startedAt = performance.now()
    let raf = 0
    const step = (now: number) => {
      const p = Math.min(1, (now - startedAt) / total)
      const eased = 1 - (1 - p) * (1 - p)
      setDisplay(start + (end - start) * eased)
      if (p < 1) {
        raf = window.requestAnimationFrame(step)
      } else {
        prevRef.current = end
        setDisplay(end)
      }
    }
    raf = window.requestAnimationFrame(step)
    return () => window.cancelAnimationFrame(raf)
  }, [duration, target])

  return display
}

export default function FusionPage() {
  const nav = useNavigate()
  const [papers, setPapers] = useState<PaperRow[]>([])
  const [textbooks, setTextbooks] = useState<TextbookRow[]>([])
  const [selectedTextbookId, setSelectedTextbookId] = useState('')
  const [textbookDetail, setTextbookDetail] = useState<TextbookDetail | null>(null)
  const [selectedChapterId, setSelectedChapterId] = useState('')
  const [chapterData, setChapterData] = useState<ChapterData | null>(null)
  const [selectedPaperId, setSelectedPaperId] = useState('')
  const [selectedPaperDetail, setSelectedPaperDetail] = useState<PaperDetailSummary | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState('')
  const [macroMode, setMacroMode] = useState(true)
  const [paperSearch, setPaperSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadingPaper, setLoadingPaper] = useState(false)
  const [error, setError] = useState('')
  const [modeFlash, setModeFlash] = useState(false)
  const [graphApi, setGraphApi] = useState<FusionGraphApi | null>(null)
  const [showPaperNodes, setShowPaperNodes] = useState(true)
  const [showEntityNodes, setShowEntityNodes] = useState(true)
  const [showLogicNodes, setShowLogicNodes] = useState(true)

  const loadBaseData = useCallback(async () => {
    setBusy(true)
    setError('')
    try {
      const [paperRes, textbookRes] = await Promise.all([
        apiGet<{ papers: PaperRow[] }>('/graph/papers?limit=180'),
        apiGet<{ textbooks: TextbookRow[] }>('/textbooks?limit=120'),
      ])
      const nextPapers = paperRes.papers ?? []
      const nextTextbooks = textbookRes.textbooks ?? []
      setPapers(nextPapers)
      setTextbooks(nextTextbooks)
      if (!selectedTextbookId && nextTextbooks.length > 0) {
        setSelectedTextbookId(nextTextbooks[0].textbook_id)
      }
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }, [selectedTextbookId])

  useEffect(() => {
    void loadBaseData()
  }, [loadBaseData])

  useEffect(() => {
    if (!selectedTextbookId) {
      setTextbookDetail(null)
      setSelectedChapterId('')
      return
    }
    let active = true
    setError('')
    apiGet<TextbookDetail>(`/textbooks/${encodeURIComponent(selectedTextbookId)}`)
      .then((detail) => {
        if (!active) return
        setTextbookDetail(detail)
        const firstChapterId = detail.chapters?.[0]?.chapter_id ?? ''
        setSelectedChapterId((prev) => prev || firstChapterId)
      })
      .catch((e: unknown) => {
        if (!active) return
        setError(String((e as { message?: unknown } | null)?.message ?? e))
      })
    return () => {
      active = false
    }
  }, [selectedTextbookId])

  useEffect(() => {
    if (!selectedTextbookId || !selectedChapterId) {
      setChapterData(null)
      return
    }
    let active = true
    apiGet<ChapterData>(
      `/textbooks/${encodeURIComponent(selectedTextbookId)}/chapters/${encodeURIComponent(selectedChapterId)}/entities`,
    )
      .then((data) => {
        if (!active) return
        setChapterData(data)
      })
      .catch((e: unknown) => {
        if (!active) return
        setError(String((e as { message?: unknown } | null)?.message ?? e))
      })
    return () => {
      active = false
    }
  }, [selectedChapterId, selectedTextbookId])

  useEffect(() => {
    if (!selectedPaperId) {
      setSelectedPaperDetail(null)
      return
    }
    let active = true
    setLoadingPaper(true)
    apiGet<PaperDetailSummary>(`/graph/paper/${encodeURIComponent(selectedPaperId)}`)
      .then((detail) => {
        if (!active) return
        setSelectedPaperDetail(detail)
      })
      .catch((e: unknown) => {
        if (!active) return
        setError(String((e as { message?: unknown } | null)?.message ?? e))
      })
      .finally(() => {
        if (!active) return
        setLoadingPaper(false)
      })
    return () => {
      active = false
    }
  }, [selectedPaperId])

  useEffect(() => {
    setModeFlash(true)
    const timer = window.setTimeout(() => setModeFlash(false), 460)
    return () => window.clearTimeout(timer)
  }, [macroMode])

  const chapterEntities = useMemo(() => chapterData?.entities ?? [], [chapterData?.entities])
  const chapterRelations = useMemo(() => chapterData?.relations ?? [], [chapterData?.relations])

  const linkedPapers = useMemo(() => {
    if (!chapterEntities.length || !papers.length) return []
    const matches: LinkCandidate[] = []
    for (const paper of papers) {
      const candidate = scorePaperByEntities(paper, chapterEntities)
      if (!candidate) continue
      matches.push(candidate)
    }
    return matches.sort((a, b) => b.score - a.score || b.matchedEntities.length - a.matchedEntities.length).slice(0, 24)
  }, [chapterEntities, papers])

  const filteredLinks = useMemo(() => {
    const q = normalizeText(paperSearch)
    if (!q) return linkedPapers
    return linkedPapers.filter((item) => {
      const t = normalizeText(item.paper.title)
      const s = normalizeText(item.paper.paper_source)
      return t.includes(q) || s.includes(q)
    })
  }, [linkedPapers, paperSearch])

  const entityTypeStats = useMemo(() => {
    const map = new Map<string, number>()
    for (const entity of chapterEntities) {
      const key = String(entity.entity_type || 'unknown')
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return Array.from(map.entries())
      .map(([entityType, count]) => ({ entityType, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 9)
  }, [chapterEntities])

  const topEntities = useMemo(
    () =>
      [...chapterEntities]
        .sort((a, b) => a.name.localeCompare(b.name))
        .slice(0, 14),
    [chapterEntities],
  )

  const fusionGraph = useMemo(() => {
    const nodeMap = new Map<string, FusionNode>()
    const edgeMap = new Map<string, FusionEdge>()
    const chapterById = new Map<string, ChapterRow>(
      (textbookDetail?.chapters ?? []).map((chapter) => [chapter.chapter_id, chapter]),
    )

    if (textbookDetail) {
      nodeMap.set(`tb:${textbookDetail.textbook_id}`, {
        id: `tb:${textbookDetail.textbook_id}`,
        label: textbookDetail.title,
        kind: 'textbook',
        score: 1,
      })
      for (const chapter of (textbookDetail.chapters ?? []).slice(0, 18)) {
        nodeMap.set(`ch:${chapter.chapter_id}`, {
          id: `ch:${chapter.chapter_id}`,
          label: `Ch.${chapter.chapter_num} ${chapter.title}`,
          kind: 'chapter',
          score: Math.min(1, chapter.entity_count / 18),
        })
        edgeMap.set(`tb:${textbookDetail.textbook_id}->ch:${chapter.chapter_id}`, {
          id: `tb:${textbookDetail.textbook_id}->ch:${chapter.chapter_id}`,
          source: `tb:${textbookDetail.textbook_id}`,
          target: `ch:${chapter.chapter_id}`,
          kind: 'contains',
          weight: 0.7,
        })
      }
    }

    const displayedEntities = chapterEntities.slice(0, 34)
    const displayedEntityByName = new Map(displayedEntities.map((entity) => [entity.name, entity]))

    if (showEntityNodes) {
      for (const entity of displayedEntities) {
        nodeMap.set(`ent:${entity.entity_id}`, {
          id: `ent:${entity.entity_id}`,
          label: entity.name,
          kind: 'entity',
          score: 0.35,
        })
        if (selectedChapterId) {
          edgeMap.set(`ch:${selectedChapterId}->ent:${entity.entity_id}`, {
            id: `ch:${selectedChapterId}->ent:${entity.entity_id}`,
            source: `ch:${selectedChapterId}`,
            target: `ent:${entity.entity_id}`,
            kind: 'contains',
            weight: 0.56,
          })
        }
      }
    }

    if (showPaperNodes) {
      for (const paper of filteredLinks) {
        nodeMap.set(`paper:${paper.paper.paper_id}`, {
          id: `paper:${paper.paper.paper_id}`,
          label: shortText(paper.paper.title || paper.paper.paper_source || paper.paper.paper_id, 56),
          kind: 'paper',
          score: Math.min(1, paper.score / 10),
        })
        for (const entityName of paper.matchedEntities.slice(0, 5)) {
          const entity = displayedEntityByName.get(entityName)
          if (!entity || !showEntityNodes) continue
          edgeMap.set(`ent:${entity.entity_id}->paper:${paper.paper.paper_id}`, {
            id: `ent:${entity.entity_id}->paper:${paper.paper.paper_id}`,
            source: `ent:${entity.entity_id}`,
            target: `paper:${paper.paper.paper_id}`,
            kind: 'mentions',
            weight: Math.min(1, paper.score / 10),
          })
        }
      }
    }

    if (selectedPaperId && showPaperNodes && showLogicNodes) {
      for (const step of (selectedPaperDetail?.logic_steps ?? []).slice(0, 6)) {
        const stepLabel = shortText(step.summary || step.step_type || '逻辑步骤', 40)
        const stepId = `logic:${selectedPaperId}:${step.step_type ?? 'step'}:${stepLabel}`
        nodeMap.set(stepId, { id: stepId, label: stepLabel, kind: 'logic', score: 0.38 })
        edgeMap.set(`paper:${selectedPaperId}->${stepId}`, {
          id: `paper:${selectedPaperId}->${stepId}`,
          source: `paper:${selectedPaperId}`,
          target: stepId,
          kind: 'contains',
          weight: 0.6,
        })
      }
      for (const claim of (selectedPaperDetail?.claims ?? []).slice(0, 6)) {
        const claimText = shortText(claim.text || claim.step_type || '论断', 40)
        const claimId = `claim:${selectedPaperId}:${claimText}`
        nodeMap.set(claimId, { id: claimId, label: claimText, kind: 'claim', score: 0.36 })
        edgeMap.set(`paper:${selectedPaperId}->${claimId}`, {
          id: `paper:${selectedPaperId}->${claimId}`,
          source: `paper:${selectedPaperId}`,
          target: claimId,
          kind: 'supports',
          weight: 0.62,
        })
      }
    }

    if (selectedChapterId && chapterById.has(selectedChapterId)) {
      const chapter = chapterById.get(selectedChapterId)
      if (chapter) {
        nodeMap.set(`ch:${selectedChapterId}`, {
          id: `ch:${selectedChapterId}`,
          label: `Ch.${chapter.chapter_num} ${chapter.title}`,
          kind: 'chapter',
          score: 0.9,
        })
      }
    }

    return {
      nodes: Array.from(nodeMap.values()),
      edges: Array.from(edgeMap.values()),
    }
  }, [
    chapterEntities,
    filteredLinks,
    selectedChapterId,
    selectedPaperDetail?.claims,
    selectedPaperDetail?.logic_steps,
    selectedPaperId,
    showEntityNodes,
    showLogicNodes,
    showPaperNodes,
    textbookDetail,
  ])

  const metrics = useMemo(() => {
    const nodeCount = fusionGraph.nodes.length
    const edgeCount = fusionGraph.edges.length
    const coverage = papers.length ? Math.round((linkedPapers.length / papers.length) * 100) : 0
    const densityValue = nodeCount ? edgeCount / nodeCount : 0
    return {
      paperCount: papers.length,
      textbookCount: textbooks.length,
      nodeCount,
      edgeCount,
      coverage,
      densityValue,
      densityText: densityValue.toFixed(2),
    }
  }, [fusionGraph.edges.length, fusionGraph.nodes.length, linkedPapers.length, papers.length, textbooks.length])

  const selectedNodeMeta = useMemo(() => {
    if (!selectedNodeId) return null
    if (selectedNodeId.startsWith('paper:')) {
      const paperId = selectedNodeId.replace('paper:', '')
      return linkedPapers.find((item) => item.paper.paper_id === paperId) ?? null
    }
    if (selectedNodeId.startsWith('ent:')) {
      const entityId = selectedNodeId.replace('ent:', '')
      return chapterEntities.find((entity) => entity.entity_id === entityId) ?? null
    }
    return null
  }, [chapterEntities, linkedPapers, selectedNodeId])

  const selectedChapter = useMemo(
    () => textbookDetail?.chapters?.find((chapter) => chapter.chapter_id === selectedChapterId) ?? null,
    [selectedChapterId, textbookDetail?.chapters],
  )

  const relationTypeStats = useMemo(() => {
    const map = new Map<string, number>()
    for (const relation of chapterRelations) {
      const key = String(relation.rel_type || 'related_to')
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return Array.from(map.entries())
      .map(([relationType, count]) => ({ relationType, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 6)
  }, [chapterRelations])

  const paperYearTrend = useMemo(() => {
    const map = new Map<number, number>()
    for (const link of linkedPapers) {
      const year = Number(link.paper.year ?? 0)
      if (!year || year < 1900 || year > 2100) continue
      map.set(year, (map.get(year) ?? 0) + 1)
    }
    return Array.from(map.entries())
      .sort((a, b) => a[0] - b[0])
      .slice(-8)
      .map(([year, count]) => ({ year, count }))
  }, [linkedPapers])

  const claimConfidence = useMemo(() => {
    const values = (selectedPaperDetail?.claims ?? [])
      .map((claim) => Number(claim.confidence))
      .filter((value) => Number.isFinite(value))
    if (!values.length) return null
    const avg = values.reduce((sum, value) => sum + value, 0) / values.length
    const high = values.filter((value) => value >= 0.7).length
    return {
      avg,
      highRate: Math.round((high / values.length) * 100),
      count: values.length,
    }
  }, [selectedPaperDetail?.claims])

  const coherenceScore = useMemo(() => {
    const coverageScore = metrics.coverage
    const densityScore = Math.min(100, Math.round(metrics.densityValue * 32))
    const confidenceScore = claimConfidence ? Math.round(claimConfidence.avg * 100) : 45
    return Math.round(coverageScore * 0.45 + densityScore * 0.22 + confidenceScore * 0.33)
  }, [claimConfidence, metrics.coverage, metrics.densityValue])

  const trendMax = useMemo(
    () => (paperYearTrend.length ? Math.max(...paperYearTrend.map((item) => item.count)) : 1),
    [paperYearTrend],
  )

  const operationStages = useMemo(
    () => [
      {
        label: '论文语料',
        detail: `${papers.length} 篇论文`,
        state: papers.length > 0 ? 'ready' : 'idle',
      },
      {
        label: '教科书',
        detail: `${textbooks.length} 本教材`,
        state: textbooks.length > 0 ? 'ready' : 'idle',
      },
      {
        label: '章节绑定',
        detail: selectedChapter ? `第 ${selectedChapter.chapter_num} 章` : '待选择',
        state: selectedChapterId ? 'ready' : 'idle',
      },
      {
        label: '对齐链接',
        detail: `${filteredLinks.length} 条链接`,
        state: filteredLinks.length > 0 ? 'active' : 'idle',
      },
      {
        label: '推理链路',
        detail: selectedPaperId ? `${selectedPaperDetail?.claims?.length ?? 0} 条论断` : '待选择',
        state: selectedPaperId ? 'active' : 'idle',
      },
    ],
    [filteredLinks.length, papers.length, selectedChapter, selectedChapterId, selectedPaperDetail?.claims?.length, selectedPaperId, textbooks.length],
  )

  const paperCountDisplay = useAnimatedNumber(metrics.paperCount)
  const textbookCountDisplay = useAnimatedNumber(metrics.textbookCount)
  const nodeCountDisplay = useAnimatedNumber(metrics.nodeCount)
  const edgeCountDisplay = useAnimatedNumber(metrics.edgeCount)
  const coverageDisplay = useAnimatedNumber(metrics.coverage)
  const coherenceDisplay = useAnimatedNumber(coherenceScore)
  const densityDisplay = useAnimatedNumber(metrics.densityValue)

  const entitySpectrum = useMemo(() => {
    const palette = ['#45c8ff', '#7cffcb', '#7e8bff', '#ffca84', '#f784bd']
    const total = Math.max(1, chapterEntities.length)
    const items = entityTypeStats.slice(0, 5).map((item, idx) => ({
      label: item.entityType,
      count: item.count,
      ratio: item.count / total,
      color: palette[idx % palette.length],
    }))
    if (!items.length) {
      return {
        conic: 'conic-gradient(rgba(90, 125, 174, 0.5) 0deg 360deg)',
        legend: [] as Array<{ label: string; count: number; ratio: number; color: string }>,
      }
    }
    let current = 0
    const parts: string[] = []
    for (const item of items) {
      const next = current + item.ratio * 360
      parts.push(`${item.color} ${current.toFixed(2)}deg ${next.toFixed(2)}deg`)
      current = next
    }
    if (current < 360) {
      parts.push(`rgba(90, 125, 174, 0.38) ${current.toFixed(2)}deg 360deg`)
    }
    return {
      conic: `conic-gradient(${parts.join(', ')})`,
      legend: items,
    }
  }, [chapterEntities.length, entityTypeStats])

  return (
    <div className="page fusionDeck">
      <section className="moduleHero moduleHero--fusion">
        <div className="moduleHeroAurora moduleHeroAurora--a" aria-hidden="true" />
        <div className="moduleHeroAurora moduleHeroAurora--b" aria-hidden="true" />
        <div className="moduleHeroGridFx" aria-hidden="true" />
        <div className="moduleHeroHolo" aria-hidden="true">
          <span className="moduleHeroHoloRing moduleHeroHoloRing--a" />
          <span className="moduleHeroHoloRing moduleHeroHoloRing--b" />
          <span className="moduleHeroHoloSweep" />
          <span className="moduleHeroHoloCore" />
        </div>
        <div className="moduleHeroMain">
          <span className="moduleHeroEyebrow">融合作战层</span>
          <h1 className="moduleHeroTitle">教科书 KG × 论文 KG 融合中枢</h1>
          <p className="moduleHeroSubtitle">
            以宏观 3D 统一编排章节、实体、逻辑与论断信号，并可一键切换到 2D 分析工作台。
          </p>
          <div className="moduleHeroMeta">
            <span className="pill">
              <span className="kicker">模式</span> {macroMode ? '宏观 3D' : '2D 工作台'}
            </span>
            <span className="pill">
              <span className="kicker">节点</span> {fusionGraph.nodes.length}
            </span>
            <span className="pill">
              <span className="kicker">边</span> {fusionGraph.edges.length}
            </span>
          </div>
        </div>
        <div className="moduleHeroStats">
          <div className="moduleHeroStatCard">
            <span className="kicker">链路密度</span>
            <div className="moduleHeroStatValue">{metrics.densityText}</div>
          </div>
          <div className="moduleHeroStatCard">
            <span className="kicker">覆盖率</span>
            <div className="moduleHeroStatValue">{metrics.coverage}%</div>
          </div>
          <div className="moduleHeroStatCard">
            <span className="kicker">一致性</span>
            <div className="moduleHeroStatValue">{coherenceScore}</div>
          </div>
        </div>
      </section>

      <div className="fusionDeckTop">
        <div>
          <h2 className="pageTitle">LogicKG 融合指挥台</h2>
          <div className="pageSubtitle">
            在同一驾驶舱协同教材 KG、论文 KG、逻辑链与论断，并在 3D 战略视角和 2D 检视视角之间切换。
          </div>
        </div>
        <div className="pageActions fusionDeckActions">
          <div className="fusionModeSwitch" role="tablist" aria-label="融合视图模式">
            <button
              className={`btn btnSmall fusionModeBtn ${macroMode ? 'fusionModeBtn--active' : ''}`}
              role="tab"
              aria-selected={macroMode}
              onClick={() => setMacroMode(true)}
            >
              3D 宏观
            </button>
            <button
              className={`btn btnSmall fusionModeBtn ${!macroMode ? 'fusionModeBtn--active' : ''}`}
              role="tab"
              aria-selected={!macroMode}
              onClick={() => setMacroMode(false)}
            >
              2D 工作台
            </button>
          </div>
          <button className="btn" disabled={busy} onClick={() => void loadBaseData()}>
            {busy ? '同步中...' : '同步数据'}
          </button>
        </div>
      </div>

      <div className="fusionTicker">
        <div className="fusionTickerCard">
          <div className="kicker">论文语料</div>
          <div className="fusionTickerValue fusionTickerValue--rolling">{Math.round(paperCountDisplay).toLocaleString()}</div>
        </div>
        <div className="fusionTickerCard">
          <div className="kicker">教材来源</div>
          <div className="fusionTickerValue fusionTickerValue--rolling">{Math.round(textbookCountDisplay).toLocaleString()}</div>
        </div>
        <div className="fusionTickerCard">
          <div className="kicker">融合图谱</div>
          <div className="fusionTickerValue fusionTickerValue--rolling">
            {Math.round(nodeCountDisplay)}N / {Math.round(edgeCountDisplay)}E
          </div>
        </div>
        <div className="fusionTickerCard">
          <div className="kicker">覆盖率</div>
          <div className="fusionTickerValue fusionTickerValue--rolling">{Math.round(coverageDisplay)}%</div>
        </div>
        <div className="fusionTickerCard fusionTickerCard--signal">
          <div className="kicker">系统一致性</div>
          <div className="fusionTickerValue fusionTickerValue--rolling">{Math.round(coherenceDisplay)}</div>
          <div className="fusionTickerMeta">
            <span className={`fusionStatusDot ${coherenceScore >= 70 ? 'fusionStatusDot--ok' : 'fusionStatusDot--warn'}`} />
            {coherenceScore >= 70 ? '融合状态稳定' : '链接仍较稀疏'}
          </div>
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}

      <div className="fusionOpsStrip" role="list" aria-label="融合流程阶段">
        {operationStages.map((stage) => (
          <div key={stage.label} className={`fusionOpsNode fusionOpsNode--${stage.state}`} role="listitem">
            <div className="fusionOpsLabel">{stage.label}</div>
            <div className="fusionOpsDetail">{stage.detail}</div>
          </div>
        ))}
      </div>

      <div className="panel fusionCommandPanel fusionPanelBevel">
        <div className="panelBody fusionCommandBody">
          <label className="fusionControl">
            <span className="kicker">教科书</span>
            <select
              className="select"
              value={selectedTextbookId}
              onChange={(e) => {
                setSelectedTextbookId(e.target.value)
                setSelectedNodeId('')
              }}
            >
              {textbooks.map((textbook) => (
                <option key={textbook.textbook_id} value={textbook.textbook_id}>
                  {textbook.title}
                </option>
              ))}
            </select>
          </label>
          <label className="fusionControl">
            <span className="kicker">章节</span>
            <select
              className="select"
              value={selectedChapterId}
              onChange={(e) => {
                setSelectedChapterId(e.target.value)
                setSelectedNodeId(`ch:${e.target.value}`)
              }}
              disabled={!textbookDetail?.chapters?.length}
            >
              {(textbookDetail?.chapters ?? []).map((chapter) => (
                <option key={chapter.chapter_id} value={chapter.chapter_id}>
                  Ch.{chapter.chapter_num} {chapter.title}
                </option>
              ))}
            </select>
          </label>
          <label className="fusionControl fusionControl--wide">
            <span className="kicker">论文检索</span>
            <input
              className="input"
              value={paperSearch}
              onChange={(e) => setPaperSearch(e.target.value)}
              placeholder="按标题或来源筛选已链接论文"
            />
          </label>
          <div className="fusionCommandMeta">
            <span className="pill">
              <span className="kicker">实体</span> {chapterEntities.length}
            </span>
            <span className="pill">
              <span className="kicker">关系</span> {chapterRelations.length}
            </span>
            <span className="pill">
              <span className="kicker">边密度</span> {densityDisplay.toFixed(2)}
            </span>
          </div>
          <div className="fusionToggleRow">
            <button
              className={`chip ${showPaperNodes ? 'chipActive' : ''}`}
              onClick={() => setShowPaperNodes((v) => !v)}
              type="button"
            >
              论文
            </button>
            <button
              className={`chip ${showEntityNodes ? 'chipActive' : ''}`}
              onClick={() => setShowEntityNodes((v) => !v)}
              type="button"
            >
              实体
            </button>
            <button
              className={`chip ${showLogicNodes ? 'chipActive' : ''}`}
              onClick={() => setShowLogicNodes((v) => !v)}
              type="button"
            >
              逻辑/论断
            </button>
          </div>
        </div>
      </div>

      <div className="fusionDeckLayout">
        <aside className="panel fusionLeftRail fusionPanelBevel">
          <div className="panelHeader">
            <div className="panelTitle">知识焦点图</div>
          </div>
          <div className="panelBody">
            <div className="stack">
              <div className="itemCard fusionSignalCard">
                <div className="itemTitle">{selectedChapter ? `第 ${selectedChapter.chapter_num} 章 ${selectedChapter.title}` : '章节'}</div>
                <div className="itemMeta">
                  {selectedChapter?.entity_count ?? 0} 实体 - {selectedChapter?.relation_count ?? 0} 关系
                </div>
              </div>

              <div className="fusionMiniSection">
                <div className="kicker">实体类型分布</div>
                <div className="fusionBars">
                  {entityTypeStats.map((item) => {
                    const width = chapterEntities.length ? Math.max(8, Math.round((item.count / chapterEntities.length) * 100)) : 0
                    return (
                      <div key={item.entityType} className="fusionBarRow">
                        <span className="fusionBarLabel">{item.entityType}</span>
                        <div className="fusionBarTrack">
                          <div className="fusionBarValue" style={{ width: `${width}%` }} />
                        </div>
                        <span className="fusionBarCount">{item.count}</span>
                      </div>
                    )
                  })}
                  {entityTypeStats.length === 0 && <div className="metaLine">暂无实体统计。</div>}
                </div>
              </div>

              <div className="fusionMiniSection">
                <div className="kicker">关系通道</div>
                <div className="fusionBars">
                  {relationTypeStats.map((item) => {
                    const width = chapterRelations.length ? Math.max(8, Math.round((item.count / chapterRelations.length) * 100)) : 0
                    return (
                      <div key={item.relationType} className="fusionBarRow">
                        <span className="fusionBarLabel">{item.relationType}</span>
                        <div className="fusionBarTrack">
                          <div className="fusionBarValue fusionBarValue--alt" style={{ width: `${width}%` }} />
                        </div>
                        <span className="fusionBarCount">{item.count}</span>
                      </div>
                    )
                  })}
                  {relationTypeStats.length === 0 && <div className="metaLine">暂无关系通道统计。</div>}
                </div>
              </div>

              <div className="fusionMiniSection">
                <div className="kicker">实体入口</div>
                <div className="fusionTags">
                  {topEntities.map((entity) => (
                    <button
                      key={entity.entity_id}
                      className={`chip ${selectedNodeId === `ent:${entity.entity_id}` ? 'chipActive' : ''}`}
                      onClick={() => setSelectedNodeId(`ent:${entity.entity_id}`)}
                      title={entity.description || entity.name}
                    >
                      {shortText(entity.name, 22)}
                    </button>
                  ))}
                  {topEntities.length === 0 && <div className="metaLine">当前章节暂无实体。</div>}
                </div>
              </div>
            </div>
          </div>
        </aside>

        <section className={`panel fusionCenterPanel fusionPanelBevel ${macroMode ? 'fusionCenterPanel--macro' : ''}`}>
          <div className="panelHeader">
            <div className="split">
              <div className="panelTitle">{macroMode ? '宏观融合场' : '2D 融合工作台'}</div>
              <span className="metaLine">
                {fusionGraph.nodes.length} 节点 - {fusionGraph.edges.length} 边
              </span>
            </div>
            <div className="fusionCenterToolbar">
              <button className="btn btnSmall" onClick={() => graphApi?.zoomOut()}>
                -
              </button>
              <button className="btn btnSmall" onClick={() => graphApi?.zoomIn()}>
                +
              </button>
              <button className="btn btnSmall" onClick={() => graphApi?.fit()}>
                适配视图
              </button>
              <button className="btn btnSmall" onClick={() => graphApi?.centerOn(selectedNodeId)}>
                聚焦节点
              </button>
            </div>
          </div>
          <div
            className={`panelBody fusionCenterBody ${macroMode ? 'fusionCenterBody--macro' : 'fusionCenterBody--flat'} ${
              modeFlash ? 'fusionCenterBody--transition' : ''
            }`}
          >
            <div className="fusionStageBadge">{macroMode ? '3D 战略轨道模式' : '2D 分析检视模式'}</div>
            <div className="fusionStageReticle" aria-hidden="true" />
            <div className="fusionStageOrbit fusionStageOrbit--a" aria-hidden="true" />
            <div className="fusionStageOrbit fusionStageOrbit--b" aria-hidden="true" />
            <div className="fusionStageSweepLine" aria-hidden="true" />
            <FusionGraph
              nodes={fusionGraph.nodes}
              edges={fusionGraph.edges}
              selectedId={selectedNodeId}
              mode={macroMode ? 'macro' : 'workbench'}
              onReady={setGraphApi}
              onSelect={(id) => {
                setSelectedNodeId(id)
                if (id.startsWith('paper:')) setSelectedPaperId(id.replace('paper:', ''))
                if (id.startsWith('ch:')) setSelectedChapterId(id.replace('ch:', ''))
              }}
              height={macroMode ? 760 : 560}
            />
          </div>
        </section>

        <aside className="panel fusionRightRail fusionPanelBevel">
          <div className="panelHeader">
            <div className="panelTitle">分析控制台</div>
          </div>
          <div className="panelBody">
            <div className="stack">
              <div className="itemCard fusionSignalCard">
                <div className="itemTitle">信号趋势</div>
                <div className="fusionSparkline">
                  {paperYearTrend.map((item) => (
                    <div key={item.year} className="fusionSparklineBarWrap" title={`${item.year}: ${item.count}`}>
                      <div className="fusionSparklineBar" style={{ height: `${Math.round((item.count / trendMax) * 100)}%` }} />
                      <span>{String(item.year).slice(-2)}</span>
                    </div>
                  ))}
                </div>
                {paperYearTrend.length === 0 && <div className="metaLine">当前链接论文暂无年度趋势数据。</div>}
                <div className="fusionConfidence">
                  <div className="kicker">论断置信度</div>
                  <div className="fusionConfidenceTrack">
                    <div
                      className="fusionConfidenceFill"
                      style={{ width: `${claimConfidence ? Math.round(claimConfidence.avg * 100) : 0}%` }}
                    />
                  </div>
                  <div className="itemMeta">
                    {claimConfidence
                      ? `${Math.round(claimConfidence.avg * 100)}% 平均，${claimConfidence.highRate}% 高置信（${claimConfidence.count}）`
                      : '选择一篇论文以加载置信度画像。'}
                  </div>
                </div>
              </div>

              <div className="itemCard fusionSignalCard">
                <div className="itemTitle">系统遥测</div>
                <div className="fusionTelemetry">
                  <div className="fusionTelemetryRow">
                    <span>覆盖率</span>
                    <div className="fusionTelemetryTrack">
                      <div className="fusionTelemetryFill" style={{ width: `${Math.min(100, metrics.coverage)}%` }} />
                    </div>
                    <span>{metrics.coverage}%</span>
                  </div>
                  <div className="fusionTelemetryRow">
                    <span>关系负载</span>
                    <div className="fusionTelemetryTrack">
                      <div
                        className="fusionTelemetryFill fusionTelemetryFill--alt"
                        style={{
                          width: `${Math.min(100, Math.round((chapterRelations.length / Math.max(1, chapterEntities.length * 2)) * 100))}%`,
                        }}
                      />
                    </div>
                    <span>{chapterRelations.length}</span>
                  </div>
                  <div className="fusionTelemetryRow">
                    <span>推理强度</span>
                    <div className="fusionTelemetryTrack">
                      <div
                        className="fusionTelemetryFill fusionTelemetryFill--warn"
                        style={{ width: `${claimConfidence ? Math.round(claimConfidence.avg * 100) : 0}%` }}
                      />
                    </div>
                    <span>{claimConfidence ? `${Math.round(claimConfidence.avg * 100)}%` : '无'}</span>
                  </div>
                </div>
              </div>

              <div className="itemCard fusionSignalCard">
                <div className="itemTitle">实体光谱</div>
                <div className="fusionSpectrum">
                  <div
                    className="fusionDonut"
                    style={{ '--fusion-conic': entitySpectrum.conic } as CSSProperties}
                    aria-hidden="true"
                  >
                    <div className="fusionDonutInner">{chapterEntities.length}</div>
                  </div>
                  <div className="fusionSpectrumLegend">
                    {entitySpectrum.legend.map((item) => (
                      <div key={item.label} className="fusionSpectrumRow">
                        <span className="fusionSpectrumDot" style={{ backgroundColor: item.color }} />
                        <span className="fusionSpectrumLabel">{item.label}</span>
                        <span className="fusionSpectrumValue">{Math.round(item.ratio * 100)}%</span>
                      </div>
                    ))}
                    {entitySpectrum.legend.length === 0 && <div className="metaLine">暂无实体光谱。</div>}
                  </div>
                </div>
              </div>

              <div className="itemCard">
                <div className="itemTitle">论文候选链接</div>
                <div className="itemMeta">当前章节匹配 {filteredLinks.length} 篇论文。</div>
                <div className="list fusionPaperList">
                  {filteredLinks.slice(0, 10).map((candidate) => (
                    <button
                      key={candidate.paper.paper_id}
                      className={`fusionPaperCard ${selectedPaperId === candidate.paper.paper_id ? 'fusionPaperCard--active' : ''}`}
                      onClick={() => {
                        setSelectedPaperId(candidate.paper.paper_id)
                        setSelectedNodeId(`paper:${candidate.paper.paper_id}`)
                      }}
                    >
                      <div className="fusionPaperCardTitle">
                        {shortText(candidate.paper.title || candidate.paper.paper_source || candidate.paper.paper_id, 72)}
                      </div>
                      <div className="itemMeta">评分 {candidate.score.toFixed(1)}</div>
                      <div className="fusionMatchMeter">
                        <div
                          className="fusionMatchMeterFill"
                          style={{ width: `${Math.min(100, Math.round((candidate.score / 10) * 100))}%` }}
                        />
                      </div>
                    </button>
                  ))}
                  {filteredLinks.length === 0 && <div className="metaLine">当前章节暂无教材-论文链接。</div>}
                </div>
              </div>

              <div className="itemCard">
                <div className="split">
                  <div className="itemTitle">逻辑 + 论断</div>
                  {selectedPaperId && (
                    <button className="btn btnSmall" onClick={() => nav(`/paper/${encodeURIComponent(selectedPaperId)}`)}>
                      打开论文
                    </button>
                  )}
                </div>
                {loadingPaper && <div className="metaLine">正在加载论文详情...</div>}
                {!loadingPaper && !selectedPaperId && <div className="metaLine">选择论文节点以查看逻辑与论断。</div>}
                {!loadingPaper && selectedPaperId && (
                  <div className="stack">
                    <div className="list">
                      {(selectedPaperDetail?.logic_steps ?? []).slice(0, 4).map((step, idx) => (
                        <div key={`${step.step_type ?? 'step'}:${idx}`} className="fusionDetailItem">
                          <span className="badge">{step.step_type ?? '逻辑'}</span>
                          <div className="itemBody">{shortText(step.summary || '', 180) || '暂无摘要'}</div>
                        </div>
                      ))}
                    </div>
                    <div className="list">
                      {(selectedPaperDetail?.claims ?? []).slice(0, 4).map((claim, idx) => (
                        <div key={`${claim.step_type ?? 'claim'}:${idx}`} className="fusionDetailItem">
                          <span className="badge">{claim.step_type ?? '论断'}</span>
                          <div className="itemBody">{shortText(claim.text || '', 180) || '暂无论断文本'}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {selectedNodeMeta && (
                <div className="itemCard">
                  <div className="itemTitle">选中节点上下文</div>
                  {'entity_id' in selectedNodeMeta ? (
                    <>
                      <div className="itemMeta">
                        实体：{selectedNodeMeta.name} - {selectedNodeMeta.entity_type}
                      </div>
                      <div className="itemBody">{shortText(selectedNodeMeta.description || '', 220) || '暂无描述'}</div>
                    </>
                  ) : (
                    <>
                      <div className="itemMeta">匹配实体：{selectedNodeMeta.matchedEntities.join(', ')}</div>
                      <div className="itemBody">
                        {selectedNodeMeta.paper.title || selectedNodeMeta.paper.paper_source || selectedNodeMeta.paper.paper_id}
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}
