import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiPost } from '../api'
import { useI18n } from '../i18n'
import {
  invalidateOverviewStatsCache,
  invalidatePaperDataCache,
  loadOverviewStatsSnapshot,
  type DiscoveryCandidate,
} from '../loaders/panelData'
import { useGlobalState } from '../state/store'
import { invalidateOverviewGraphCache, loadOverviewGraph } from '../loaders/overview'

type Stats = { paperCount: number; ingestedCount: number }

function normalizeStatus(status: string | undefined) {
  const s = String(status ?? '').trim()
  return s || 'draft'
}

export default function OverviewPanel() {
  const nav = useNavigate()
  const { t } = useI18n()
  const { dispatch } = useGlobalState()
  const [stats, setStats] = useState<Stats>({ paperCount: 0, ingestedCount: 0 })
  const [discoveryItems, setDiscoveryItems] = useState<DiscoveryCandidate[]>([])
  const [ingestPath, setIngestPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [refreshingStats, setRefreshingStats] = useState(false)
  const refreshingGraphRef = useRef(false)

  useEffect(() => {
    let cancelled = false
    async function loadGraph() {
      dispatch({ type: 'SET_TRANSITIONING', value: true })
      try {
        const els = await loadOverviewGraph()
        if (!cancelled) dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      } catch {
        // no-op
      } finally {
        if (!cancelled) dispatch({ type: 'SET_TRANSITIONING', value: false })
      }
    }
    void loadGraph()
    return () => {
      cancelled = true
    }
  }, [dispatch])

  async function refreshStats(force = false) {
    setRefreshingStats(true)
    try {
      if (force) invalidateOverviewStatsCache()
      const snapshot = await loadOverviewStatsSnapshot()
      setStats({ paperCount: snapshot.paperCount, ingestedCount: snapshot.paperCount })
      setDiscoveryItems(snapshot.discoveryItems)
    } finally {
      setRefreshingStats(false)
    }
  }

  useEffect(() => {
    refreshStats().catch(() => {})
  }, [])

  async function submitIngest() {
    const path = ingestPath.trim()
    if (!path || busy) return
    setBusy(true)
    setMsg('')
    setError('')
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/ingest/path', { path })
      setMsg(t(`导入任务已提交：${res.task_id}`, `Ingest task submitted: ${res.task_id}`))
      invalidateOverviewGraphCache()
      invalidatePaperDataCache()
      void refreshStats(true).catch(() => {})
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusy(false)
    }
  }

  const discoverySummary = useMemo(() => {
    let accepted = 0
    let ranked = 0
    let needsMore = 0
    let totalScore = 0
    for (const item of discoveryItems) {
      const status = normalizeStatus(item.status)
      const score = Number(item.quality_score ?? 0)
      totalScore += Number.isFinite(score) ? score : 0
      if (status === 'accepted') accepted += 1
      else if (status === 'needs_more_evidence') needsMore += 1
      else ranked += 1
    }
    const avgScore = discoveryItems.length ? totalScore / discoveryItems.length : 0
    return {
      count: discoveryItems.length,
      accepted,
      ranked,
      needsMore,
      avgScore,
    }
  }, [discoveryItems])

  return (
    <div className="kgPanelBody kgStack">
      <div className="kgStatGrid">
        <div className="kgStatCard">
          <div className="kgStatLabel">{t('论文', 'Papers')}</div>
          <div className="kgStatValue">{stats.paperCount}</div>
        </div>
        <div className="kgStatCard">
          <div className="kgStatLabel">{t('发现', 'Discovery')}</div>
          <div className="kgStatValue is-muted">{discoverySummary.count}</div>
        </div>
      </div>

      <div className="kgCard">
        <div className="kgCardTitle">{t('导入中心', 'Import Center')}</div>
        <div className="kgStack" style={{ marginTop: 8 }}>
          <label className="sr-only" htmlFor="overview-ingest-path">
            {t('论文目录路径', 'Paper folder path')}
          </label>
          <input
            id="overview-ingest-path"
            name="overview_ingest_path"
            className="kgInput"
            aria-label={t('论文目录路径', 'Paper folder path')}
            placeholder={t('输入论文目录路径...', 'Enter the paper folder path...')}
            value={ingestPath}
            onChange={(e) => setIngestPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submitIngest()
            }}
          />
          <button className="kgBtn kgBtn--primary kgBtn--sm" disabled={busy || !ingestPath.trim()} onClick={() => void submitIngest()}>
            {busy ? t('提交中...', 'Submitting...') : t('快速导入', 'Quick Ingest')}
          </button>
          <button className="kgBtn kgBtn--sm" onClick={() => nav('/ingest')}>
            {t('打开完整导入工作台', 'Open Full Ingest Workbench')}
          </button>
          {msg && <div style={{ fontSize: 10.5, color: 'var(--success)' }}>{msg}</div>}
          {error && <div style={{ fontSize: 10.5, color: 'var(--danger)' }}>{error}</div>}
        </div>
      </div>

      <div className="kgCard">
        <div className="kgCardTitle">{t('科学问题发现', 'Scientific Discovery')}</div>
        <div className="kgStack" style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 }}>
            {t(
              `已发现 ${discoverySummary.count} 条候选，已采纳 ${discoverySummary.accepted} 条，待补证据 ${discoverySummary.needsMore} 条。`,
              `${discoverySummary.count} candidates found, ${discoverySummary.accepted} accepted, ${discoverySummary.needsMore} need more evidence.`,
            )}
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--faint)' }}>
            {t('平均质量分', 'Average Quality Score')}: {discoverySummary.avgScore.toFixed(2)}
          </div>
          <button className="kgBtn kgBtn--primary kgBtn--sm" onClick={() => nav('/discovery')}>
            {t('打开发现工作台', 'Open Discovery Workbench')}
          </button>
        </div>
      </div>

      <div className="kgRow" style={{ flexWrap: 'wrap' }}>
        <button
          className="kgBtn kgBtn--sm"
          onClick={() => {
            if (refreshingGraphRef.current) return
            refreshingGraphRef.current = true
            invalidateOverviewGraphCache()
            void loadOverviewGraph(200, 600, { force: true })
              .then((els) => dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' }))
              .catch(() => {})
              .finally(() => {
                refreshingGraphRef.current = false
              })
          }}
        >
          {t('刷新图谱', 'Refresh Graph')}
        </button>
        <button className="kgBtn kgBtn--sm" disabled={refreshingStats} onClick={() => void refreshStats(true).catch(() => {})}>
          {refreshingStats ? t('更新中...', 'Refreshing...') : t('刷新统计', 'Refresh Stats')}
        </button>
      </div>
    </div>
  )
}
