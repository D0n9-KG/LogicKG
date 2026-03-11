import { useCallback, useEffect, useMemo, useState } from 'react'
import { useI18n } from '../i18n'
import {
  invalidateOverviewStatsCache,
  invalidatePaperDataCache,
  invalidateTextbookCatalogCache,
  type TextbookRow,
} from '../loaders/panelData'
import { invalidateOverviewGraphCache, loadOverviewGraph } from '../loaders/overview'
import {
  loadDeleteTask,
  loadPaperManagementRows,
  loadTextbookManagementRows,
  submitPaperDeleteTask,
  submitTextbookDeleteTask,
  type DeleteTaskRecord,
  type PaperManagementRow,
} from '../loaders/sourceManagement'
import { useGlobalState } from '../state/store'

const TERMINAL_TASK_STATUSES = new Set(['succeeded', 'failed', 'canceled'])

function activeSelectionIds(selection: Record<string, boolean>) {
  return Object.entries(selection)
    .filter(([, selected]) => selected)
    .map(([id]) => id)
}

function pruneSelection(selection: Record<string, boolean>, validIds: Set<string>) {
  const next: Record<string, boolean> = {}
  for (const [id, selected] of Object.entries(selection)) {
    if (selected && validIds.has(id)) next[id] = true
  }
  return next
}

function isTaskActive(task: DeleteTaskRecord | null) {
  return ['queued', 'running'].includes(String(task?.status ?? ''))
}

async function waitForDeleteTask(taskId: string, pollMs = 250, maxPolls = 80): Promise<DeleteTaskRecord> {
  let task = await loadDeleteTask(taskId)
  let attempts = 0

  while (!TERMINAL_TASK_STATUSES.has(String(task.status ?? '')) && attempts < maxPolls) {
    await new Promise((resolve) => window.setTimeout(resolve, pollMs))
    task = await loadDeleteTask(taskId)
    attempts += 1
  }

  return task
}

function paperSearchText(row: PaperManagementRow) {
  return [
    row.display_title,
    row.title,
    row.paper_source,
    row.doi,
    row.paper_id,
  ]
    .map((value) => String(value ?? '').trim().toLowerCase())
    .filter(Boolean)
    .join(' ')
}

function taskSummary(task: DeleteTaskRecord | null) {
  return {
    deleted: Number(task?.result?.deleted_count ?? 0),
    failed: Number(task?.result?.failed_count ?? 0),
    skipped: Number(task?.result?.skipped_count ?? 0),
  }
}

function deletedIdsFromTask(task: DeleteTaskRecord, fallbackIds: string[]) {
  const items = Array.isArray(task.result?.items) ? task.result.items : []
  const deletedIds = items
    .map((item) => ({
      id: String(item.id ?? ''),
      status: String(item.status ?? ''),
    }))
    .filter((item) => item.id && item.status === 'deleted')
    .map((item) => item.id)

  if (deletedIds.length > 0) return deletedIds
  return Number(task.result?.deleted_count ?? 0) > 0 ? fallbackIds : []
}

export default function ImportedSourceManagement() {
  const { state, dispatch } = useGlobalState()
  const { t } = useI18n()
  const [paperRows, setPaperRows] = useState<PaperManagementRow[]>([])
  const [textbookRows, setTextbookRows] = useState<TextbookRow[]>([])
  const [paperQuery, setPaperQuery] = useState('')
  const [paperSelection, setPaperSelection] = useState<Record<string, boolean>>({})
  const [textbookSelection, setTextbookSelection] = useState<Record<string, boolean>>({})
  const [paperTask, setPaperTask] = useState<DeleteTaskRecord | null>(null)
  const [textbookTask, setTextbookTask] = useState<DeleteTaskRecord | null>(null)
  const [paperError, setPaperError] = useState('')
  const [textbookError, setTextbookError] = useState('')
  const [loading, setLoading] = useState(true)

  const loadManagementData = useCallback(async () => {
    const [papers, textbooks] = await Promise.all([
      loadPaperManagementRows(),
      loadTextbookManagementRows(),
    ])
    return { papers, textbooks }
  }, [])

  useEffect(() => {
    let cancelled = false
    loadManagementData()
      .then(({ papers, textbooks }) => {
        if (cancelled) return
        setPaperRows(papers)
        setTextbookRows(textbooks)
      })
      .catch((e: unknown) => {
        if (!cancelled) setPaperError(String((e as { message?: unknown })?.message ?? e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [loadManagementData])

  const filteredPaperRows = useMemo(() => {
    const query = paperQuery.trim().toLowerCase()
    if (!query) return paperRows
    return paperRows.filter((row) => paperSearchText(row).includes(query))
  }, [paperQuery, paperRows])

  const ingestedPapers = useMemo(
    () => filteredPaperRows.filter((row) => row.ingested),
    [filteredPaperRows],
  )
  const metadataOnlyPapers = useMemo(
    () => filteredPaperRows.filter((row) => !row.ingested),
    [filteredPaperRows],
  )
  const selectedPaperIds = useMemo(() => activeSelectionIds(paperSelection), [paperSelection])
  const selectedTextbookIds = useMemo(() => activeSelectionIds(textbookSelection), [textbookSelection])

  const syncSelectionsAfterRefresh = useCallback(
    (papers: PaperManagementRow[], textbooks: TextbookRow[]) => {
      setPaperSelection((current) => pruneSelection(current, new Set(papers.filter((row) => row.ingested).map((row) => row.paper_id))))
      setTextbookSelection((current) => pruneSelection(current, new Set(textbooks.map((row) => row.textbook_id))))
    },
    [],
  )

  const restoreNeutralGraphIfNeeded = useCallback(async (
    removedPaperIds: string[],
    removedTextbookIds: string[],
  ) => {
    const paperWasRemoved =
      state.papers.selectedPaperId !== null && removedPaperIds.includes(state.papers.selectedPaperId)
    const textbookWasRemoved =
      state.textbooks.selectedTextbookId !== null && removedTextbookIds.includes(state.textbooks.selectedTextbookId)

    if (paperWasRemoved) {
      dispatch({ type: 'PAPERS_SELECT', paperId: null })
      if (state.activeModule === 'papers') {
        dispatch({ type: 'SET_TRANSITIONING', value: false })
        const els = await loadOverviewGraph(200, 600, { includeTextbooks: false })
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      }
    }

    if (textbookWasRemoved) {
      dispatch({ type: 'TEXTBOOKS_SELECT', textbookId: null, chapterId: null })
      if (state.activeModule === 'textbooks') {
        dispatch({ type: 'SET_TRANSITIONING', value: false })
        const els = await loadOverviewGraph(200, 600)
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      }
    }
  }, [dispatch, state.activeModule, state.papers.selectedPaperId, state.textbooks.selectedTextbookId])

  async function handleDeleteSelectedPapers() {
    if (selectedPaperIds.length === 0 || isTaskActive(paperTask)) return
    setPaperError('')

    try {
      const submitted = await submitPaperDeleteTask(selectedPaperIds)
      const task = await waitForDeleteTask(submitted.task_id)
      setPaperTask(task)

      const deleted = Number(task.result?.deleted_count ?? 0) > 0
      if (deleted) {
        invalidatePaperDataCache()
        invalidateTextbookCatalogCache()
        invalidateOverviewStatsCache()
        invalidateOverviewGraphCache()

        const refreshed = await loadManagementData()
        setPaperRows(refreshed.papers)
        setTextbookRows(refreshed.textbooks)
        syncSelectionsAfterRefresh(refreshed.papers, refreshed.textbooks)
        const removedPaperIds = deletedIdsFromTask(task, selectedPaperIds)
        await restoreNeutralGraphIfNeeded(removedPaperIds, [])
      }

      if (String(task.status ?? '') === 'failed') {
        if (deleted) {
          setPaperError(t('论文已删除，但重建失败。', 'Paper deleted, but rebuild failed.'))
        } else {
          setPaperError(task.error || task.message || t('删除论文失败。', 'Failed to delete papers.'))
        }
      }
    } catch (e: unknown) {
      setPaperError(String((e as { message?: unknown })?.message ?? e))
    }
  }

  async function handleDeleteSelectedTextbooks() {
    if (selectedTextbookIds.length === 0 || isTaskActive(textbookTask)) return
    setTextbookError('')

    try {
      const submitted = await submitTextbookDeleteTask(selectedTextbookIds)
      const task = await waitForDeleteTask(submitted.task_id)
      setTextbookTask(task)

      const deleted = Number(task.result?.deleted_count ?? 0) > 0
      if (deleted) {
        invalidatePaperDataCache()
        invalidateTextbookCatalogCache()
        invalidateOverviewStatsCache()
        invalidateOverviewGraphCache()

        const refreshed = await loadManagementData()
        setPaperRows(refreshed.papers)
        setTextbookRows(refreshed.textbooks)
        syncSelectionsAfterRefresh(refreshed.papers, refreshed.textbooks)
        const removedTextbookIds = deletedIdsFromTask(task, selectedTextbookIds)
        await restoreNeutralGraphIfNeeded([], removedTextbookIds)
      }

      if (String(task.status ?? '') === 'failed') {
        if (deleted) {
          setTextbookError(t('教材已删除，但重建失败。', 'Textbook deleted, but rebuild failed.'))
        } else {
          setTextbookError(task.error || task.message || t('删除教材失败。', 'Failed to delete textbooks.'))
        }
      }
    } catch (e: unknown) {
      setTextbookError(String((e as { message?: unknown })?.message ?? e))
    }
  }

  const paperSummaryState = taskSummary(paperTask)
  const textbookSummaryState = taskSummary(textbookTask)

  return (
    <div className="panel">
      <div className="panelHeader">
        <div className="panelTitle">{t('已导入源管理', 'Imported Source Management')}</div>
      </div>
      <div className="panelBody">
        <div className="grid2">
          <div className="itemCard">
            <div className="split" style={{ gap: 12 }}>
              <div className="itemTitle">{t('论文管理', 'Paper Management')}</div>
              <button
                className="btn btnDanger btnSmall"
                disabled={selectedPaperIds.length === 0 || isTaskActive(paperTask)}
                onClick={() => handleDeleteSelectedPapers().catch(() => {})}
              >
                {t('删除所选论文', 'Delete Selected Papers')}
              </button>
            </div>

            <input
              className="input"
              placeholder={t('搜索论文...', 'Search papers...')}
              value={paperQuery}
              onChange={(e) => setPaperQuery(e.target.value)}
              style={{ marginTop: 10 }}
            />

            {paperError && <div className="errorBox" style={{ marginTop: 10 }}>{paperError}</div>}
            {paperTask && (
              <div className="metaLine" style={{ marginTop: 10 }}>
                {t('已删', 'Deleted')}: {paperSummaryState.deleted} · {t('失败', 'Failed')}: {paperSummaryState.failed} · {t('跳过', 'Skipped')}: {paperSummaryState.skipped}
              </div>
            )}
            {isTaskActive(paperTask) && <div className="metaLine" style={{ marginTop: 10 }}>{t('删除任务进行中...', 'Delete task is running...')}</div>}

            <div className="itemTitle" style={{ marginTop: 14 }}>{t('已导入论文', 'Ingested Papers')}</div>
            <div className="list" style={{ marginTop: 8 }}>
              {ingestedPapers.map((row) => {
                const label = row.display_title || row.title || row.paper_source || row.paper_id
                return (
                  <label key={row.paper_id} className="itemCard" style={{ display: 'block' }}>
                    <div className="split" style={{ gap: 10 }}>
                      <span>
                        <input
                          type="checkbox"
                          aria-label={label}
                          checked={!!paperSelection[row.paper_id]}
                          onChange={(e) => setPaperSelection((current) => ({ ...current, [row.paper_id]: e.target.checked }))}
                        />
                      </span>
                      <span style={{ flex: 1 }}>
                        <div className="itemTitle">{label}</div>
                        <div className="metaLine">
                          {[row.paper_source, row.doi, row.year].filter(Boolean).join(' · ')}
                        </div>
                      </span>
                    </div>
                  </label>
                )
              })}
              {ingestedPapers.length === 0 && <div className="metaLine">{loading ? t('加载中...', 'Loading...') : t('暂无已导入论文。', 'No ingested papers.')}</div>}
            </div>

            <div className="itemTitle" style={{ marginTop: 14 }}>{t('仅元数据论文', 'Metadata-only Papers')}</div>
            <div className="list" style={{ marginTop: 8 }}>
              {metadataOnlyPapers.map((row) => {
                const label = row.display_title || row.title || row.paper_source || row.paper_id
                return (
                  <div key={row.paper_id} className="itemCard">
                    <div className="itemTitle">{label}</div>
                    <div className="metaLine" style={{ marginTop: 4 }}>
                      {t('v1 暂不支持删除，仅展示为只读元数据。', 'Deletion unavailable in v1')}
                    </div>
                  </div>
                )
              })}
              {metadataOnlyPapers.length === 0 && <div className="metaLine">{t('暂无仅元数据论文。', 'No metadata-only papers.')}</div>}
            </div>
          </div>

          <div className="itemCard">
            <div className="split" style={{ gap: 12 }}>
              <div className="itemTitle">{t('教材管理', 'Textbook Management')}</div>
              <button
                className="btn btnDanger btnSmall"
                disabled={selectedTextbookIds.length === 0 || isTaskActive(textbookTask)}
                onClick={() => handleDeleteSelectedTextbooks().catch(() => {})}
              >
                {t('删除所选教材', 'Delete Selected Textbooks')}
              </button>
            </div>

            {textbookError && <div className="errorBox" style={{ marginTop: 10 }}>{textbookError}</div>}
            {textbookTask && (
              <div className="metaLine" style={{ marginTop: 10 }}>
                {t('已删', 'Deleted')}: {textbookSummaryState.deleted} · {t('失败', 'Failed')}: {textbookSummaryState.failed} · {t('跳过', 'Skipped')}: {textbookSummaryState.skipped}
              </div>
            )}
            {isTaskActive(textbookTask) && <div className="metaLine" style={{ marginTop: 10 }}>{t('删除任务进行中...', 'Delete task is running...')}</div>}

            <div className="list" style={{ marginTop: 14 }}>
              {textbookRows.map((row) => (
                <label key={row.textbook_id} className="itemCard" style={{ display: 'block' }}>
                  <div className="split" style={{ gap: 10 }}>
                    <span>
                      <input
                        type="checkbox"
                        aria-label={row.title}
                        checked={!!textbookSelection[row.textbook_id]}
                        onChange={(e) => setTextbookSelection((current) => ({ ...current, [row.textbook_id]: e.target.checked }))}
                      />
                    </span>
                    <span style={{ flex: 1 }}>
                      <div className="itemTitle">{row.title}</div>
                      <div className="metaLine">
                        {t(`${row.chapter_count} 章 · ${row.entity_count} 实体`, `${row.chapter_count} chapters · ${row.entity_count} entities`)}
                      </div>
                    </span>
                  </div>
                </label>
              ))}
              {textbookRows.length === 0 && <div className="metaLine">{loading ? t('加载中...', 'Loading...') : t('暂无教材。', 'No textbooks.')}</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
