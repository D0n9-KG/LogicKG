import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiGet, apiPost, apiPostForm } from '../api'
import { TERMS } from '../ui/terms'

type TaskInfo = {
  task_id: string
  status?: string
  progress?: number
  stage?: string
  message?: string | null
  error?: string | null
} & Record<string, unknown>

type ScanUnit = {
  unit_id: string
  unit_rel_dir: string
  md_rel_path: string
  doi?: string | null
  title?: string | null
  year?: number | null
  paper_type?: string | null
  status: string
  error?: string | null
  existing_paper_id?: string | null
}

type UploadScan = {
  upload_id: string
  mode: string
  doi_strategy?: string
  root: string
  units: ScanUnit[]
  errors?: unknown[]
}

type FolderFile = { path: string; file: File; size: number }
type DoiStrategy = 'extract_only' | 'title_crossref'

type WebkitFileEntry = {
  isFile: true
  isDirectory: false
  name: string
  file: (success: (file: File) => void, error?: (err: unknown) => void) => void
}

type WebkitDirectoryReader = {
  readEntries: (success: (entries: WebkitEntry[]) => void, error?: (err: unknown) => void) => void
}

type WebkitDirectoryEntry = {
  isFile: false
  isDirectory: true
  name: string
  createReader: () => WebkitDirectoryReader
}

type WebkitEntry = WebkitFileEntry | WebkitDirectoryEntry

type WebkitFile = File & { webkitRelativePath?: string }

async function walkEntry(entry: WebkitEntry | null, prefix: string): Promise<FolderFile[]> {
  if (!entry) return []
  if (entry.isFile) {
    const file: File = await new Promise((resolve, reject) => entry.file(resolve, reject))
    return [{ path: `${prefix}${file.name}`, file, size: file.size }]
  }
  if (entry.isDirectory) {
    const reader = entry.createReader()
    const entries: WebkitEntry[] = []
    while (true) {
      const batch = await new Promise<WebkitEntry[]>((resolve, reject) => reader.readEntries(resolve, reject))
      if (!batch || batch.length === 0) break
      entries.push(...batch)
    }
    const out: FolderFile[] = []
    for (const child of entries) {
      out.push(...(await walkEntry(child, `${prefix}${entry.name}/`)))
    }
    return out
  }
  return []
}

function groupScan(scan: UploadScan | null) {
  const units = scan?.units ?? []
  return {
    ready: units.filter((u) => u.status === 'ready'),
    conflicts: units.filter((u) => u.status === 'conflict'),
    needDoi: units.filter((u) => u.status === 'need_doi'),
    errors: units.filter((u) => u.status === 'error'),
  }
}

function taskStatusLabel(status: string | null | undefined) {
  const s = String(status ?? '')
  if (!s) return ''
  if (s === 'queued') return '排队中'
  if (s === 'running') return '进行中'
  if (s === 'succeeded') return '成功'
  if (s === 'failed') return '失败'
  if (s === 'canceled') return '已取消'
  return s
}

function taskStageLabel(stage: string | null | undefined) {
  const s = String(stage ?? '')
  if (!s) return ''
  if (s.includes('crossref')) return `${TERMS.crossref} 解析`
  if (s.includes('neo4j_clear')) return '清理 Neo4j'
  if (s.includes('neo4j_write')) return '写入 Neo4j'
  if (s.includes('llm')) return `${TERMS.llm} 抽取`
  if (s.includes('faiss')) return `${TERMS.faiss} 重建`
  if (s === 'done') return '完成'
  if (s === 'canceled') return '已取消'
  if (s === 'failed') return '失败'
  return s
}

function parseApiDetailMessage(msg: string): string {
  const s = String(msg ?? '').trim()
  if (!s) return ''
  try {
    const obj = JSON.parse(s) as { detail?: unknown } | null
    if (obj && typeof obj.detail === 'string') return obj.detail
  } catch {
    // ignore
  }
  return s
}

function normalizeDoiStrategy(v: unknown): DoiStrategy {
  return String(v ?? '').trim().toLowerCase() === 'title_crossref' ? 'title_crossref' : 'extract_only'
}

export default function IngestPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [error, setError] = useState<string>('')
  const [info, setInfo] = useState<string>('')
  const [result, setResult] = useState<string>('')

  // Upload ingest
  const [chunkMB, setChunkMB] = useState<number>(8)
  const chunkBytes = useMemo(() => Math.max(256 * 1024, Math.min(64 * 1024 * 1024, Math.floor(chunkMB * 1024 * 1024))), [chunkMB])
  const [zipFile, setZipFile] = useState<File | null>(null)
  const [folderFiles, setFolderFiles] = useState<FolderFile[]>([])
  const [uploadBusy, setUploadBusy] = useState<boolean>(false)
  const [uploadId, setUploadId] = useState<string>('')
  const [uploadProgress, setUploadProgress] = useState<{ sent: number; total: number }>({ sent: 0, total: 0 })
  const [scan, setScan] = useState<UploadScan | null>(null)
  const [doiStrategy, setDoiStrategy] = useState<DoiStrategy>('extract_only')
  const [doiByUnit, setDoiByUnit] = useState<Record<string, string>>({})
  const [paperTypeByUnit, setPaperTypeByUnit] = useState<Record<string, string>>({})

  // Tasks polling (commit_ready / replace_with_new / rebuild)
  const [taskId, setTaskId] = useState<string>('')
  const [task, setTask] = useState<TaskInfo | null>(null)
  const [actionUnitId, setActionUnitId] = useState<string>('')
  const [refreshedForTaskId, setRefreshedForTaskId] = useState<string>('')
  const [hydrated, setHydrated] = useState<boolean>(false)
  const [loadUploadId, setLoadUploadId] = useState<string>('')

  const persistKey = 'logickg.ingest.state.v1'

  useEffect(() => {
    try {
      const urlUploadId = String(searchParams.get('upload_id') ?? '').trim()
      const urlTaskId = String(searchParams.get('task_id') ?? '').trim()
      const raw = localStorage.getItem(persistKey)
      const s = (raw ? (JSON.parse(raw) as Partial<{
        chunkMB: number
        uploadId: string
        scan: UploadScan | null
        doiStrategy: DoiStrategy
        taskId: string
        doiByUnit: Record<string, string>
        paperTypeByUnit: Record<string, string>
      }>) : {}) as Partial<{
        chunkMB: number
        uploadId: string
        scan: UploadScan | null
        doiStrategy: DoiStrategy
        taskId: string
        doiByUnit: Record<string, string>
        paperTypeByUnit: Record<string, string>
      }>
      if (typeof s.chunkMB === 'number' && Number.isFinite(s.chunkMB)) setChunkMB(s.chunkMB)
      if (s.scan) setScan(s.scan)
      if (s.scan?.doi_strategy) setDoiStrategy(normalizeDoiStrategy(s.scan.doi_strategy))
      if (s.doiStrategy) setDoiStrategy(normalizeDoiStrategy(s.doiStrategy))
      const storedUploadId =
        (typeof s.uploadId === 'string' && s.uploadId) || (s.scan?.upload_id ? String(s.scan.upload_id) : '')
      const id = urlUploadId || storedUploadId
      if (id) {
        setUploadId(id)
        setLoadUploadId(id)
      }

      const tId = urlTaskId || (typeof s.taskId === 'string' ? s.taskId : '')
      if (tId) setTaskId(tId)
      if (s.doiByUnit && typeof s.doiByUnit === 'object') setDoiByUnit(s.doiByUnit)
      if (s.paperTypeByUnit && typeof s.paperTypeByUnit === 'object') setPaperTypeByUnit(s.paperTypeByUnit)
      if (id || tId) setInfo('已恢复上次导入会话（upload_id / 扫描结果 / 任务状态）。')
    } catch {
      // ignore
    } finally {
      setHydrated(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!hydrated) return
    try {
      const payload = { chunkMB, uploadId, scan, doiStrategy, taskId, doiByUnit, paperTypeByUnit }
      localStorage.setItem(persistKey, JSON.stringify(payload))
    } catch {
      // ignore
    }
  }, [chunkMB, doiByUnit, doiStrategy, hydrated, paperTypeByUnit, scan, taskId, uploadId])

  useEffect(() => {
    if (!hydrated) return
    const currentUploadId = String(searchParams.get('upload_id') ?? '')
    const currentTaskId = String(searchParams.get('task_id') ?? '')

    const next = new URLSearchParams(searchParams)
    if (uploadId) next.set('upload_id', uploadId)
    else next.delete('upload_id')

    if (taskId) next.set('task_id', taskId)
    else next.delete('task_id')

    const nextUploadId = String(next.get('upload_id') ?? '')
    const nextTaskId = String(next.get('task_id') ?? '')
    if (nextUploadId === currentUploadId && nextTaskId === currentTaskId) return
    setSearchParams(next, { replace: true })
  }, [hydrated, searchParams, setSearchParams, taskId, uploadId])

  useEffect(() => {
    if (!uploadId && scan?.upload_id) setUploadId(String(scan.upload_id))
  }, [scan, uploadId])

  useEffect(() => {
    if (!uploadId) return
    if (!loadUploadId.trim() || loadUploadId.trim() === uploadId) setLoadUploadId(uploadId)
  }, [loadUploadId, uploadId])

  const refreshScan = useCallback(async (id: string) => {
    const s = await apiGet<UploadScan>(`/ingest/upload/scan?upload_id=${encodeURIComponent(id)}`)
    setScan(s)
    if (s?.doi_strategy) setDoiStrategy(normalizeDoiStrategy(s.doi_strategy))
    return s
  }, [])

  useEffect(() => {
    if (!uploadId) return
    // Best-effort: refresh scan after route-switch / reload
    refreshScan(uploadId).catch((e: unknown) => {
      const raw = String((e as { message?: unknown } | null)?.message ?? e)
      const detail = parseApiDetailMessage(raw).toLowerCase()
      const missingUpload =
        (detail.includes('upload') && (detail.includes('not found') || detail.includes('missing') || detail.includes('404'))) ||
        detail.includes('no such file or directory') ||
        detail.includes('manifest.json')
      if (missingUpload) {
        setError('')
        setScan(null)
        setUploadId('')
        setLoadUploadId('')
        setInfo(`上次 upload_id 已失效并被清理：${uploadId}`)
      }
    })
  }, [uploadId, refreshScan])

  const scanGroups = useMemo(() => groupScan(scan), [scan])
  const uploadPct = useMemo(() => {
    if (!uploadProgress.total) return 0
    return Math.round((uploadProgress.sent / uploadProgress.total) * 100)
  }, [uploadProgress.sent, uploadProgress.total])
  const scanTotal = scan?.units.length ?? 0
  const scanIssueCount = scanGroups.conflicts.length + scanGroups.needDoi.length + scanGroups.errors.length
  const taskProgressPct = Math.round(Math.max(0, Math.min(1, Number(task?.progress ?? 0))) * 100)
  const taskIsActive = ['queued', 'running'].includes(String(task?.status ?? ''))

  const pollTask = useCallback(async (id: string): Promise<{ isFinal: boolean }> => {
    let t: TaskInfo
    try {
      t = await apiGet<TaskInfo>(`/tasks/${encodeURIComponent(id)}`)
    } catch (e: unknown) {
      const raw = String((e as { message?: unknown } | null)?.message ?? e)
      const detail = parseApiDetailMessage(raw)
      const isMissing =
        detail.includes('Task not found') ||
        detail.includes('No such file or directory') ||
        detail.includes('storage\\\\tasks') ||
        detail.includes('storage/tasks')
      if (isMissing) {
        setError('')
        setTask(null)
        setTaskId('')
        setInfo(`上次任务记录已过期/被清理：${id}\n已自动清除 task_id，可重新发起导入/重建任务。`)
        try {
          const sp = new URLSearchParams(searchParams)
          sp.delete('task_id')
          setSearchParams(sp, { replace: true })
        } catch {
          // ignore
        }
        return { isFinal: true }
      }
      throw e
    }
    setTask(t)
    const status = String(t?.status ?? '')
    const isFinal = status && !['queued', 'running'].includes(status)
    const type = String((t as { type?: unknown } | null)?.type ?? '')
    const payloadUploadId = String(
      ((t as { payload?: { upload_id?: unknown } } | null)?.payload?.upload_id as string | undefined) ?? '',
    ).trim()
    if (payloadUploadId && (type === 'ingest_upload_ready' || type === 'upload_replace') && payloadUploadId !== uploadId) {
      setUploadId(payloadUploadId)
      setLoadUploadId(payloadUploadId)
    }
    if (status && !['queued', 'running'].includes(status)) {
      setResult(JSON.stringify(t, null, 2))
      if (status === 'succeeded') setInfo(`任务已完成：${id}`)
      if (status === 'failed') setInfo(`任务失败：${id}\n${String(t?.error ?? t?.message ?? '')}`.trim())
      if (status === 'canceled') setInfo(`任务已取消：${id}`)
    }
    if (isFinal && id !== refreshedForTaskId) {
      if (type === 'upload_replace') setActionUnitId('')
      const effectiveUploadId = payloadUploadId || uploadId
      if (effectiveUploadId && (type === 'ingest_upload_ready' || type === 'upload_replace')) {
        setRefreshedForTaskId(id)
        await refreshScan(effectiveUploadId)
      }
    }
    return { isFinal: Boolean(isFinal) }
  }, [refreshScan, refreshedForTaskId, searchParams, setSearchParams, uploadId])

  useEffect(() => {
    if (!taskId) return
    let alive = true
    let stopped = false
    let iv: ReturnType<typeof setInterval> | null = null
    const stop = () => {
      if (stopped) return
      stopped = true
      alive = false
      if (iv) clearInterval(iv)
      iv = null
    }
    const tick = async () => {
      if (!alive) return
      const r = await pollTask(taskId)
      if (r.isFinal) stop()
    }
    tick().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
    iv = setInterval(() => tick().catch(() => {}), 1200)
    return () => {
      stop()
    }
  }, [taskId, pollTask])

  async function rebuildFaiss() {
    setError('')
    setResult('')
    setTask(null)
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/rebuild/faiss', {})
      setTaskId(res.task_id ?? '')
      setInfo(`已提交任务：重建全局 FAISS（${res.task_id ?? ''}）`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function rebuildAll() {
    if (!window.confirm('确定要“全链路重建（所有论文）”吗？\n这会重新解析/抽取并写回 Neo4j，并在最后重建全局 FAISS。')) return
    setError('')
    setResult('')
    setTask(null)
    try {
      const res = await apiPost<{ task_id: string }>('/tasks/rebuild/all', {})
      setTaskId(res.task_id ?? '')
      setInfo(`已提交任务：全链路重建（${res.task_id ?? ''}）`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function uploadChunksZip(id: string, file: File) {
    const totalChunks = Math.ceil(file.size / chunkBytes)
    const status = await apiGet<{ received?: number[] }>(`/ingest/upload/status?upload_id=${encodeURIComponent(id)}`)
    const received = new Set<number>((status?.received ?? []) as number[])
    setUploadProgress({ sent: 0, total: file.size })
    for (let idx = 0; idx < totalChunks; idx++) {
      if (received.has(idx)) continue
      const start = idx * chunkBytes
      const end = Math.min(file.size, start + chunkBytes)
      const blob = file.slice(start, end)
      const form = new FormData()
      form.append('upload_id', id)
      form.append('index', String(idx))
      form.append('blob', blob, `chunk-${idx}.bin`)
      await apiPostForm('/ingest/upload/chunk', form)
      setUploadProgress((p) => ({ sent: Math.min(p.total, p.sent + (end - start)), total: p.total }))
    }
  }

  async function uploadChunksFolder(id: string, files: FolderFile[]) {
    const total = files.reduce((a, b) => a + b.size, 0)
    setUploadProgress({ sent: 0, total })
    for (const f of files) {
      const totalChunks = Math.max(1, Math.ceil(f.size / chunkBytes))
      const st = await apiGet<{ received?: number[] }>(
        `/ingest/upload/status?upload_id=${encodeURIComponent(id)}&file_path=${encodeURIComponent(f.path)}`,
      )
      const received = new Set<number>((st?.received ?? []) as number[])
      for (let idx = 0; idx < totalChunks; idx++) {
        if (received.has(idx)) continue
        const start = idx * chunkBytes
        const end = Math.min(f.size, start + chunkBytes)
        const blob = f.file.slice(start, end)
        const form = new FormData()
        form.append('upload_id', id)
        form.append('index', String(idx))
        form.append('file_path', f.path)
        form.append('blob', blob, `chunk-${idx}.bin`)
        await apiPostForm('/ingest/upload/chunk', form)
        setUploadProgress((p) => ({ sent: Math.min(p.total, p.sent + (end - start)), total: p.total }))
      }
    }
  }

  async function startUpload(mode: 'zip' | 'folder') {
    setUploadBusy(true)
    setError('')
    setResult('')
    setInfo('')
    setTask(null)
    setTaskId('')
    setActionUnitId('')
    setRefreshedForTaskId('')
    setScan(null)
    try {
      if (mode === 'zip') {
        if (!zipFile) throw new Error('请先选择一个 .zip 文件。')
        const start = await apiPost<{ upload_id: string }>('/ingest/upload/start', {
          mode: 'zip',
          chunk_bytes: chunkBytes,
          total_bytes: zipFile.size,
          filename: zipFile.name,
          doi_strategy: doiStrategy,
        })
        const id = String(start.upload_id ?? '')
        setUploadId(id)
        setLoadUploadId(id)
        await uploadChunksZip(id, zipFile)
        const s = await apiPost<UploadScan>(`/ingest/upload/finish?upload_id=${encodeURIComponent(id)}`, {})
        setScan(s)
        setInfo(`上传完成：${id}\n已生成扫描结果，可继续处理冲突 / 缺 DOI / 可导入项。`)
      } else {
        if (folderFiles.length === 0) throw new Error('请先选择或拖入一个文件夹。')
        const start = await apiPost<{ upload_id: string }>('/ingest/upload/start', {
          mode: 'folder',
          chunk_bytes: chunkBytes,
          files: folderFiles.map((f) => ({ path: f.path, size: f.size })),
          doi_strategy: doiStrategy,
        })
        const id = String(start.upload_id ?? '')
        setUploadId(id)
        setLoadUploadId(id)
        await uploadChunksFolder(id, folderFiles)
        const s = await apiPost<UploadScan>(`/ingest/upload/finish?upload_id=${encodeURIComponent(id)}`, {})
        setScan(s)
        setInfo(`上传完成：${id}\n已生成扫描结果，可继续处理冲突 / 缺 DOI / 可导入项。`)
      }
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setUploadBusy(false)
    }
  }

  async function setDoi(unitId: string) {
    if (!uploadId) return
    const doi = (doiByUnit[unitId] ?? '').trim()
    if (!doi) return
    setError('')
    try {
      await apiPost<Record<string, unknown>>('/ingest/upload/set_doi', { upload_id: uploadId, unit_id: unitId, doi })
      await refreshScan(uploadId)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function setPaperType(unitId: string, paperType: string) {
    if (!uploadId) return
    const pt = (paperType ?? '').trim().toLowerCase()
    if (!pt) return
    setError('')
    try {
      await apiPost<Record<string, unknown>>('/ingest/upload/set_paper_type', { upload_id: uploadId, unit_id: unitId, paper_type: pt })
      await refreshScan(uploadId)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function keepExisting(unitId: string) {
    if (!uploadId) return
    setError('')
    setResult('')
    try {
      await apiPost<Record<string, unknown>>('/ingest/upload/keep_existing', { upload_id: uploadId, unit_id: unitId })
      await refreshScan(uploadId)
      setInfo(`已从本次上传中移除该条目（保留库中现有 DOI）。`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function replaceWithNew(unitId: string) {
    if (!uploadId) return
    setError('')
    setResult('')
    try {
      const res = await apiPost<{ task_id: string }>('/ingest/upload/replace_with_new', { upload_id: uploadId, unit_id: unitId })
      setActionUnitId(unitId)
      setTaskId(res.task_id ?? '')
      setInfo(`已提交“用新版本替换”任务：${res.task_id ?? ''}\n你可以在“任务”页查看进度；任务完成后本页会自动刷新扫描结果。`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  async function commitReady() {
    if (!uploadId) return
    setError('')
    setResult('')
    try {
      const res = await apiPost<{ task_id: string }>('/ingest/upload/commit_ready', { upload_id: uploadId, unit_id: '_' })
      setTaskId(res.task_id ?? '')
      setInfo(`已提交“导入可导入项”任务：${res.task_id ?? ''}\n你可以在“任务”页查看进度；任务完成后本页会自动刷新扫描结果。`)
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    }
  }

  return (
    <div className="page ingestPage">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">导入</h2>
          <div className="pageSubtitle">上传导入 → 扫描分组（可导入 / 冲突 / 需 DOI）→ 后台任务入库</div>
        </div>
        <div className="pageActions">
          <span className="pill">
            <span className="kicker">分片(MB)</span>
            <input className="input ingestChunkInput" name="ingest_chunk_mb" type="number" min={1} max={64} value={chunkMB} onChange={(e) => setChunkMB(Number(e.target.value || 8))} />
          </span>
          <span className="pill">
            <span className="kicker">{'DOI\u7b56\u7565'}</span>
            <select className="input" name="ingest_doi_strategy" value={doiStrategy} onChange={(e) => setDoiStrategy(normalizeDoiStrategy(e.target.value))}>
              <option value="extract_only">{'\u89c4\u5219\u62bd\u53d6'}</option>
              <option value="title_crossref">{'\u6807\u9898 + Crossref'}</option>
            </select>
          </span>
          {uploadId && (
            <span className="pill">
              <span className="kicker">upload_id</span> <code>{uploadId}</code>
            </span>
          )}
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}
      {info && (
        <div className="infoBox ingestInfoBox">
          <div className="split">
            <div style={{ whiteSpace: 'pre-wrap' }}>{info}</div>
            <button className="btn btnSmall" onClick={() => setInfo('')}>
              清除
            </button>
          </div>
        </div>
      )}

      <div className="ingestSummaryRow">
        <div className="ingestSummaryCard">
          <div className="kicker">Session</div>
          <div className="ingestSummaryValue">{uploadId ? <code>{uploadId}</code> : '--'}</div>
          <div className="metaLine">Current upload context</div>
        </div>
        <div className="ingestSummaryCard">
          <div className="kicker">Units</div>
          <div className="ingestSummaryValue">{scanTotal}</div>
          <div className="metaLine">Detected scan units</div>
        </div>
        <div className="ingestSummaryCard">
          <div className="kicker">Pending</div>
          <div className="ingestSummaryValue">{scanIssueCount}</div>
          <div className="metaLine">Conflicts / DOI / Errors</div>
        </div>
        <div className="ingestSummaryCard">
          <div className="kicker">Task</div>
          <div className="ingestSummaryValue">{taskId ? `${taskProgressPct}%` : '--'}</div>
          <div className="metaLine">{taskId ? (taskIsActive ? 'Running' : 'Completed') : 'No active task'}</div>
        </div>
      </div>

      <div className="grid2 ingestTopGrid">
        <div className="panel ingestUploadPanel">
          <div className="panelHeader">
            <div className="split">
              <div className="panelTitle">上传（文件夹 / ZIP）</div>
              {uploadProgress.total > 0 && (
                <span className="pill">
                  <span className="kicker">进度</span> {uploadPct}% · {(uploadProgress.sent / 1e6).toFixed(1)}/{(uploadProgress.total / 1e6).toFixed(1)} MB
                </span>
              )}
            </div>
          </div>
          <div className="panelBody">
            <div className="stack">
              {uploadProgress.total > 0 && (
                <div className="progress">
                  <div className="progressBar" style={{ width: `${uploadPct}%` }} />
                </div>
              )}

              <div className="itemCard">
                <div className="itemTitle">ZIP（压缩包）</div>
                <div className="row" style={{ marginTop: 8 }}>
                  <input type="file" name="ingest_zip_file" accept=".zip" onChange={(e) => setZipFile(e.target.files?.[0] ?? null)} />
                  <button className="btn btnPrimary" disabled={uploadBusy} onClick={() => startUpload('zip')}>
                    {uploadBusy ? '上传中…' : '上传 ZIP'}
                  </button>
                </div>
                <div className="hint">适合一次性导入；断点续传会跳过已收到分片。</div>
              </div>

              <div className="itemCard">
                <div className="itemTitle">文件夹</div>
                <div className="row" style={{ marginTop: 8 }}>
                  <input
                    type="file"
                    name="ingest_folder_files"
                    // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                    // @ts-ignore
                    webkitdirectory="true"
                    multiple
                  onChange={(e) => {
                    const files = Array.from(e.target.files ?? [])
                    const mapped: FolderFile[] = files.map((f) => {
                      const wf = f as WebkitFile
                      return { path: String(wf.webkitRelativePath ?? f.name), file: f, size: f.size }
                    })
                    setFolderFiles(mapped)
                  }}
                />
                  <button className="btn btnPrimary" disabled={uploadBusy} onClick={() => startUpload('folder')}>
                    {uploadBusy ? '上传中…' : `上传文件夹（${folderFiles.length} 个文件）`}
                  </button>
                </div>

                <div
                  className={`dropZone ${folderFiles.length > 0 ? 'dropZoneStrong' : ''}`}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={async (e) => {
                    e.preventDefault()
                    setError('')
                    try {
                      const items = Array.from(e.dataTransfer.items ?? [])
                      const out: FolderFile[] = []
                      for (const it of items) {
                        const entry = (it as unknown as { webkitGetAsEntry?: () => WebkitEntry | null }).webkitGetAsEntry?.() ?? null
                        if (!entry) continue
                        out.push(...(await walkEntry(entry, '')))
                      }
                      if (out.length === 0) throw new Error('此处不支持拖拽文件夹，请使用文件夹选择器或 ZIP。')
                      setFolderFiles(out)
                    } catch (err: unknown) {
                      setError(String((err as { message?: unknown } | null)?.message ?? err))
                    }
                  }}
                  style={{ marginTop: 10 }}
                >
                  <div className="itemTitle">拖拽文件夹</div>
                  <div className="metaLine" style={{ marginTop: 6 }}>
                    Chrome / Edge 支持文件夹拖入（保留目录结构）；否则使用文件夹选择器或 ZIP。
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="panel ingestOpsPanel">
          <div className="panelHeader">
            <div className="panelTitle">任务状态 / 运维</div>
          </div>
          <div className="panelBody">
            <div className="stack">
              <div className="metaLine">
                {taskId ? (
                  <>
                    当前任务：<code>{taskId}</code> · {taskStatusLabel(task?.status)} · {(Number(task?.progress ?? 0) || 0).toFixed(2)} ·{' '}
                    {taskStageLabel(task?.stage)}
                  </>
                ) : (
                  '暂无运行中的任务。'
                )}
              </div>

              <div className="itemCard">
                <div className="itemTitle">会话恢复</div>
                <div className="metaLine" style={{ marginTop: 6 }}>
                  你可以粘贴 upload_id 载入扫描结果（也会同步到地址栏，便于分享/恢复）。注意：<code>127.0.0.1</code> 与 <code>localhost</code> 的浏览器存储不互通。
                </div>
                <div className="row" style={{ marginTop: 10 }}>
                  <input className="input ingestLoadInput" name="ingest_load_upload_id" value={loadUploadId} onChange={(e) => setLoadUploadId(e.target.value)} placeholder="upload_id（例如 upload-xxxx...）" />
                  <button
                    className="btn"
                    disabled={uploadBusy || !loadUploadId.trim()}
                    onClick={() => {
                      const id = loadUploadId.trim()
                      setUploadId(id)
                      refreshScan(id).catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
                    }}
                  >
                    载入
                  </button>
                </div>
              </div>
              <div className="row ingestOpsActions">
                <Link className="btn" to="/tasks" style={{ display: 'inline-flex', alignItems: 'center' }}>
                  打开任务列表
                </Link>
                <button className="btn" disabled={uploadBusy} onClick={rebuildFaiss}>
                  重建全局 FAISS
                </button>
                <button className="btn btnDanger" disabled={uploadBusy} onClick={rebuildAll}>
                  全链路重建
                </button>
              </div>
              <div className="hint ingestOpsHint">提示：导入 / 替换后如需增强问答证据覆盖，可在此重建全局 FAISS。</div>
            </div>
          </div>
        </div>
      </div>

      {scan && (
        <div className="panel ingestScanPanel">
          <div className="panelHeader">
            <div className="split">
              <div className="panelTitle">扫描结果</div>
              <div className="row">
                <span className="badge badgeOk">可导入 {scanGroups.ready.length}</span>
                <span className="badge badgeWarn">冲突 {scanGroups.conflicts.length}</span>
                <span className="badge badgeWarn">需 DOI {scanGroups.needDoi.length}</span>
                <span className="badge badgeDanger">错误 {scanGroups.errors.length}</span>
              </div>
            </div>
          </div>
          <div className="panelBody">
            <div className="row ingestScanActions">
              <button className="btn btnPrimary" disabled={uploadBusy} onClick={commitReady}>
                导入可导入项（异步）
              </button>
              <button
                className="btn"
                disabled={uploadBusy}
                  onClick={() => {
                    if (!uploadId) return
                    refreshScan(uploadId).catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
                  }}
                >
                  刷新扫描
                </button>
            </div>

            {scanGroups.conflicts.length > 0 && (
              <div className="ingestBucket ingestBucketConflict">
                <div className="metaLine">冲突（DOI 已存在）</div>
                <div className="list ingestBucketList">
                  {scanGroups.conflicts.map((u) => (
                    <div key={u.unit_id} className="itemCard">
                      <div className="itemMeta">
                        {u.year ?? ''} · <code>{u.doi ?? ''}</code> · <code>{u.unit_id}</code>
                      </div>
                      <div className="itemBody">{u.title ?? u.md_rel_path}</div>
                      <div className="row" style={{ marginTop: 10 }}>
                        <span className="kicker">论文类型</span>
                        <select
                          className="select ingestTypeSelect"
                          name={`ingest_conflict_type_${u.unit_id}`}
                          value={paperTypeByUnit[u.unit_id] ?? String(u.paper_type ?? 'research')}
                          onChange={(e) => {
                            const v = e.target.value
                            setPaperTypeByUnit({ ...paperTypeByUnit, [u.unit_id]: v })
                            setPaperType(u.unit_id, v).catch(() => {})
                          }}
                        >
                          <option value="research">研究型(Research)</option>
                          <option value="review">综述型(Review)</option>
                          <option value="software">软件型(Software)</option>
                          <option value="theoretical">理论型(Theoretical)</option>
                          <option value="case_study">案例型(Case Study)</option>
                        </select>
                      </div>
                      <div className="row" style={{ marginTop: 10 }}>
                        <button className="btn" onClick={() => keepExisting(u.unit_id)}>
                          保留现有
                        </button>
                        <button
                          className="btn btnPrimary"
                          disabled={uploadBusy || (actionUnitId === u.unit_id && ['queued', 'running'].includes(String(task?.status ?? '')))}
                          onClick={() => replaceWithNew(u.unit_id)}
                        >
                          {actionUnitId === u.unit_id && ['queued', 'running'].includes(String(task?.status ?? '')) ? '替换中…' : '用新版本替换（异步）'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {scanGroups.needDoi.length > 0 && (
              <div className="ingestBucket ingestBucketNeedDoi">
                <div className="metaLine">需要 DOI</div>
                <div className="list ingestBucketList">
                  {scanGroups.needDoi.map((u) => (
                    <div key={u.unit_id} className="itemCard">
                      <div className="itemMeta">
                        {u.year ?? ''} · <code>{u.unit_id}</code>
                      </div>
                      <div className="itemBody">{u.title ?? u.md_rel_path}</div>
                      <div className="row" style={{ marginTop: 10 }}>
                        <span className="kicker">论文类型</span>
                        <select
                          className="select ingestTypeSelect"
                          name={`ingest_needdoi_type_${u.unit_id}`}
                          value={paperTypeByUnit[u.unit_id] ?? String(u.paper_type ?? 'research')}
                          onChange={(e) => {
                            const v = e.target.value
                            setPaperTypeByUnit({ ...paperTypeByUnit, [u.unit_id]: v })
                            setPaperType(u.unit_id, v).catch(() => {})
                          }}
                        >
                          <option value="research">研究型(Research)</option>
                          <option value="review">综述型(Review)</option>
                          <option value="software">软件型(Software)</option>
                          <option value="theoretical">理论型(Theoretical)</option>
                          <option value="case_study">案例型(Case Study)</option>
                        </select>
                      </div>
                      <div className="row" style={{ marginTop: 10 }}>
                        <input className="input ingestDoiInput" name={`ingest_doi_${u.unit_id}`} placeholder="DOI（10.xxxx/...）" value={doiByUnit[u.unit_id] ?? ''} onChange={(e) => setDoiByUnit({ ...doiByUnit, [u.unit_id]: e.target.value })} />
                        <button className="btn btnPrimary" onClick={() => setDoi(u.unit_id)}>
                          设置 DOI
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {scanGroups.errors.length > 0 && (
              <div className="ingestBucket ingestBucketError">
                <div className="metaLine">错误</div>
                <div className="list ingestBucketList">
                  {scanGroups.errors.map((u) => (
                    <div key={u.unit_id} className="itemCard">
                      <div className="itemMeta">
                        <code>{u.unit_id}</code>
                      </div>
                      <div className="itemBody">{u.error ?? '未知错误'}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {result && (
        <div className="panel ingestResultPanel">
          <div className="panelHeader">
            <div className="panelTitle">结果 JSON</div>
          </div>
          <div className="panelBody">
            <pre style={{ whiteSpace: 'pre-wrap' }}>{result}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
