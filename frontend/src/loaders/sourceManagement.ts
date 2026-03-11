import { apiGet, apiPost } from '../api'
import { loadTextbookCatalog, type TextbookRow } from './panelData'

export type DeleteTaskSummary = {
  deleted_count?: number
  failed_count?: number
  skipped_count?: number
  rebuild?: Record<string, unknown> | null
  items?: Array<Record<string, unknown>>
}

export type DeleteTaskRecord = {
  task_id: string
  status?: string
  stage?: string
  message?: string | null
  error?: string | null
  result?: DeleteTaskSummary | null
}

export type PaperManagementRow = {
  paper_id: string
  paper_source?: string
  title?: string
  doi?: string
  year?: number
  ingested?: boolean
  display_title?: string
  deletable?: boolean
  collections?: Array<{
    collection_id: string
    name: string
  }>
}

type SubmitTaskResponse = {
  task_id: string
}

type PaperManagementResponse = {
  papers?: PaperManagementRow[]
}

export async function submitPaperDeleteTask(paperIds: string[]): Promise<SubmitTaskResponse> {
  return apiPost<SubmitTaskResponse>('/tasks/delete/papers', {
    paper_ids: paperIds,
    trigger_rebuild: true,
  })
}

export async function submitTextbookDeleteTask(textbookIds: string[]): Promise<SubmitTaskResponse> {
  return apiPost<SubmitTaskResponse>('/tasks/delete/textbooks', {
    textbook_ids: textbookIds,
    trigger_rebuild: true,
  })
}

export async function loadDeleteTask(taskId: string): Promise<DeleteTaskRecord> {
  return apiGet<DeleteTaskRecord>(`/tasks/${encodeURIComponent(taskId)}`)
}

export async function loadPaperManagementRows(limit = 200, query = ''): Promise<PaperManagementRow[]> {
  const qs = new URLSearchParams({ limit: String(limit) })
  if (query.trim()) qs.set('q', query.trim())
  const response = await apiGet<PaperManagementResponse>(`/papers/manage?${qs.toString()}`)
  return response.papers ?? []
}

export async function loadTextbookManagementRows(limit = 100): Promise<TextbookRow[]> {
  return loadTextbookCatalog(limit, { force: true })
}
