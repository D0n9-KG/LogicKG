// frontend/src/panels/OpsPanel.tsx
import { useEffect, useState } from 'react'
import { apiGet, apiPost } from '../api'
import { useI18n } from '../i18n'
import { loadOverviewGraph } from '../loaders/overview'
import { useGlobalState } from '../state/store'

type Task = { task_id: string; type: string; status: string; submitted_at?: string }

export default function OpsPanel() {
  const { dispatch } = useGlobalState()
  const { t } = useI18n()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    let cancelled = false
    // Show overview graph in background; clears transitioning set by switchModule
    loadOverviewGraph()
      .then((els) => {
        if (!cancelled) {
          dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
          dispatch({ type: 'SET_TRANSITIONING', value: false })
        }
      })
      .catch(() => { if (!cancelled) dispatch({ type: 'SET_TRANSITIONING', value: false }) })

    // Load tasks
    setLoading(true)
    apiGet<{ tasks: Task[] }>('/tasks?limit=30')
      .then((r) => { if (!cancelled) setTasks(r.tasks ?? []) })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [dispatch])

  function refresh() {
    setLoading(true)
    apiGet<{ tasks: Task[] }>('/tasks?limit=30')
      .then((r) => setTasks(r.tasks ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  async function rebuildAll() {
    setBusy('rebuild_all'); setSuccessMsg(''); setErrorMsg('')
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/rebuild/all', {})
      setSuccessMsg(t(`重建任务：${res.task_id}`, `Rebuild task: ${res.task_id}`))
      refresh()
    } catch (e: unknown) {
      setErrorMsg(String((e as { message?: unknown })?.message ?? e))
    } finally {
      setBusy(null)
    }
  }

  const STATUS_COLOR: Record<string, string> = {
    succeeded: 'var(--success)',
    failed: 'var(--danger)',
    running: 'var(--accent)',
    submitted: 'var(--warning)',
    cancelled: 'var(--faint)',
  }

  return (
    <div className="kgPanelBody kgStack">
      <div className="kgRow" style={{ flexWrap: 'wrap' }}>
        <button className="kgBtn kgBtn--sm" onClick={refresh} disabled={loading}>{t('刷新任务', 'Refresh Tasks')}</button>
        <button className="kgBtn kgBtn--sm" disabled={!!busy} onClick={() => void rebuildAll()}>
          {busy === 'rebuild_all' ? t('提交中...', 'Submitting...') : t('重建全部', 'Rebuild All')}
        </button>
      </div>
      {successMsg && <div style={{ fontSize: 10.5, color: 'var(--success)' }}>{successMsg}</div>}
      {errorMsg && <div style={{ fontSize: 10.5, color: 'var(--danger)' }}>{errorMsg}</div>}
      {loading && <div className="text-faint" style={{ fontSize: 11 }}>{t('加载中...', 'Loading...')}</div>}
      <div className="kgSectionTitle">{t('任务队列', 'Task Queue')}</div>
      <div className="kgStack" style={{ gap: 4 }}>
        {tasks.map((t) => (
          <div key={t.task_id} className="kgListItem">
            <div className="kgListItemTitle" style={{ color: STATUS_COLOR[t.status] ?? 'var(--text)' }}>
              {t.type} · {t.status}
            </div>
            <div className="kgListItemMeta truncate">{t.task_id}</div>
          </div>
        ))}
        {tasks.length === 0 && !loading && <div className="text-faint" style={{ fontSize: 11 }}>{t('暂无任务', 'No tasks')}</div>}
      </div>
    </div>
  )
}
