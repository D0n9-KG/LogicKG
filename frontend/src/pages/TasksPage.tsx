import { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost } from '../api'
import { useI18n, type UILocale } from '../i18n'

type TaskRow = {
  task_id: string
  type: string
  status: string
  stage?: string
  progress?: number
  message?: string | null
  error?: string | null
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
}

function badgeClass(status: string) {
  if (status === 'succeeded') return 'badge badgeOk'
  if (status === 'failed') return 'badge badgeDanger'
  if (status === 'running') return 'badge badgeWarn'
  if (status === 'queued') return 'badge badgeWarn'
  return 'badge'
}

function statusLabel(status: string, locale: UILocale) {
  if (status === 'queued') return locale === 'zh-CN' ? '排队中' : 'Queued'
  if (status === 'running') return locale === 'zh-CN' ? '进行中' : 'Running'
  if (status === 'succeeded') return locale === 'zh-CN' ? '成功' : 'Succeeded'
  if (status === 'failed') return locale === 'zh-CN' ? '失败' : 'Failed'
  if (status === 'canceled') return locale === 'zh-CN' ? '已取消' : 'Canceled'
  return status
}

function typeLabel(type: string, locale: UILocale) {
  if (type === 'ingest_path') return locale === 'zh-CN' ? '导入（旧：本地路径）' : 'Ingest (Legacy Path)'
  if (type === 'ingest_upload_ready') return locale === 'zh-CN' ? '导入（上传可导入项）' : 'Ingest (Uploaded Item)'
  if (type === 'upload_replace') return locale === 'zh-CN' ? '替换论文（按 DOI）' : 'Replace Paper (by DOI)'
  if (type === 'rebuild_paper') return locale === 'zh-CN' ? '重建论文' : 'Rebuild Paper'
  if (type === 'rebuild_faiss') return locale === 'zh-CN' ? '重建全局 FAISS' : 'Rebuild Global FAISS'
  if (type === 'rebuild_all') return locale === 'zh-CN' ? '全链路重建（所有论文）' : 'Full Pipeline Rebuild'
  if (type === 'rebuild_similarity') return locale === 'zh-CN' ? '重建相似度关系' : 'Rebuild Similarity Links'
  if (type === 'update_similarity_paper') return locale === 'zh-CN' ? '更新单论文相似度' : 'Update Paper Similarity'
  return type
}

function stageLabel(stage: string | null | undefined, locale: UILocale) {
  const s = String(stage ?? '')
  if (!s) return ''
  if (s.includes('crossref')) return locale === 'zh-CN' ? '文献元数据解析' : 'Crossref Resolve'
  if (s.includes('neo4j_clear')) return locale === 'zh-CN' ? '清理 Neo4j' : 'Clear Neo4j'
  if (s.includes('neo4j_write')) return locale === 'zh-CN' ? '写入 Neo4j' : 'Write Neo4j'
  if (s.includes('llm')) return locale === 'zh-CN' ? '大模型抽取' : 'LLM Extraction'
  if (s.includes('faiss')) return locale === 'zh-CN' ? '向量索引重建' : 'FAISS Rebuild'
  if (s === 'done') return locale === 'zh-CN' ? '完成' : 'Done'
  if (s === 'canceled') return locale === 'zh-CN' ? '已取消' : 'Canceled'
  if (s === 'failed') return locale === 'zh-CN' ? '失败' : 'Failed'
  return s
}

export default function TasksPage() {
  const { locale, t } = useI18n()
  const [tasks, setTasks] = useState<TaskRow[]>([])
  const [error, setError] = useState<string>('')
  const [info, setInfo] = useState<string>('')
  const [busy, setBusy] = useState<string>('')
  const [actionBusy, setActionBusy] = useState<string>('')
  const [query, setQuery] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  async function refresh() {
    const r = await apiGet<{ tasks: TaskRow[] }>('/tasks?limit=120&keep_finished=10&prune_finished=true')
    setTasks(r.tasks ?? [])
  }

  useEffect(() => {
    refresh().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
  }, [])

  const hasActive = useMemo(() => tasks.some((t) => ['queued', 'running'].includes(String(t.status))), [tasks])

  useEffect(() => {
    let canceled = false
    let inFlight = false

    async function tick() {
      if (canceled || inFlight) return
      inFlight = true
      try {
        const r = await apiGet<{ tasks: TaskRow[] }>('/tasks?limit=120&keep_finished=10&prune_finished=true')
        if (!canceled) setTasks(r.tasks ?? [])
      } catch {
        // keep polling silent
      } finally {
        inFlight = false
      }
    }

    const iv = setInterval(() => tick().catch(() => {}), hasActive ? 1200 : 5000)
    return () => {
      canceled = true
      clearInterval(iv)
    }
  }, [hasActive])

  async function cancel(taskId: string) {
    setBusy(taskId)
    setError('')
    try {
      await apiPost<Record<string, unknown>>(`/tasks/${encodeURIComponent(taskId)}/cancel`, {})
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy('')
    }
  }

  async function submitRebuildFaiss() {
    setActionBusy('rebuild_faiss')
    setError('')
    setInfo('')
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/rebuild/faiss', {})
      setInfo(
        locale === 'zh-CN'
          ? `已提交任务：重建全局 FAISS（${res.task_id ?? ''}）`
          : `Task submitted: Rebuild global FAISS (${res.task_id ?? ''})`,
      )
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setActionBusy('')
    }
  }

  async function submitRebuildAll() {
    if (
      !window.confirm(
        locale === 'zh-CN'
          ? '确定要“全链路重建（所有论文）”吗？\n这会重新解析/抽取并写图谱，可能耗时较长。'
          : 'Run full pipeline rebuild for all papers?\nThis may take a long time.',
      )
    ) {
      return
    }
    setActionBusy('rebuild_all')
    setError('')
    setInfo('')
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/rebuild/all', {})
      setInfo(
        locale === 'zh-CN'
          ? `已提交任务：全链路重建（${res.task_id ?? ''}）`
          : `Task submitted: Full pipeline rebuild (${res.task_id ?? ''})`,
      )
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setActionBusy('')
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return tasks.filter((t) => {
      if (statusFilter !== 'all' && t.status !== statusFilter) return false
      if (!q) return true
      const hay = `${t.task_id} ${t.type} ${t.status} ${t.stage ?? ''} ${t.message ?? ''} ${t.error ?? ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [query, statusFilter, tasks])

  const runningCount = useMemo(() => tasks.filter((t) => ['queued', 'running'].includes(t.status)).length, [tasks])

  return (
    <div className="page">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">{t('任务', 'Tasks')}</h2>
          <div className="pageSubtitle">{t('后台队列任务（导入 / 替换 / 重建）', 'Backend queue tasks (ingest / replace / rebuild)')}</div>
        </div>
        <div className="pageActions">
          <span className="pill">
            <span className="kicker">{t('进行中', 'Active')}</span> {runningCount}
          </span>
          <button className="btn" disabled={!!actionBusy} onClick={submitRebuildFaiss}>
            {actionBusy === 'rebuild_faiss' ? t('提交中…', 'Submitting...') : t('重建全局 FAISS', 'Rebuild Global FAISS')}
          </button>
          <button className="btn btnDanger" disabled={!!actionBusy} onClick={submitRebuildAll}>
            {actionBusy === 'rebuild_all' ? t('提交中…', 'Submitting...') : t('全链路重建', 'Full Rebuild')}
          </button>
          <button className="btn" onClick={() => refresh().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))}>
            {t('刷新', 'Refresh')}
          </button>
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}
      {info && (
        <div className="infoBox" style={{ marginTop: 12 }}>
          <div className="split">
            <div style={{ whiteSpace: 'pre-wrap' }}>{info}</div>
            <button className="btn btnSmall" onClick={() => setInfo('')}>
              {t('清除', 'Clear')}
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panelHeader">
          <div className="split">
            <div className="panelTitle">{t('队列', 'Queue')}</div>
            <div className="row">
              <select className="select" style={{ width: 160 }} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="all">{t('全部', 'All')}</option>
                <option value="queued">{t('排队中', 'Queued')}</option>
                <option value="running">{t('进行中', 'Running')}</option>
                <option value="succeeded">{t('成功', 'Succeeded')}</option>
                <option value="failed">{t('失败', 'Failed')}</option>
                <option value="canceled">{t('已取消', 'Canceled')}</option>
              </select>
              <input className="input" style={{ width: 260, maxWidth: '70vw' }} value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('搜索任务…', 'Search tasks...')} />
            </div>
          </div>
        </div>
        <div className="panelBody">
          <div className="list">
            {filtered.map((row) => {
              const pct = Math.round(Math.max(0, Math.min(1, Number(row.progress ?? 0))) * 100)
              const cancelable = ['queued', 'running'].includes(row.status)
              return (
                <div key={row.task_id} className="itemCard">
                  <div className="split">
                    <div className="itemTitle" style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                      <code>{row.task_id}</code>
                      <span className={badgeClass(row.status)} title={row.status}>
                        {statusLabel(row.status, locale)}
                      </span>
                      <span className="badge" title={row.type}>
                        {typeLabel(row.type, locale)}
                      </span>
                    </div>
                    <button className="btn btnSmall btnDanger" disabled={!cancelable || busy === row.task_id} onClick={() => cancel(row.task_id)}>
                      {t('取消', 'Cancel')}
                    </button>
                  </div>

                  <div className="itemMeta">
                    {t('阶段', 'Stage')}: <code title={row.stage ?? ''}>{stageLabel(row.stage, locale)}</code> · {t('进度', 'Progress')}: {pct}%
                  </div>

                  <div className="progress" style={{ marginTop: 10 }}>
                    <div className="progressBar" style={{ width: `${pct}%` }} />
                  </div>

                  {(row.message || row.error) && <div className="itemBody">{row.error ? `ERROR: ${row.error}` : row.message}</div>}
                </div>
              )
            })}
          </div>
          {filtered.length === 0 && <div className="metaLine">{t('暂无任务。', 'No tasks yet.')}</div>}
        </div>
      </div>
    </div>
  )
}
