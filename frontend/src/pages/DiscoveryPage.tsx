import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { apiGet, apiPost } from '../api'
import { useI18n, type UILocale } from '../i18n'
import './discovery.css'

type DiscoveryTask = {
  task_id: string
  status?: string
  progress?: number
  stage?: string
  message?: string | null
  error?: string | null
  log?: string[]
}

type DiscoveryCandidate = {
  candidate_id: string
  question: string
  gap_id?: string
  rank?: number
  status?: string
  quality_score?: number
  support_evidence_ids?: string[]
  challenge_evidence_ids?: string[]
  missing_evidence_statement?: string | null
}

type BatchSubmitResponse = {
  task_id: string
}

type CandidateListResponse = {
  candidates: DiscoveryCandidate[]
  source_task_id?: string | null
}

type FeedbackResponse = {
  candidate_id: string
  label: 'accepted' | 'rejected' | 'needs_revision'
  updated_score: number
}

type FeedbackLabel = 'accepted' | 'rejected' | 'needs_revision'
type PipelineState = 'pending' | 'active' | 'completed' | 'error'

type DiscoveryConfigPayload = {
  domain?: string
  dry_run?: boolean
  max_gaps?: number
  candidates_per_gap?: number
  use_llm?: boolean
  hop_order?: number
  adjacent_samples?: number
  random_samples?: number
  rag_top_k?: number
  prompt_optimize?: boolean
  community_method?: 'author_hop' | 'louvain' | 'hybrid'
  community_samples?: number
  prompt_optimization_method?: 'rl_bandit' | 'heuristic'
}

type DiscoveryConfigResponse = {
  discovery?: DiscoveryConfigPayload
}

const PIPELINE_STEPS: Array<{ id: string; title: string; description: string }> = [
  {
    id: 'start',
    title: 'Start Batch',
    description: 'Initialize domain and runtime controls, then enqueue the task.',
  },
  {
    id: 'gap',
    title: 'Detect Gaps',
    description: 'Locate candidate knowledge gaps from current graph evidence.',
  },
  {
    id: 'question',
    title: 'Generate Questions',
    description: 'Transform each gap into auditable scientific questions.',
  },
  {
    id: 'audit',
    title: 'Audit Evidence',
    description: 'Check support/challenge evidence and missing statements.',
  },
  { id: 'rank', title: 'Score & Rank', description: 'Compute quality score and rank final candidates.' },
  { id: 'done', title: 'Feedback Loop', description: 'Collect human feedback for iterative improvement.' },
]

const STAGE_THRESHOLDS = [0.05, 0.2, 0.4, 0.65, 0.85, 1]

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  if (value <= 0) return 0
  if (value >= 1) return 1
  return value
}

function taskStatusLabel(status: string | null | undefined, locale: UILocale) {
  const s = String(status ?? '').trim()
  if (s === 'queued') return locale === 'zh-CN' ? '排队中' : 'Queued'
  if (s === 'running') return locale === 'zh-CN' ? '进行中' : 'Running'
  if (s === 'succeeded') return locale === 'zh-CN' ? '成功' : 'Succeeded'
  if (s === 'failed') return locale === 'zh-CN' ? '失败' : 'Failed'
  if (s === 'canceled') return locale === 'zh-CN' ? '已取消' : 'Canceled'
  return s || (locale === 'zh-CN' ? '空闲' : 'Idle')
}

function taskBadgeClass(status: string | null | undefined) {
  const s = String(status ?? '').trim()
  if (s === 'succeeded') return 'badge badgeOk'
  if (s === 'failed' || s === 'canceled') return 'badge badgeDanger'
  if (s === 'running' || s === 'queued') return 'badge badgeWarn'
  return 'badge'
}

function candidateBadgeClass(status: string | null | undefined) {
  const s = String(status ?? '').trim()
  if (s === 'accepted') return 'badge badgeOk'
  if (s === 'rejected') return 'badge badgeDanger'
  if (s === 'needs_more_evidence') return 'badge badgeWarn'
  return 'badge'
}

function candidateStatusLabel(status: string | null | undefined, locale: UILocale) {
  const s = String(status ?? '').trim()
  if (s === 'accepted') return locale === 'zh-CN' ? '已采纳' : 'Accepted'
  if (s === 'rejected') return locale === 'zh-CN' ? '已拒绝' : 'Rejected'
  if (s === 'needs_more_evidence') return locale === 'zh-CN' ? '待补证据' : 'Needs More Evidence'
  if (s === 'ranked') return locale === 'zh-CN' ? '已排序' : 'Ranked'
  return s || (locale === 'zh-CN' ? '草稿' : 'Draft')
}

function qualityPercent(rawScore: number | undefined): number {
  const score = Number(rawScore ?? 0)
  const normalized = (score + 0.5) / 1.5
  return Math.round(clamp01(normalized) * 100)
}

function buildPipelineState(task: DiscoveryTask | null): PipelineState[] {
  if (!task) return PIPELINE_STEPS.map(() => 'pending')

  const status = String(task.status ?? '')
  const progress = clamp01(Number(task.progress ?? 0))
  const completedByProgress = STAGE_THRESHOLDS.filter((value) => progress >= value).length

  if (status === 'succeeded') return PIPELINE_STEPS.map(() => 'completed')
  if (status === 'failed' || status === 'canceled') {
    return PIPELINE_STEPS.map((_, idx) => {
      if (idx < completedByProgress) return 'completed'
      if (idx === completedByProgress) return 'error'
      return 'pending'
    })
  }

  if (status === 'queued') return PIPELINE_STEPS.map((_, idx) => (idx === 0 ? 'active' : 'pending'))

  if (status === 'running') {
    return PIPELINE_STEPS.map((_, idx) => {
      if (idx < completedByProgress) return 'completed'
      if (idx === completedByProgress) return 'active'
      return 'pending'
    })
  }

  return PIPELINE_STEPS.map(() => 'pending')
}

export default function DiscoveryPage() {
  const nav = useNavigate()
  const { locale, t } = useI18n()

  const [domain, setDomain] = useState('granular_flow')
  const [dryRun, setDryRun] = useState(true)
  const [maxGaps, setMaxGaps] = useState(8)
  const [candidatesPerGap, setCandidatesPerGap] = useState(2)
  const [useLlm, setUseLlm] = useState(true)
  const [hopOrder, setHopOrder] = useState(2)
  const [adjacentSamples, setAdjacentSamples] = useState(6)
  const [randomSamples, setRandomSamples] = useState(2)
  const [ragTopK, setRagTopK] = useState(4)
  const [promptOptimize, setPromptOptimize] = useState(true)
  const [communityMethod, setCommunityMethod] = useState<'author_hop' | 'louvain' | 'hybrid'>('hybrid')
  const [communitySamples, setCommunitySamples] = useState(4)
  const [promptOptimizationMethod, setPromptOptimizationMethod] = useState<'rl_bandit' | 'heuristic'>('rl_bandit')

  const [taskId, setTaskId] = useState('')
  const [task, setTask] = useState<DiscoveryTask | null>(null)
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([])
  const [selectedCandidateId, setSelectedCandidateId] = useState('')
  const [feedbackNote, setFeedbackNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [feedbackBusy, setFeedbackBusy] = useState<FeedbackLabel | ''>('')
  const [refreshingCandidates, setRefreshingCandidates] = useState(false)
  const [refreshingConfig, setRefreshingConfig] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  async function refreshConfig() {
    setRefreshingConfig(true)
    try {
      const res = await apiGet<DiscoveryConfigResponse>('/config-center/effective/discovery')
      const cfg = (res?.discovery ?? {}) as DiscoveryConfigPayload
      setDomain(String(cfg.domain ?? 'granular_flow'))
      setDryRun(Boolean(cfg.dry_run ?? true))
      setMaxGaps(Number(cfg.max_gaps ?? 8))
      setCandidatesPerGap(Number(cfg.candidates_per_gap ?? 2))
      setUseLlm(Boolean(cfg.use_llm ?? true))
      setHopOrder(Number(cfg.hop_order ?? 2))
      setAdjacentSamples(Number(cfg.adjacent_samples ?? 6))
      setRandomSamples(Number(cfg.random_samples ?? 2))
      setRagTopK(Number(cfg.rag_top_k ?? 4))
      setPromptOptimize(Boolean(cfg.prompt_optimize ?? true))
      setCommunityMethod((cfg.community_method ?? 'hybrid') as 'author_hop' | 'louvain' | 'hybrid')
      setCommunitySamples(Number(cfg.community_samples ?? 4))
      setPromptOptimizationMethod((cfg.prompt_optimization_method ?? 'rl_bandit') as 'rl_bandit' | 'heuristic')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setRefreshingConfig(false)
    }
  }

  async function refreshCandidates(syncTask = false) {
    setRefreshingCandidates(true)
    try {
      const data = await apiGet<CandidateListResponse>('/discovery/candidates')
      const next = Array.isArray(data.candidates) ? data.candidates : []
      setCandidates(next)
      if (syncTask && data.source_task_id) setTaskId(String(data.source_task_id))
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setRefreshingCandidates(false)
    }
  }

  useEffect(() => {
    void refreshCandidates(true)
    void refreshConfig()
  }, [])

  useEffect(() => {
    setSelectedCandidateId((prev) => {
      if (prev && candidates.some((item) => item.candidate_id === prev)) return prev
      return candidates[0]?.candidate_id ?? ''
    })
  }, [candidates])

  useEffect(() => {
    if (!taskId) return

    let cancelled = false
    let timer: number | null = null

    async function tick() {
      try {
        const taskRes = await apiGet<DiscoveryTask>(`/tasks/${encodeURIComponent(taskId)}`)
        if (cancelled) return
        setTask(taskRes)
        const status = String(taskRes.status ?? '')
        const isFinal = status === 'succeeded' || status === 'failed' || status === 'canceled'
        if (isFinal) {
          if (status === 'succeeded') {
            setInfo(t(`发现批处理已完成：${taskId}`, `Discovery batch completed: ${taskId}`))
            void refreshCandidates(false)
          }
          if (status === 'failed') {
            setError(String(taskRes.error ?? taskRes.message ?? t(`任务失败：${taskId}`, `Task failed: ${taskId}`)))
          }
          return
        }
      } catch (e: unknown) {
        if (cancelled) return
        setError(String((e as { message?: unknown } | null)?.message ?? e))
      }
      timer = window.setTimeout(() => void tick(), 1200)
    }

    void tick()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [taskId, t])

  async function runDiscoveryBatch() {
    setSubmitting(true)
    setError('')
    setInfo('')
    setTask(null)
    try {
      const res = await apiPost<BatchSubmitResponse>('/discovery/batch', {
        domain: domain.trim() || 'granular_flow',
        dry_run: dryRun,
        max_gaps: Math.max(1, Math.min(64, Number(maxGaps) || 8)),
        candidates_per_gap: Math.max(1, Math.min(3, Number(candidatesPerGap) || 2)),
        use_llm: useLlm,
        hop_order: Math.max(1, Math.min(3, Number(hopOrder) || 2)),
        adjacent_samples: Math.max(0, Math.min(30, Number(adjacentSamples) || 6)),
        random_samples: Math.max(0, Math.min(30, Number(randomSamples) || 2)),
        rag_top_k: Math.max(1, Math.min(8, Number(ragTopK) || 4)),
        prompt_optimize: promptOptimize,
        community_method: communityMethod,
        community_samples: Math.max(0, Math.min(30, Number(communitySamples) || 4)),
        prompt_optimization_method: promptOptimizationMethod,
      })
      setTaskId(res.task_id)
      setInfo(t(`发现批处理已入队：${res.task_id}`, `Discovery batch queued: ${res.task_id}`))
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setSubmitting(false)
    }
  }

  const selectedCandidate = useMemo(
    () => candidates.find((item) => item.candidate_id === selectedCandidateId) ?? null,
    [candidates, selectedCandidateId],
  )

  async function submitFeedback(label: FeedbackLabel) {
    if (!selectedCandidate) return
    setFeedbackBusy(label)
    setError('')
    setInfo('')
    try {
      const res = await apiPost<FeedbackResponse>('/discovery/feedback', {
        candidate_id: selectedCandidate.candidate_id,
        label,
        note: feedbackNote.trim() || undefined,
      })
      const nextStatus = label === 'needs_revision' ? 'ranked' : label
      setCandidates((prev) =>
        prev.map((item) =>
          item.candidate_id === selectedCandidate.candidate_id
            ? { ...item, quality_score: res.updated_score, status: nextStatus }
            : item,
        ),
      )
      setInfo(t(`反馈已提交：${res.candidate_id} -> ${res.label}`, `Feedback submitted: ${res.candidate_id} -> ${res.label}`))
      setFeedbackNote('')
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setFeedbackBusy('')
    }
  }

  const progress = Math.round(clamp01(Number(task?.progress ?? 0)) * 100)
  const pipelineStates = useMemo(() => buildPipelineState(task), [task])
  const taskLogs = useMemo(() => (Array.isArray(task?.log) ? [...task.log].reverse().slice(0, 8) : []), [task?.log])

  const qualitySummary = useMemo(() => {
    const total = candidates.length
    let accepted = 0
    let rejected = 0
    let needsMore = 0
    let withSupport = 0
    let totalScore = 0
    for (const item of candidates) {
      const status = String(item.status ?? '')
      if (status === 'accepted') accepted += 1
      if (status === 'rejected') rejected += 1
      if (status === 'needs_more_evidence') needsMore += 1
      if ((item.support_evidence_ids ?? []).length > 0) withSupport += 1
      totalScore += Number(item.quality_score ?? 0)
    }
    return {
      total,
      accepted,
      rejected,
      needsMore,
      supportCoverage: total ? Math.round((withSupport / total) * 100) : 0,
      avgScore: total ? totalScore / total : 0,
    }
  }, [candidates])

  const gapCount = useMemo(
    () => new Set(candidates.map((item) => String(item.gap_id ?? '').trim()).filter(Boolean)).size,
    [candidates],
  )

  return (
    <div className="page discoveryPage">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">{t('科学问题发现', 'Scientific Question Discovery')}</h2>
          <div className="pageSubtitle">
            {t(
              '挖掘尚未解决的知识缺口，生成候选问题，审计证据，完成质量排序，并支持人工反馈闭环。',
              'Discover unresolved knowledge gaps, generate candidate questions, audit evidence, rank quality, and collect feedback.',
            )}
          </div>
        </div>
        <div className="pageActions discoveryActionWrap">
          <div className="discoveryConfigPanel">
            <div className="discoveryConfigHint">
              {t(
                '参数由运维配置中心统一维护；此页面用于批量执行与结果复核。',
                'Parameters are centrally maintained in Ops Config Center. Use this page for batch execution and review.',
              )}
            </div>

            <div className="discoverySummaryRow">
              <span className="pill"><span className="kicker">{t('领域', 'domain')}</span>{domain}</span>
              <span className="pill"><span className="kicker">{t('缺口上限', 'max_gaps')}</span>{maxGaps}</span>
              <span className="pill"><span className="kicker">{t('每缺口候选', 'per_gap')}</span>{candidatesPerGap}</span>
              <span className="pill"><span className="kicker">{t('跳数', 'hop')}</span>{hopOrder}</span>
              <span className="pill"><span className="kicker">{t('邻域/随机', 'adj/random')}</span>{adjacentSamples}/{randomSamples}</span>
              <span className="pill"><span className="kicker">{t('RAG TopK', 'rag_top_k')}</span>{ragTopK}</span>
              <span className="pill"><span className="kicker">{t('社区策略', 'community')}</span>{communityMethod}/{communitySamples}</span>
              <span className="pill"><span className="kicker">{t('提示策略', 'prompt_policy')}</span>{promptOptimizationMethod}</span>
            </div>

            <div className="discoveryToggleBar">
              <label className="pill discoveryDryRun">
                <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
                <span>{t('演练模式', 'dry-run')}</span>
              </label>
              <label className="pill discoveryDryRun">
                <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
                <span>{t('启用大模型', 'use-llm')}</span>
              </label>
              <label className="pill discoveryDryRun">
                <input type="checkbox" checked={promptOptimize} onChange={(e) => setPromptOptimize(e.target.checked)} />
                <span>{t('提示优化', 'prompt-opt')}</span>
              </label>
            </div>

            <div className="discoveryButtonBar">
              <button className="btn btnPrimary" disabled={submitting} onClick={() => void runDiscoveryBatch()}>
                {submitting ? t('提交中...', 'Submitting...') : t('运行发现批处理', 'Run Discovery Batch')}
              </button>
              <button className="btn" disabled={refreshingCandidates} onClick={() => void refreshCandidates(true)}>
                {refreshingCandidates ? t('刷新中...', 'Refreshing...') : t('刷新候选', 'Refresh Candidates')}
              </button>
              <button className="btn" disabled={refreshingConfig} onClick={() => void refreshConfig()}>
                {refreshingConfig ? t('同步中...', 'Syncing...') : t('同步配置', 'Sync Config')}
              </button>
              <button className="btn" onClick={() => nav('/ops')}>
                {t('打开配置中心', 'Open Config Center')}
              </button>
            </div>
          </div>
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}
      {info && (
        <div className="infoBox" style={{ marginTop: 12 }}>
          {info}
        </div>
      )}

      <div className="discoveryGrid">
        <div className="stack">
          <section className="panel">
            <div className="panelHeader">
              <div className="split">
                <h3 className="panelTitle">{t('发现流程', 'Discovery Process')}</h3>
                <span className={taskBadgeClass(task?.status)}>{taskStatusLabel(task?.status, locale)}</span>
              </div>
            </div>
            <div className="panelBody">
              <div className="pipelineList">
                {PIPELINE_STEPS.map((step, idx) => (
                  <article
                    key={step.id}
                    className={[
                      'pipelineItem',
                      pipelineStates[idx] === 'completed' ? 'is-completed' : '',
                      pipelineStates[idx] === 'active' ? 'is-active' : '',
                      pipelineStates[idx] === 'error' ? 'is-error' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    <div className="pipelineMeta">
                      <span className="pipelineIndex">{t('步骤', 'STEP')} {idx + 1}</span>
                      <span className="pipelineState">
                        {pipelineStates[idx] === 'pending'
                          ? t('待处理', 'PENDING')
                          : pipelineStates[idx] === 'active'
                            ? t('进行中', 'ACTIVE')
                            : pipelineStates[idx] === 'completed'
                              ? t('已完成', 'COMPLETED')
                              : t('异常', 'ERROR')}
                      </span>
                    </div>
                    <div className="pipelineTitle">
                      {step.id === 'start'
                        ? t('启动批处理', 'Start Batch')
                        : step.id === 'gap'
                          ? t('识别缺口', 'Detect Gaps')
                          : step.id === 'question'
                            ? t('生成问题', 'Generate Questions')
                            : step.id === 'audit'
                              ? t('证据审计', 'Audit Evidence')
                              : step.id === 'rank'
                                ? t('评分排序', 'Score & Rank')
                                : t('反馈闭环', 'Feedback Loop')}
                    </div>
                    <div className="pipelineDesc">
                      {step.id === 'start'
                        ? t('初始化领域与运行参数，并入队任务。', 'Initialize domain and runtime controls, then enqueue the task.')
                        : step.id === 'gap'
                          ? t('从当前图谱证据中识别候选知识缺口。', 'Locate candidate knowledge gaps from current graph evidence.')
                          : step.id === 'question'
                            ? t('将每个缺口转化为可审计的科学问题。', 'Transform each gap into auditable scientific questions.')
                            : step.id === 'audit'
                              ? t('核查支持/挑战证据与缺失陈述。', 'Check support/challenge evidence and missing statements.')
                              : step.id === 'rank'
                                ? t('计算质量分并完成候选排序。', 'Compute quality score and rank final candidates.')
                                : t('收集人工反馈并持续优化。', 'Collect human feedback for iterative improvement.')}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panelHeader">
              <div className="panelTitle">{t('任务追踪', 'Task Trace')}</div>
            </div>
            <div className="panelBody stack">
              <div className="metaLine">{t('任务 ID', 'Task ID')}: <code>{taskId || '-'}</code></div>
              <div className="metaLine">{t('阶段', 'Stage')}: <code>{String(task?.stage ?? '-')}</code></div>
              <div className="progress">
                <div className="progressBar" style={{ width: `${progress}%` }} />
              </div>
              <div className="metaLine">{t('进度', 'Progress')}: {progress}%</div>
              {task?.message && <div className="metaLine">{t('消息', 'Message')}: {task.message}</div>}

              <div className="traceLog">
                {taskLogs.map((line, idx) => (
                  <div key={`${line}-${idx}`} className="traceLine">{line}</div>
                ))}
                {taskLogs.length === 0 && <div className="metaLine">{t('暂无日志。', 'No logs yet.')}</div>}
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panelHeader">
              <div className="panelTitle">{t('质量快照', 'Quality Snapshot')}</div>
            </div>
            <div className="panelBody discoveryMetrics">
              <div className="metricCard">
                <div className="metricLabel">{t('缺口数', 'Gap Count')}</div>
                <div className="metricValue">{gapCount}</div>
              </div>
              <div className="metricCard">
                <div className="metricLabel">{t('候选数', 'Candidates')}</div>
                <div className="metricValue">{qualitySummary.total}</div>
              </div>
              <div className="metricCard">
                <div className="metricLabel">{t('平均分', 'Avg Score')}</div>
                <div className="metricValue">{qualitySummary.avgScore.toFixed(2)}</div>
              </div>
              <div className="metricCard">
                <div className="metricLabel">{t('支持覆盖率', 'Support Coverage')}</div>
                <div className="metricValue">{qualitySummary.supportCoverage}%</div>
              </div>
            </div>
            <div className="panelBody" style={{ paddingTop: 0 }}>
              <div className="row">
                <span className="badge badgeOk">{t('已采纳', 'Accepted')} {qualitySummary.accepted}</span>
                <span className="badge badgeDanger">{t('已拒绝', 'Rejected')} {qualitySummary.rejected}</span>
                <span className="badge badgeWarn">{t('待补证据', 'Needs More')} {qualitySummary.needsMore}</span>
              </div>
            </div>
          </section>
        </div>

        <div className="stack">
          <section className="panel">
            <div className="panelHeader">
              <div className="panelTitle">{t('候选列表', 'Candidate List')}</div>
            </div>
            <div className="panelBody candidateList">
              {candidates.map((item) => {
                const scorePct = qualityPercent(item.quality_score)
                return (
                  <button
                    key={item.candidate_id}
                    type="button"
                    className={`candidateCard${selectedCandidateId === item.candidate_id ? ' is-active' : ''}`}
                    onClick={() => setSelectedCandidateId(item.candidate_id)}
                  >
                    <div className="split">
                      <div className="candidateTitle">#{item.rank ?? '-'} {item.question}</div>
                      <span className={candidateBadgeClass(item.status)}>{candidateStatusLabel(item.status, locale)}</span>
                    </div>
                    <div className="candidateMetaRow">
                      <span>id: {item.candidate_id}</span>
                      <span>{t('分数', 'score')}: {Number(item.quality_score ?? 0).toFixed(2)}</span>
                    </div>
                    <div className="qualityMeter">
                      <div className="qualityBar" style={{ width: `${scorePct}%` }} />
                    </div>
                  </button>
                )
              })}
              {candidates.length === 0 && <div className="metaLine">{t('暂无候选，请先运行发现批处理。', 'No candidates yet. Run discovery batch first.')}</div>}
            </div>
          </section>

          <section className="panel">
            <div className="panelHeader">
              <div className="panelTitle">{t('候选详情与反馈', 'Candidate Detail & Feedback')}</div>
            </div>
            <div className="panelBody stack">
              {!selectedCandidate && <div className="metaLine">{t('请选择一条候选查看详情。', 'Select a candidate to inspect detail.')}</div>}

              {selectedCandidate && (
                <>
                  <div className="itemCard">
                    <div className="itemTitle">{selectedCandidate.question}</div>
                    <div className="itemMeta">candidate_id: {selectedCandidate.candidate_id}</div>
                    <div className="itemMeta">gap_id: {selectedCandidate.gap_id ?? '-'}</div>
                    <div className="itemMeta">quality_score: {Number(selectedCandidate.quality_score ?? 0).toFixed(2)}</div>
                    <div className="itemMeta">{t('支持证据', 'support evidence')}: {(selectedCandidate.support_evidence_ids ?? []).length}</div>
                    <div className="itemMeta">{t('挑战证据', 'challenge evidence')}: {(selectedCandidate.challenge_evidence_ids ?? []).length}</div>
                  </div>

                  <div className="itemCard">
                    <div className="itemMeta" style={{ marginTop: 0 }}>{t('缺失证据说明', 'missing evidence statement')}</div>
                    <div className="itemBody">{selectedCandidate.missing_evidence_statement?.trim() || t('无', 'None')}</div>
                  </div>

                  <div className="itemCard">
                    <div className="itemMeta" style={{ marginTop: 0, marginBottom: 8 }}>{t('反馈备注（可选）', 'Feedback note (optional)')}</div>
                    <textarea
                      className="textarea"
                      value={feedbackNote}
                      onChange={(e) => setFeedbackNote(e.target.value)}
                      placeholder={t('记录该候选被采纳/拒绝的原因。', 'Record why this candidate should be accepted/rejected.')}
                    />
                    <div className="row" style={{ marginTop: 10 }}>
                      <button className="btn btnSmall btnPrimary" disabled={!!feedbackBusy} onClick={() => void submitFeedback('accepted')}>
                        {feedbackBusy === 'accepted' ? t('提交中...', 'Submitting...') : t('采纳', 'Accept')}
                      </button>
                      <button className="btn btnSmall" disabled={!!feedbackBusy} onClick={() => void submitFeedback('needs_revision')}>
                        {feedbackBusy === 'needs_revision' ? t('提交中...', 'Submitting...') : t('需修订', 'Needs Revision')}
                      </button>
                      <button className="btn btnSmall btnDanger" disabled={!!feedbackBusy} onClick={() => void submitFeedback('rejected')}>
                        {feedbackBusy === 'rejected' ? t('提交中...', 'Submitting...') : t('拒绝', 'Reject')}
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
