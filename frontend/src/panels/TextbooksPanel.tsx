import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import {
  invalidateOverviewStatsCache,
  invalidateTextbookCatalogCache,
  loadTextbookCatalog,
  loadTextbookChapters,
  type ChapterRow,
  type TextbookRow,
} from '../loaders/panelData'
import { invalidateOverviewGraphCache, loadOverviewGraph } from '../loaders/overview'
import { loadDeleteTask, submitTextbookDeleteTask, type DeleteTaskRecord } from '../loaders/sourceManagement'
import { useGlobalState } from '../state/store'
import { buildTextbookChapterOverviewGraph, loadTextbookEntityGraph } from '../loaders/textbooks'

const TERMINAL_TASK_STATUSES = new Set(['succeeded', 'failed', 'canceled'])

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

export default function TextbooksPanel() {
  const { state, dispatch } = useGlobalState()
  const { t } = useI18n()
  const { textbooks } = state
  const [allTextbooks, setAllTextbooks] = useState<TextbookRow[]>([])
  const [chapters, setChapters] = useState<ChapterRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [deleteConfirmId, setDeleteConfirmId] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)
  const selectReqRef = useRef<string | null>(null)
  const selectedTextbook = useMemo(
    () => allTextbooks.find((row) => row.textbook_id === textbooks.selectedTextbookId) ?? null,
    [allTextbooks, textbooks.selectedTextbookId],
  )

  const reloadTextbooks = useCallback(async (force = false) => {
    return loadTextbookCatalog(100, force ? { force: true } : {})
  }, [])

  useEffect(() => {
    dispatch({ type: 'SET_TRANSITIONING', value: false })
    let cancelled = false
    reloadTextbooks()
      .then((rows) => {
        if (!cancelled) setAllTextbooks(rows)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(String((e as { message?: unknown })?.message ?? e))
      })
    return () => {
      cancelled = true
    }
  }, [dispatch, reloadTextbooks])

  function selectTextbook(textbookId: string) {
    setError('')
    dispatch({ type: 'TEXTBOOKS_SELECT', textbookId, chapterId: null })
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    setLoading(true)
    selectReqRef.current = textbookId
    loadTextbookChapters(textbookId)
      .then((chapterRows) => {
        if (selectReqRef.current !== textbookId) return
        setChapters(chapterRows)
        const textbook = allTextbooks.find((row) => row.textbook_id === textbookId)
        const els = buildTextbookChapterOverviewGraph(
          {
            textbook_id: textbookId,
            title: textbook?.title ?? textbookId,
          },
          chapterRows,
        )
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      })
      .catch(() => {})
      .finally(() => {
        if (selectReqRef.current === textbookId) {
          setLoading(false)
          dispatch({ type: 'SET_TRANSITIONING', value: false })
        }
      })
  }

  function clearSelectedTextbook() {
    selectReqRef.current = null
    setChapters([])
    dispatch({ type: 'TEXTBOOKS_SELECT', textbookId: null, chapterId: null })
    dispatch({ type: 'SET_TRANSITIONING', value: false })
  }

  function selectChapter(chapterId: string) {
    if (!textbooks.selectedTextbookId) return
    const reqKey = `chapter:${chapterId}`
    selectReqRef.current = reqKey
    dispatch({ type: 'TEXTBOOKS_SELECT', textbookId: textbooks.selectedTextbookId, chapterId })
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    loadTextbookEntityGraph(textbooks.selectedTextbookId, chapterId)
      .then((els) => {
        if (selectReqRef.current !== reqKey) return
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      })
      .catch(() => {})
      .finally(() => {
        if (selectReqRef.current === reqKey) dispatch({ type: 'SET_TRANSITIONING', value: false })
      })
  }

  async function confirmDelete() {
    if (!deleteConfirmId) return
    setDeleteBusy(true)
    setError('')

    try {
      const textbookId = deleteConfirmId
      const wasSelected = textbooks.selectedTextbookId === textbookId
      const submitted = await submitTextbookDeleteTask([textbookId])
      const task = await waitForDeleteTask(submitted.task_id)
      const deleted = Number(task.result?.deleted_count ?? 0) > 0

      if (deleted) {
        invalidateTextbookCatalogCache()
        invalidateOverviewStatsCache()
        invalidateOverviewGraphCache()
      }

      setDeleteConfirmId('')

      if (deleted) {
        const rows = await reloadTextbooks(true)
        setAllTextbooks(rows)
      }

      if (deleted && wasSelected) {
        clearSelectedTextbook()
        const els = await loadOverviewGraph(200, 600)
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      }

      if (String(task.status ?? '') === 'failed') {
        if (deleted) {
          setError(t('教材已删除，但重建失败。', 'Textbook deleted, but rebuild failed.'))
        } else {
          setError(task.error || task.message || t('删除教材失败。', 'Failed to delete textbook.'))
        }
        return
      }

      if (!deleted) {
        setError(t('没有可删除的教材数据。', 'No textbook data was deleted.'))
      }
    } catch (e: unknown) {
      setError(String((e as { message?: unknown })?.message ?? e))
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="kgPanelBody kgStack">
      {error && <div style={{ fontSize: 10.5, color: 'var(--danger)' }}>{error}</div>}

      {!textbooks.selectedTextbookId ? (
        <div className="kgStack" style={{ gap: 4 }}>
          <div className="kgSectionTitle">{t('教材列表', 'Textbook List')}</div>
          {allTextbooks.map((row) => (
            <div key={row.textbook_id} className="kgListItem" onClick={() => selectTextbook(row.textbook_id)}>
              <div className="kgListItemTitle truncate">{row.title}</div>
              <div className="kgListItemMeta">{t(`${row.chapter_count} 章 · ${row.entity_count} 实体`, `${row.chapter_count} chapters · ${row.entity_count} entities`)}</div>
            </div>
          ))}
        </div>
      ) : (
        <>
          <div className="kgRow" style={{ justifyContent: 'space-between', gap: 8 }}>
            <button className="kgBtn kgBtn--sm" onClick={clearSelectedTextbook}>
              {t('返回教材列表', 'Back to Textbook List')}
            </button>
            <button
              className="kgBtn kgBtn--sm"
              style={{ color: 'var(--danger)' }}
              onClick={() => setDeleteConfirmId(textbooks.selectedTextbookId ?? '')}
            >
              {t('删除', 'Delete')}
            </button>
          </div>
          {selectedTextbook && <div className="kgSectionTitle">{selectedTextbook.title}</div>}
          {loading && <div className="text-faint" style={{ fontSize: 11 }}>{t('加载中...', 'Loading...')}</div>}
          <div className="kgSectionTitle">{t('章节', 'Chapters')}</div>
          <div className="kgStack" style={{ gap: 4 }}>
            {chapters.map((c) => (
              <div
                key={c.chapter_id}
                className={`kgListItem${textbooks.selectedChapterId === c.chapter_id ? ' is-active' : ''}`}
                onClick={() => selectChapter(c.chapter_id)}
              >
                <div className="kgListItemTitle">{t(`第 ${c.chapter_num} 章：${c.title}`, `Chapter ${c.chapter_num}: ${c.title}`)}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {deleteConfirmId && createPortal(
        <div className="modalOverlay" onClick={() => !deleteBusy && setDeleteConfirmId('')}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div className="modalTitle">{t('删除教材', 'Delete Textbook')}</div>
              <button type="button" className="btn btnSmall" disabled={deleteBusy} onClick={() => setDeleteConfirmId('')}>
                {t('关闭', 'Close')}
              </button>
            </div>
            <div className="modalBody">
              <div className="hint" style={{ marginBottom: 10, fontSize: 11 }}>
                {selectedTextbook?.title || deleteConfirmId}
              </div>
              <div className="hint">
                {t(
                  '确认删除这本教材？这会移除 Neo4j 图数据、派生文件，并在删除后自动重建全局索引。',
                  'Delete this textbook? This removes Neo4j graph data, derived files, and automatically rebuilds global indexes afterward.',
                )}
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="btn btnDanger" disabled={deleteBusy} onClick={() => confirmDelete().catch(() => {})}>
                  {deleteBusy ? t('删除中...', 'Deleting...') : t('确定删除', 'Confirm Delete')}
                </button>
                <button type="button" className="btn" disabled={deleteBusy} onClick={() => setDeleteConfirmId('')}>
                  {t('取消', 'Cancel')}
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  )
}
