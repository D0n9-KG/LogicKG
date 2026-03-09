// frontend/src/panels/PapersPanel.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { apiDelete, apiPatch, apiPost } from '../api'
import { useI18n } from '../i18n'
import {
  invalidateOverviewStatsCache,
  invalidatePaperDataCache,
  loadPaperCatalog,
  loadPaperCollections,
  type CollectionRow,
  type PaperRow,
} from '../loaders/panelData'
import { saveScope } from '../scope'
import { useGlobalState } from '../state/store'
import { loadPaperNeighborhood } from '../loaders/papers'
import { invalidateOverviewGraphCache, loadOverviewGraph } from '../loaders/overview'

export default function PapersPanel() {
  const { state, dispatch, switchModule } = useGlobalState()
  const { locale, t } = useI18n()
  const { papers } = state
  const [allPapers, setAllPapers] = useState<PaperRow[]>([])
  const [collections, setCollections] = useState<CollectionRow[]>([])
  const [collectionFilter, setCollectionFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const selectReqRef = useRef<string | null>(null)

  // Modal states
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignPaper, setAssignPaper] = useState<PaperRow | null>(null)
  const [assignSelected, setAssignSelected] = useState<Record<string, boolean>>({})
  const [assignBusy, setAssignBusy] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [collEditOpen, setCollEditOpen] = useState(false)
  const [collEditMode, setCollEditMode] = useState<'create' | 'rename'>('create')
  const [collEditName, setCollEditName] = useState('')
  const [collEditBusy, setCollEditBusy] = useState(false)

  const reloadCollections = useCallback(async () => {
    setCollections(await loadPaperCollections())
  }, [])

  const reloadPapers = useCallback(async () => {
    setLoading(true)
    try {
      setAllPapers(await loadPaperCatalog(collectionFilter))
    } catch (e: unknown) {
      setError(String((e as { message?: unknown })?.message ?? e))
    } finally {
      setLoading(false)
    }
  }, [collectionFilter])

  // Load graph on mount
  useEffect(() => {
    let cancelled = false
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    loadOverviewGraph()
      .then((els) => { if (!cancelled) dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' }) })
      .catch(() => {})
      .finally(() => { if (!cancelled) dispatch({ type: 'SET_TRANSITIONING', value: false }) })
    return () => { cancelled = true }
  }, [dispatch])

  useEffect(() => { reloadCollections().catch(() => {}) }, [reloadCollections])
  useEffect(() => { reloadPapers().catch(() => {}) }, [reloadPapers])

  const filtered = useMemo(() => {
    const q = papers.searchQuery.toLowerCase()
    return allPapers
      .filter((p) => !q || `${p.title ?? ''} ${p.paper_source ?? ''}`.toLowerCase().includes(q))
      .sort((a, b) => (b.year ?? 0) - (a.year ?? 0))
  }, [allPapers, papers.searchQuery])

  function selectPaper(paperId: string) {
    dispatch({ type: 'PAPERS_SELECT', paperId })
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    selectReqRef.current = paperId
    loadPaperNeighborhood(paperId)
      .then((els) => {
        if (selectReqRef.current !== paperId) return
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'concentric' })
      })
      .catch(() => {})
      .finally(() => {
        if (selectReqRef.current === paperId) dispatch({ type: 'SET_TRANSITIONING', value: false })
      })
  }

  function openAssign(p: PaperRow, e: React.MouseEvent) {
    e.stopPropagation()
    const sel: Record<string, boolean> = {}
    for (const c of p.collections ?? []) sel[c.collection_id] = true
    setAssignSelected(sel)
    setAssignPaper(p)
    setAssignOpen(true)
  }

  async function saveAssign() {
    if (!assignPaper) return
    setAssignBusy(true)
    try {
      const before = new Set((assignPaper.collections ?? []).map((c) => c.collection_id))
      const after = new Set<string>(Object.entries(assignSelected).filter(([, value]) => value).map(([key]) => key))
      for (const cid of [...after].filter((value): value is string => !before.has(value)))
        await apiPost(`/collections/${encodeURIComponent(cid)}/papers/${encodeURIComponent(assignPaper.paper_id)}`, {})
      for (const cid of [...before].filter((value): value is string => !after.has(value)))
        await apiDelete(`/collections/${encodeURIComponent(cid)}/papers/${encodeURIComponent(assignPaper.paper_id)}`)
      invalidatePaperDataCache()
      setAssignOpen(false)
      await reloadPapers()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown })?.message ?? e))
    } finally {
      setAssignBusy(false)
    }
  }

  async function confirmDelete() {
    setDeleteBusy(true)
    try {
      await apiDelete(`/papers/${encodeURIComponent(deleteConfirmId)}`)
      invalidatePaperDataCache()
      invalidateOverviewStatsCache()
      invalidateOverviewGraphCache()
      setDeleteConfirmId('')
      await reloadPapers()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown })?.message ?? e))
    } finally {
      setDeleteBusy(false)
    }
  }

  async function submitCollEdit() {
    const name = collEditName.trim()
    if (!name) return
    if (collEditMode === 'rename' && (collectionFilter === 'all' || collectionFilter === '__uncategorized__')) return
    setCollEditBusy(true)
    try {
      if (collEditMode === 'create') {
        await apiPost('/collections', { name })
      } else {
        await apiPatch(`/collections/${encodeURIComponent(collectionFilter)}`, { name })
      }
      invalidatePaperDataCache()
      await reloadCollections()
      setCollEditOpen(false)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown })?.message ?? e))
    } finally {
      setCollEditBusy(false)
    }
  }

  function askByCurrentFilter() {
    const pickedIds = filtered.slice(0, 300).map((p) => String(p.paper_id)).filter(Boolean)
    if (!pickedIds.length) return

    if (collectionFilter !== 'all' && collectionFilter !== '__uncategorized__') {
      saveScope({ mode: 'collection', collectionId: collectionFilter })
      dispatch({
        type: 'ASK_SET_DRAFT',
        question:
          locale === 'zh-CN'
            ? '请基于当前论文集总结关键方法、结论差异与证据链。'
            : 'Summarize key methods, conclusion differences, and evidence chains for this collection.',
        k: 8,
      })
    } else {
      saveScope({ mode: 'papers', paperIds: pickedIds })
      dispatch({
        type: 'ASK_SET_DRAFT',
        question:
          locale === 'zh-CN'
            ? `请基于当前筛选出的 ${pickedIds.length} 篇论文进行对比总结，并给出证据链。`
            : `Compare and summarize the ${pickedIds.length} filtered papers, and provide the evidence chain.`,
        k: 8,
      })
    }
    dispatch({ type: 'ASK_SET_CURRENT', id: null })
    switchModule('ask')
  }

  return (
    <div className="kgPanelBody kgStack">
      {/* 搜索 */}
      <input
        className="kgInput"
        placeholder={t('搜索论文...', 'Search papers...')}
        value={papers.searchQuery}
        onChange={(e) => dispatch({ type: 'PAPERS_SEARCH', query: e.target.value })}
      />

      {/* 集合过滤 */}
      <select
        className="kgInput"
        style={{ fontSize: 11 }}
        value={collectionFilter}
        onChange={(e) => setCollectionFilter(e.target.value)}
      >
        <option value="all">{t('全部论文', 'All Papers')}</option>
        <option value="__uncategorized__">{t('未分类', 'Uncategorized')}</option>
        {collections.map((c) => (
          <option key={c.collection_id} value={c.collection_id}>{c.name}</option>
        ))}
      </select>

      {/* 集合操作按钮 */}
      <div className="kgRow" style={{ flexWrap: 'wrap', gap: 4 }}>
        <button
          type="button"
          className="kgBtn kgBtn--sm"
          onClick={() => { setCollEditMode('create'); setCollEditName(''); setCollEditOpen(true) }}
        >
          {t('+ 新建集合', '+ New Collection')}
        </button>
        {collectionFilter !== 'all' && collectionFilter !== '__uncategorized__' && (
          <button
            type="button"
            className="kgBtn kgBtn--sm"
            onClick={() => {
              const c = collections.find((x) => x.collection_id === collectionFilter)
              setCollEditMode('rename')
              setCollEditName(c?.name ?? '')
              setCollEditOpen(true)
            }}
          >
            {t('重命名', 'Rename')}
          </button>
        )}
        <button
          type="button"
          className="kgBtn kgBtn--sm kgBtn--primary"
          onClick={askByCurrentFilter}
          disabled={filtered.length === 0}
          title={
            collectionFilter !== 'all' && collectionFilter !== '__uncategorized__'
              ? t('按当前论文集提问', 'Ask by current collection')
              : t('按当前筛选论文提问', 'Ask by current filtered papers')
          }
        >
          {t('按当前筛选提问', 'Ask Filtered Set')}
        </button>
      </div>

      {error && <div style={{ fontSize: 10.5, color: 'var(--danger)' }}>{error}</div>}
      {loading && <div className="text-faint" style={{ fontSize: 11 }}>{t('加载中...', 'Loading...')}</div>}

      {/* 论文列表 */}
      <div className="kgStack" style={{ gap: 4 }}>
        {filtered.slice(0, 100).map((p) => (
          <div
            key={p.paper_id}
            className={`kgListItem${papers.selectedPaperId === p.paper_id ? ' is-active' : ''}`}
            onClick={() => selectPaper(p.paper_id)}
          >
            <div className="kgListItemTitle truncate">{p.title || p.paper_source || p.paper_id}</div>
            <div className="kgListItemMeta" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>{p.year ?? '—'} · {p.ingested ? t('已导入', 'Ingested') : t('仅元数据', 'Metadata Only')}</span>
              <div style={{ display: 'flex', gap: 4 }} onClick={(e) => e.stopPropagation()}>
                <button
                  type="button"
                  className="kgBtn kgBtn--sm"
                  style={{ fontSize: 10, padding: '1px 6px' }}
                  onClick={(e) => openAssign(p, e)}
                >
                  {t('集合', 'Collection')}
                </button>
                <button
                  type="button"
                  className="kgBtn kgBtn--sm"
                  style={{ fontSize: 10, padding: '1px 6px', color: 'var(--danger)' }}
                  onClick={(e) => { e.stopPropagation(); setDeleteConfirmId(p.paper_id) }}
                >
                  {t('删除', 'Delete')}
                </button>
              </div>
            </div>
          </div>
        ))}
        {filtered.length > 100 && (
          <div className="text-faint" style={{ fontSize: 10.5, textAlign: 'center' }}>
            {t(`显示前 100 条 / 共 ${filtered.length} 条`, `Showing first 100 of ${filtered.length}`)}
          </div>
        )}
      </div>

      {/* 分配集合弹窗 */}
      {assignOpen && assignPaper && createPortal(
        <div className="modalOverlay" onClick={() => !assignBusy && setAssignOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">{t('分配集合', 'Assign Collection')}</div>
              <button type="button" className="btn btnSmall" disabled={assignBusy} onClick={() => setAssignOpen(false)}>{t('关闭', 'Close')}</button>
            </div>
            <div className="modalBody">
              <div className="hint" style={{ marginBottom: 10, fontSize: 11 }}>
                {t('论文', 'Paper')}: {assignPaper.paper_source || assignPaper.paper_id}
              </div>
              <div className="list">
                {collections.map((c) => (
                  <div key={c.collection_id} className="itemCard">
                    <div className="split">
                      <div className="itemTitle">{c.name}</div>
                      <input
                        type="checkbox"
                        checked={!!assignSelected[c.collection_id]}
                        onChange={(e) => setAssignSelected((m) => ({ ...m, [c.collection_id]: e.target.checked }))}
                      />
                    </div>
                  </div>
                ))}
                {collections.length === 0 && <div className="metaLine">{t('暂无集合，请先新建。', 'No collections yet. Create one first.')}</div>}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="btn btnPrimary" disabled={assignBusy} onClick={() => saveAssign().catch(() => {})}>
                  {assignBusy ? t('保存中...', 'Saving...') : t('保存', 'Save')}
                </button>
                <button type="button" className="btn" disabled={assignBusy} onClick={() => setAssignOpen(false)}>{t('取消', 'Cancel')}</button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 删除确认弹窗 */}
      {deleteConfirmId && createPortal(
        <div className="modalOverlay" onClick={() => !deleteBusy && setDeleteConfirmId('')}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">{t('删除论文', 'Delete Paper')}</div>
              <button type="button" className="btn btnSmall" disabled={deleteBusy} onClick={() => setDeleteConfirmId('')}>{t('关闭', 'Close')}</button>
            </div>
            <div className="modalBody">
              <div className="hint">
                {t(
                  '确认删除该论文？将删除 Neo4j 图数据及所有派生文件。',
                  'Delete this paper? This will remove Neo4j graph data and derived files.',
                )}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="btn btnDanger" disabled={deleteBusy} onClick={() => confirmDelete().catch(() => {})}>
                  {deleteBusy ? t('删除中...', 'Deleting...') : t('确定删除', 'Confirm Delete')}
                </button>
                <button type="button" className="btn" disabled={deleteBusy} onClick={() => setDeleteConfirmId('')}>{t('取消', 'Cancel')}</button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* 集合编辑弹窗 */}
      {collEditOpen && createPortal(
        <div className="modalOverlay" onClick={() => !collEditBusy && setCollEditOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">{collEditMode === 'create' ? t('新建集合', 'Create Collection') : t('重命名集合', 'Rename Collection')}</div>
              <button type="button" className="btn btnSmall" disabled={collEditBusy} onClick={() => setCollEditOpen(false)}>{t('关闭', 'Close')}</button>
            </div>
            <div className="modalBody">
              <input
                className="input"
                value={collEditName}
                onChange={(e) => setCollEditName(e.target.value)}
                placeholder={t('集合名称...', 'Collection name...')}
              />
              <div className="row" style={{ marginTop: 12 }}>
                <button
                  type="button"
                  className="btn btnPrimary"
                  disabled={collEditBusy || !collEditName.trim()}
                  onClick={() => submitCollEdit().catch(() => {})}
                >
                  {collEditBusy ? t('提交中...', 'Submitting...') : t('确定', 'Confirm')}
                </button>
                <button type="button" className="btn" disabled={collEditBusy} onClick={() => setCollEditOpen(false)}>{t('取消', 'Cancel')}</button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}
