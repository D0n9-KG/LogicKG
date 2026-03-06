// frontend/src/panels/TextbooksPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../api'
import { useI18n } from '../i18n'
import { useGlobalState } from '../state/store'
import { loadTextbookEntityGraph } from '../loaders/textbooks'

type Textbook = { textbook_id: string; title: string; chapter_count: number; entity_count: number }
type Chapter = { chapter_id: string; chapter_num: number; title: string }

export default function TextbooksPanel() {
  const { state, dispatch } = useGlobalState()
  const { t } = useI18n()
  const { textbooks } = state
  const [allTextbooks, setAllTextbooks] = useState<Textbook[]>([])
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [loading, setLoading] = useState(false)
  const selectReqRef = useRef<string | null>(null)

  useEffect(() => {
    // Clear transitioning set by switchModule (textbooks has no immediate graph load)
    dispatch({ type: 'SET_TRANSITIONING', value: false })
    let cancelled = false
    apiGet<{ textbooks: Textbook[] }>('/textbooks?limit=100')
      .then((r) => { if (!cancelled) setAllTextbooks(r.textbooks ?? []) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [dispatch])

  function selectTextbook(textbookId: string) {
    dispatch({ type: 'TEXTBOOKS_SELECT', textbookId, chapterId: null })
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    setLoading(true)
    selectReqRef.current = textbookId
    Promise.all([
      apiGet<{ chapters: Chapter[] }>(`/textbooks/${encodeURIComponent(textbookId)}`),
      loadTextbookEntityGraph(textbookId),
    ])
      .then(([res, els]) => {
        if (selectReqRef.current !== textbookId) return
        setChapters(res.chapters ?? [])
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'breadthfirst' })
      })
      .catch(() => {})
      .finally(() => {
        if (selectReqRef.current === textbookId) {
          setLoading(false)
          dispatch({ type: 'SET_TRANSITIONING', value: false })
        }
      })
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
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'breadthfirst' })
      })
      .catch(() => {})
      .finally(() => {
        if (selectReqRef.current === reqKey) dispatch({ type: 'SET_TRANSITIONING', value: false })
      })
  }

  return (
    <div className="kgPanelBody kgStack">
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
          <button className="kgBtn kgBtn--sm" onClick={() => dispatch({ type: 'TEXTBOOKS_SELECT', textbookId: null, chapterId: null })}>
            {t('← 返回教材列表', '← Back to Textbook List')}
          </button>
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
    </div>
  )
}
