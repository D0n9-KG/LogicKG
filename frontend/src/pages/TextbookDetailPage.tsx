import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiGet } from '../api'
import SignalGraph, { type SignalGraphEdge, type SignalGraphNode } from '../components/SignalGraph'

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
  authors: string[]
  year: number | null
  edition: string | null
  doc_type: string
  total_chapters: number
  chapters: ChapterRow[]
}

type EntityRow = {
  entity_id: string
  name: string
  entity_type: string
  description: string
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

type PaperRow = {
  paper_id: string
  title?: string
  paper_source?: string
  year?: number
}

type PaperDetailSummary = {
  logic_steps?: Array<{ step_type?: string; summary?: string }>
  claims?: Array<{ text?: string; step_type?: string; confidence?: number | null }>
}

type ChapterPaperLink = {
  paper: PaperRow
  score: number
  matchedEntities: string[]
}

type GraphMeta = {
  title: string
  detail: string
  paperId?: string
}

function normalizeText(value: string | null | undefined) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fff]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function shortText(value: string | null | undefined, max = 100) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  if (!text) return ''
  if (text.length <= max) return text
  return `${text.slice(0, Math.max(1, max - 3))}...`
}

function scorePaper(paper: PaperRow, entities: EntityRow[]): ChapterPaperLink | null {
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

    const tokens = keyword.split(' ').filter((token) => token.length > 2)
    let tokenHit = 0
    for (const token of tokens) {
      if (haystack.includes(token)) tokenHit += 1
    }

    if (tokenHit > 0) {
      score += Math.min(2, tokenHit)
      matched.add(entity.name)
    }
  }

  if (!score || matched.size === 0) return null
  return { paper, score, matchedEntities: Array.from(matched) }
}

export default function TextbookDetailPage() {
  const nav = useNavigate()
  const { textbookId } = useParams<{ textbookId: string }>()

  const [detail, setDetail] = useState<TextbookDetail | null>(null)
  const [error, setError] = useState('')
  const [selectedChapter, setSelectedChapter] = useState('')
  const [chapterData, setChapterData] = useState<ChapterData | null>(null)
  const [papers, setPapers] = useState<PaperRow[]>([])
  const [selectedPaperId, setSelectedPaperId] = useState('')
  const [paperDetail, setPaperDetail] = useState<PaperDetailSummary | null>(null)
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState('')
  const [loadingChapter, setLoadingChapter] = useState(false)
  const [loadingPaper, setLoadingPaper] = useState(false)

  const loadDetail = useCallback(async () => {
    if (!textbookId) return
    setError('')

    try {
      const [detailRes, paperRes] = await Promise.all([
        apiGet<TextbookDetail>(`/textbooks/${encodeURIComponent(textbookId)}`),
        apiGet<{ papers: PaperRow[] }>('/graph/papers?limit=180'),
      ])

      setDetail(detailRes)
      setPapers(paperRes.papers ?? [])

      if ((detailRes.chapters ?? []).length > 0) {
        setSelectedChapter((prev) => prev || detailRes.chapters[0].chapter_id)
      }
    } catch (e: unknown) {
      setError(String((e as { message?: unknown })?.message ?? e))
    }
  }, [textbookId])

  useEffect(() => {
    void loadDetail()
  }, [loadDetail])

  const loadChapter = useCallback(
    async (chapterId: string) => {
      if (!textbookId || !chapterId) return
      setLoadingChapter(true)
      setChapterData(null)
      setSelectedPaperId('')
      setPaperDetail(null)
      setSelectedGraphNodeId(`ch:${chapterId}`)

      try {
        const result = await apiGet<ChapterData>(
          `/textbooks/${encodeURIComponent(textbookId)}/chapters/${encodeURIComponent(chapterId)}/entities`,
        )
        setChapterData(result)
      } catch (e: unknown) {
        setError(String((e as { message?: unknown })?.message ?? e))
      } finally {
        setLoadingChapter(false)
      }
    },
    [textbookId],
  )

  useEffect(() => {
    if (!selectedChapter) return
    void loadChapter(selectedChapter)
  }, [loadChapter, selectedChapter])

  useEffect(() => {
    if (!selectedPaperId) return
    setLoadingPaper(true)

    apiGet<PaperDetailSummary>(`/graph/paper/${encodeURIComponent(selectedPaperId)}`)
      .then((value) => setPaperDetail(value))
      .catch((e: unknown) => setError(String((e as { message?: unknown })?.message ?? e)))
      .finally(() => setLoadingPaper(false))
  }, [selectedPaperId])

  const chapterLinks = useMemo(() => {
    if (!chapterData?.entities?.length || !papers.length) return []
    const links: ChapterPaperLink[] = []

    for (const paper of papers) {
      const candidate = scorePaper(paper, chapterData.entities)
      if (!candidate) continue
      links.push(candidate)
    }

    return links.sort((a, b) => b.score - a.score || b.matchedEntities.length - a.matchedEntities.length).slice(0, 12)
  }, [chapterData?.entities, papers])

  const chapterSignals = useMemo(() => {
    const entityCount = chapterData?.entities?.length ?? 0
    const relationCount = chapterData?.relations?.length ?? 0
    const avgLinkScore = chapterLinks.length
      ? Number((chapterLinks.reduce((sum, item) => sum + item.score, 0) / chapterLinks.length).toFixed(1))
      : 0
    const relationDensity = entityCount ? Number((relationCount / entityCount).toFixed(2)) : 0
    const claimCount = paperDetail?.claims?.length ?? 0

    return { entityCount, relationCount, avgLinkScore, relationDensity, claimCount }
  }, [chapterData?.entities?.length, chapterData?.relations?.length, chapterLinks, paperDetail?.claims?.length])

  const textbookGraph = useMemo(() => {
    const nodes = new Map<string, SignalGraphNode>()
    const edges = new Map<string, SignalGraphEdge>()
    const metaMap = new Map<string, GraphMeta>()

    if (!detail || !selectedChapter) {
      return { nodes: [] as SignalGraphNode[], edges: [] as SignalGraphEdge[], metaMap }
    }

    const putNode = (node: SignalGraphNode, meta: GraphMeta) => {
      nodes.set(node.id, node)
      metaMap.set(node.id, meta)
    }

    const putEdge = (edge: SignalGraphEdge) => {
      edges.set(edge.id, edge)
    }

    const chapter = detail.chapters.find((item) => item.chapter_id === selectedChapter)
    const textbookNodeId = `tb:${detail.textbook_id}`
    const chapterNodeId = `ch:${selectedChapter}`

    putNode(
      { id: textbookNodeId, label: detail.title, kind: 'textbook', weight: 1 },
      { title: detail.title, detail: `${detail.authors?.join(', ') ?? ''} ${detail.year ?? ''}`.trim() },
    )

    putNode(
      {
        id: chapterNodeId,
        label: chapter ? `Ch.${chapter.chapter_num} ${chapter.title}` : `Chapter ${selectedChapter}`,
        kind: 'chapter',
        weight: 0.9,
      },
      {
        title: chapter ? `第 ${chapter.chapter_num} 章` : '当前章节',
        detail: chapter?.title ?? selectedChapter,
      },
    )

    putEdge({
      id: `${textbookNodeId}->${chapterNodeId}`,
      source: textbookNodeId,
      target: chapterNodeId,
      kind: 'contains',
      weight: 0.8,
    })

    const entityByName = new Map<string, string>()
    for (const entity of (chapterData?.entities ?? []).slice(0, 24)) {
      const entityNodeId = `ent:${entity.entity_id}`
      entityByName.set(entity.name, entityNodeId)

      putNode(
        {
          id: entityNodeId,
          label: shortText(entity.name, 26),
          kind: 'entity',
          weight: 0.26,
        },
        {
          title: entity.name,
          detail: `${entity.entity_type}${entity.description ? ` | ${shortText(entity.description, 100)}` : ''}`,
        },
      )

      putEdge({
        id: `${chapterNodeId}->${entityNodeId}`,
        source: chapterNodeId,
        target: entityNodeId,
        kind: 'contains',
        weight: 0.36,
      })
    }

    for (const link of chapterLinks.slice(0, 10)) {
      const paperNodeId = `paper:${link.paper.paper_id}`

      putNode(
        {
          id: paperNodeId,
          label: shortText(link.paper.title || link.paper.paper_source || link.paper.paper_id, 40),
          kind: 'paper',
          weight: Math.min(1, 0.35 + link.score / 10),
        },
        {
          title: link.paper.title || link.paper.paper_source || link.paper.paper_id,
          detail: `匹配分 ${link.score.toFixed(1)} | 命中实体 ${link.matchedEntities.slice(0, 4).join(', ') || '无'}`,
          paperId: link.paper.paper_id,
        },
      )

      putEdge({
        id: `${chapterNodeId}->${paperNodeId}`,
        source: chapterNodeId,
        target: paperNodeId,
        kind: 'mentions',
        weight: Math.min(1, link.score / 10),
      })

      for (const entityName of link.matchedEntities.slice(0, 4)) {
        const entityNodeId = entityByName.get(entityName)
        if (!entityNodeId) continue

        putEdge({
          id: `${entityNodeId}->${paperNodeId}`,
          source: entityNodeId,
          target: paperNodeId,
          kind: 'supports',
          weight: 0.6,
        })
      }
    }

    if (selectedPaperId) {
      for (const [idx, step] of (paperDetail?.logic_steps ?? []).slice(0, 6).entries()) {
        const logicNodeId = `logic:${selectedPaperId}:${idx}`
        putNode(
          {
            id: logicNodeId,
            label: shortText(step.summary || step.step_type || 'logic', 34),
            kind: 'logic',
            weight: 0.24,
          },
          { title: step.step_type || 'logic', detail: step.summary || '' },
        )

        putEdge({
          id: `paper:${selectedPaperId}->${logicNodeId}`,
          source: `paper:${selectedPaperId}`,
          target: logicNodeId,
          kind: 'contains',
          weight: 0.55,
        })
      }

      for (const [idx, claim] of (paperDetail?.claims ?? []).slice(0, 8).entries()) {
        const claimNodeId = `claim:${selectedPaperId}:${idx}`
        putNode(
          {
            id: claimNodeId,
            label: shortText(claim.text || claim.step_type || 'claim', 34),
            kind: 'claim',
            weight: 0.22,
          },
          {
            title: claim.step_type || 'claim',
            detail: `${shortText(claim.text || '', 160)}${Number.isFinite(Number(claim.confidence)) ? ` | ${(Number(claim.confidence) * 100).toFixed(0)}%` : ''}`,
          },
        )

        putEdge({
          id: `paper:${selectedPaperId}->${claimNodeId}`,
          source: `paper:${selectedPaperId}`,
          target: claimNodeId,
          kind: 'supports',
          weight: 0.6,
        })
      }
    }

    return { nodes: Array.from(nodes.values()), edges: Array.from(edges.values()), metaMap }
  }, [chapterData?.entities, chapterLinks, detail, paperDetail?.claims, paperDetail?.logic_steps, selectedChapter, selectedPaperId])

  const selectedGraphMeta = useMemo(
    () => textbookGraph.metaMap.get(selectedGraphNodeId),
    [selectedGraphNodeId, textbookGraph.metaMap],
  )

  const graphPaperMeta = selectedGraphMeta?.paperId
  const selectedChapterObj = detail?.chapters.find((item) => item.chapter_id === selectedChapter)

  function onSelectGraphNode(nodeId: string) {
    setSelectedGraphNodeId(nodeId)

    if (!nodeId) return
    if (nodeId.startsWith('paper:')) {
      setSelectedPaperId(nodeId.slice('paper:'.length))
      return
    }
    if (nodeId.startsWith('ch:')) {
      const chapterId = nodeId.slice('ch:'.length)
      if (chapterId) setSelectedChapter(chapterId)
    }
  }

  const typeColors: Record<string, string> = {
    concept: '#6ec6ff',
    theory: '#ff9e80',
    equation: '#b39ddb',
    method: '#81c784',
    model: '#ffcc80',
    material: '#90caf9',
    parameter: '#ce93d8',
    phenomenon: '#ef9a9a',
    tool: '#80cbc4',
    condition: '#fff59d',
  }

  if (!detail) {
    return <div className="page">{error ? <div className="errorBox">{error}</div> : <div className="metaLine">加载中...</div>}</div>
  }

  return (
    <div className="page textbookDeck">
      <section className="moduleHero moduleHero--textbook">
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
          <span className="moduleHeroEyebrow">教科书章节作战层</span>
          <h1 className="moduleHeroTitle">章节到论文的智能桥接</h1>
          <p className="moduleHeroSubtitle">查看章节实体与关系，并在统一工作区跟踪匹配论文及其 logic / claim 证据。</p>
          <div className="moduleHeroMeta">
            <span className="pill">
              <span className="kicker">章节</span> {detail.total_chapters}
            </span>
            <span className="pill">
              <span className="kicker">当前</span>{' '}
              {selectedChapterObj ? `第 ${selectedChapterObj.chapter_num} 章` : '未选择'}
            </span>
            <span className="pill">
              <span className="kicker">匹配论文</span> {chapterLinks.length}
            </span>
          </div>
        </div>
        <div className="moduleHeroStats">
          <div className="moduleHeroStatCard">
            <span className="kicker">实体</span>
            <div className="moduleHeroStatValue">{chapterSignals.entityCount}</div>
          </div>
          <div className="moduleHeroStatCard">
            <span className="kicker">关系</span>
            <div className="moduleHeroStatValue">{chapterSignals.relationCount}</div>
          </div>
          <div className="moduleHeroStatCard">
            <span className="kicker">论断</span>
            <div className="moduleHeroStatValue">{chapterSignals.claimCount}</div>
          </div>
        </div>
      </section>

      {error && <div className="errorBox">{error}</div>}

      <div className="textbookDetailLayout textbookDetailWorkspace">
        <div className="textbookChapterTree">
          <Link to="/textbooks" className="metaLine">
            返回教科书列表
          </Link>
          <h2 className="pageTitle" style={{ marginTop: 8, fontSize: 20 }}>
            {detail.title}
          </h2>
          <div className="metaLine" style={{ marginTop: 4 }}>
            {detail.authors?.join(', ')} {detail.year ? `(${detail.year})` : ''}
            {detail.edition ? ` | ${detail.edition}` : ''}
          </div>

          <div style={{ marginTop: 14 }}>
            {detail.chapters.map((chapter) => (
              <div
                key={chapter.chapter_id}
                className={`textbookChapterItem${selectedChapter === chapter.chapter_id ? ' textbookChapterItem--active' : ''}`}
                onClick={() => setSelectedChapter(chapter.chapter_id)}
              >
                <div className="textbookChapterTitle">
                  Ch.{chapter.chapter_num}: {chapter.title}
                </div>
                <div className="textbookChapterMeta">
                  {chapter.entity_count} 实体 | {chapter.relation_count} 关系
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          {!selectedChapter && <div className="metaLine">请选择左侧章节查看详情。</div>}
          {loadingChapter && <div className="metaLine">正在加载章节实体...</div>}

          {chapterData && (
            <div className="stack">
              <div className="textbookSignalStrip" role="list" aria-label="章节信号">
                <div className="textbookSignalCard" role="listitem">
                  <div className="kicker">实体</div>
                  <div className="textbookSignalValue">{chapterSignals.entityCount}</div>
                </div>
                <div className="textbookSignalCard" role="listitem">
                  <div className="kicker">关系</div>
                  <div className="textbookSignalValue">{chapterSignals.relationCount}</div>
                </div>
                <div className="textbookSignalCard" role="listitem">
                  <div className="kicker">关系密度</div>
                  <div className="textbookSignalValue">{chapterSignals.relationDensity}</div>
                </div>
                <div className="textbookSignalCard" role="listitem">
                  <div className="kicker">链接均分</div>
                  <div className="textbookSignalValue">{chapterSignals.avgLinkScore.toFixed(1)}</div>
                </div>
                <div className="textbookSignalCard" role="listitem">
                  <div className="kicker">选中论断</div>
                  <div className="textbookSignalValue">{chapterSignals.claimCount}</div>
                </div>
              </div>

              <div className="panel fusionPanelBevel textbookDeckPanel">
                <div className="panelHeader">
                  <div className="split">
                    <div className="panelTitle">章节-论文互动图谱</div>
                    <span className="pill">
                      <span className="kicker">节点</span> {textbookGraph.nodes.length}
                    </span>
                  </div>
                </div>
                <div className="panelBody">
                  <SignalGraph
                    nodes={textbookGraph.nodes}
                    edges={textbookGraph.edges}
                    selectedId={selectedGraphNodeId}
                    onSelect={onSelectGraphNode}
                    height={460}
                  />
                  <div className="split" style={{ marginTop: 10 }}>
                    <div className="metaLine">
                      {selectedGraphMeta
                        ? `${selectedGraphMeta.title} | ${shortText(selectedGraphMeta.detail, 160)}`
                        : '点击图谱节点可查看详情并联动到论文信息。'}
                    </div>
                    <div className="row" style={{ gap: 8 }}>
                      {graphPaperMeta && (
                        <button
                          className="btn btnSmall"
                          onClick={() => nav(`/paper/${encodeURIComponent(graphPaperMeta)}`)}
                        >
                          打开论文详情
                        </button>
                      )}
                      <button className="btn btnSmall" onClick={() => setSelectedGraphNodeId('')}>
                        清空选中
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="panel fusionPanelBevel textbookDeckPanel">
                <div className="panelHeader">
                  <div className="split">
                    <div className="panelTitle">
                      章节实体 ({chapterData.entities.length}) | 关系 ({chapterData.relations.length})
                    </div>
                    <div className="pill">
                      <span className="kicker">链接论文</span> {chapterLinks.length}
                    </div>
                  </div>
                </div>

                <div className="panelBody">
                  <div className="entityGrid">
                    {chapterData.entities.map((entity) => (
                      <div
                        key={entity.entity_id}
                        className="entityCard"
                        style={{ border: `1px solid ${typeColors[entity.entity_type] ?? 'rgba(146,168,217,0.25)'}` }}
                      >
                        <div className="entityName" style={{ color: typeColors[entity.entity_type] ?? 'rgba(242,248,255,0.94)' }}>
                          {entity.name}
                        </div>
                        <div className="kicker">{entity.entity_type}</div>
                        {entity.description && (
                          <div className="entityDesc">
                            {entity.description.length > 120 ? `${entity.description.slice(0, 120)}...` : entity.description}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>

                  {chapterData.relations.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div className="panelTitle" style={{ marginBottom: 8 }}>
                        关系
                      </div>
                      <table className="relTable">
                        <thead>
                          <tr>
                            <th>源实体</th>
                            <th>关系</th>
                            <th>目标实体</th>
                          </tr>
                        </thead>
                        <tbody>
                          {chapterData.relations.map((relation, idx) => {
                            const src = chapterData.entities.find((entity) => entity.entity_id === relation.source_id)
                            const tgt = chapterData.entities.find((entity) => entity.entity_id === relation.target_id)
                            return (
                              <tr key={`${relation.source_id}->${relation.target_id}:${idx}`}>
                                <td>{src?.name ?? relation.source_id}</td>
                                <td className="metaLine">{relation.rel_type}</td>
                                <td>{tgt?.name ?? relation.target_id}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>

              <div className="panel fusionPanelBevel textbookDeckPanel">
                <div className="panelHeader">
                  <div className="panelTitle">论文 KG 联动</div>
                </div>

                <div className="panelBody textbookPaperBridge">
                  <div className="textbookPaperBridgeList">
                    {chapterLinks.map((link) => (
                      <button
                        key={link.paper.paper_id}
                        className={`textbookPaperCard ${selectedPaperId === link.paper.paper_id ? 'textbookPaperCard--active' : ''}`}
                        onClick={() => setSelectedPaperId(link.paper.paper_id)}
                      >
                        <div className="itemTitle">{shortText(link.paper.title || link.paper.paper_source || link.paper.paper_id, 82)}</div>
                        <div className="itemMeta">
                          评分 {link.score.toFixed(1)} | {link.paper.year ?? '未知'} | 实体 {link.matchedEntities.slice(0, 4).join(', ')}
                        </div>
                      </button>
                    ))}

                    {chapterLinks.length === 0 && <div className="metaLine">当前章节尚未匹配到论文，请先扩充论文库或调整章节实体。</div>}
                  </div>

                  <div className="textbookPaperBridgeDetail itemCard">
                    <div className="split">
                      <div className="itemTitle">论文细节联动</div>
                      {selectedPaperId && (
                        <button className="btn btnSmall" onClick={() => nav(`/paper/${encodeURIComponent(selectedPaperId)}`)}>
                          打开论文详情
                        </button>
                      )}
                    </div>

                    {!selectedPaperId && <div className="metaLine">在左侧选择一篇匹配论文，查看它的 logic 与 claim。</div>}
                    {loadingPaper && <div className="metaLine">正在加载论文图谱详情...</div>}

                    {!loadingPaper && selectedPaperId && (
                      <div className="stack" style={{ marginTop: 8 }}>
                        <div className="list">
                          {(paperDetail?.logic_steps ?? []).slice(0, 4).map((step, idx) => (
                            <div key={`${step.step_type ?? 'logic'}:${idx}`} className="fusionDetailItem">
                              <span className="badge">{step.step_type ?? '逻辑'}</span>
                              <div className="itemBody">{shortText(step.summary || '', 180) || '暂无逻辑摘要'}</div>
                            </div>
                          ))}
                        </div>
                        <div className="list">
                          {(paperDetail?.claims ?? []).slice(0, 4).map((claim, idx) => (
                            <div key={`${claim.step_type ?? 'claim'}:${idx}`} className="fusionDetailItem">
                              <span className="badge">{claim.step_type ?? '论断'}</span>
                              <div className="itemBody">{shortText(claim.text || '', 180) || '暂无论断文本'}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
