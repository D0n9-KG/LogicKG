import type { AskItem, AskModuleState, AskSession } from './types'

const DEFAULT_DRAFT_K = 8
const MAX_SESSION_TURNS = 30
const MAX_ASK_SESSIONS = 24
const ASK_STORE_VERSION = 2

export const ASK_STORE_KEY = 'logickg.ask.v1'
export const ASK_STORE_EVENT = 'logickg:ask_state_changed'

type AskStoreDraftPayload = {
  question?: unknown
  k?: unknown
}

type AskStoreSessionPayload = {
  id?: unknown
  title?: unknown
  createdAt?: unknown
  updatedAt?: unknown
  draft?: AskStoreDraftPayload
  currentId?: unknown
  items?: unknown
}

type AskStoreV2Payload = {
  version?: unknown
  currentSessionId?: unknown
  sessions?: unknown
}

type AskStoreV1Payload = {
  draft?: AskStoreDraftPayload
  currentId?: unknown
  items?: unknown
}

function makeSessionId() {
  return `ask-session-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

function clampK(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n)) return DEFAULT_DRAFT_K
  return Math.max(1, Math.min(20, Math.round(n)))
}

function normalizeText(value: unknown): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function normalizeTimestamp(value: unknown, fallback: number): number {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return fallback
  return Math.round(n)
}

function normalizeStatus(value: unknown): AskItem['status'] {
  if (value === 'running' || value === 'done' || value === 'error') return value
  return 'done'
}

function normalizeAskItem(value: unknown, fallbackTime: number): AskItem | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  const id = normalizeText(row.id)
  if (!id) return null
  return {
    ...row,
    id,
    question: String(row.question ?? ''),
    k: clampK(row.k),
    createdAt: normalizeTimestamp(row.createdAt, fallbackTime),
    status: normalizeStatus(row.status),
  } as AskItem
}

function normalizeHistory(items: unknown, fallbackTime: number): AskItem[] {
  if (!Array.isArray(items)) return []
  return items
    .map((item, index) => normalizeAskItem(item, fallbackTime + index))
    .filter((item): item is AskItem => item !== null)
    .slice(0, MAX_SESSION_TURNS)
}

function buildSessionTitle(history: AskItem[], explicitTitle?: unknown): string {
  const title = normalizeText(explicitTitle)
  if (title) return title
  const firstQuestion = normalizeText(history[0]?.question)
  if (!firstQuestion) return ''
  return firstQuestion.length <= 42 ? firstQuestion : `${firstQuestion.slice(0, 39)}...`
}

function latestSessionTimestamp(history: AskItem[], createdAt: number, updatedAt?: unknown): number {
  const explicit = normalizeTimestamp(updatedAt, 0)
  if (explicit > 0) return explicit
  let latest = createdAt
  for (const item of history) {
    latest = Math.max(latest, normalizeTimestamp(item.createdAt, createdAt))
  }
  return latest
}

function normalizeSessionPayload(value: unknown, fallbackIndex = 0): AskSession | null {
  if (!value || typeof value !== 'object') return null
  const row = value as AskStoreSessionPayload
  const fallbackTime = Date.now() + fallbackIndex
  const history = normalizeHistory(row.items, fallbackTime)
  const createdAt = normalizeTimestamp(row.createdAt, history[history.length - 1]?.createdAt ?? fallbackTime)
  const updatedAt = latestSessionTimestamp(history, createdAt, row.updatedAt)
  const currentId =
    typeof row.currentId === 'string'
      ? row.currentId
      : history.length
        ? history[0].id
        : null
  return {
    id: normalizeText(row.id) || makeSessionId(),
    title: buildSessionTitle(history, row.title),
    createdAt,
    updatedAt,
    history,
    currentId,
    draftQuestion: String(row.draft?.question ?? ''),
    draftK: clampK(row.draft?.k),
  }
}

function normalizeLegacyPayload(value: AskStoreV1Payload): AskSession | null {
  const history = normalizeHistory(value.items, Date.now())
  if (!history.length && !normalizeText(value.draft?.question)) return null
  const createdAt = history[history.length - 1]?.createdAt ?? Date.now()
  return {
    id: makeSessionId(),
    title: buildSessionTitle(history),
    createdAt,
    updatedAt: latestSessionTimestamp(history, createdAt),
    history,
    currentId:
      typeof value.currentId === 'string'
        ? value.currentId
        : history.length
          ? history[0].id
          : null,
    draftQuestion: String(value.draft?.question ?? ''),
    draftK: clampK(value.draft?.k),
  }
}

function sortSessions(sessions: AskSession[]): AskSession[] {
  return [...sessions]
    .slice(0, MAX_ASK_SESSIONS)
    .sort((a, b) => {
      if (a.updatedAt !== b.updatedAt) return b.updatedAt - a.updatedAt
      if (a.createdAt !== b.createdAt) return b.createdAt - a.createdAt
      return a.id.localeCompare(b.id)
    })
}

export function createAskSession(seed: Partial<AskSession> = {}): AskSession {
  const createdAt = normalizeTimestamp(seed.createdAt, Date.now())
  const history = normalizeHistory(seed.history ?? [], createdAt)
  const updatedAt = latestSessionTimestamp(history, createdAt, seed.updatedAt ?? createdAt)
  return {
    id: normalizeText(seed.id) || makeSessionId(),
    title: buildSessionTitle(history, seed.title),
    createdAt,
    updatedAt,
    history,
    currentId:
      typeof seed.currentId === 'string'
        ? seed.currentId
        : history.length
          ? history[0].id
          : null,
    draftQuestion: String(seed.draftQuestion ?? ''),
    draftK: clampK(seed.draftK),
  }
}

export function deriveAskModuleState(sessions: AskSession[], currentSessionId: string | null = null): AskModuleState {
  const normalizedSessions = sortSessions(sessions.map((session) => createAskSession(session))).slice(0, MAX_ASK_SESSIONS)

  const activeSession =
    (currentSessionId ? normalizedSessions.find((session) => session.id === currentSessionId) : undefined) ??
    normalizedSessions[0] ??
    null

  return {
    sessions: normalizedSessions,
    currentSessionId: activeSession?.id ?? null,
    history: activeSession?.history ?? [],
    currentId: activeSession?.currentId ?? null,
    draftQuestion: activeSession?.draftQuestion ?? '',
    draftK: activeSession?.draftK ?? DEFAULT_DRAFT_K,
  }
}

export function ensureAskSession(ask: AskModuleState): AskModuleState {
  if (ask.sessions.length) return deriveAskModuleState(ask.sessions, ask.currentSessionId)
  const nextSession = createAskSession()
  return deriveAskModuleState([nextSession], nextSession.id)
}

export function getCurrentAskSession(ask: AskModuleState): AskSession | null {
  if (!ask.sessions.length) return null
  return ask.sessions.find((session) => session.id === ask.currentSessionId) ?? ask.sessions[0] ?? null
}

export function isAskStatePristine(ask: AskModuleState): boolean {
  if (ask.sessions.length !== 1) return false
  const session = ask.sessions[0]
  if (!session) return false
  return (
    session.history.length === 0 &&
    session.currentId === null &&
    normalizeText(session.draftQuestion) === '' &&
    session.draftK === DEFAULT_DRAFT_K &&
    normalizeText(session.title) === ''
  )
}

export function mapCurrentAskSession(
  ask: AskModuleState,
  updater: (session: AskSession) => AskSession,
): AskModuleState {
  return mapAskSession(ask, ask.currentSessionId, updater)
}

export function mapAskSession(
  ask: AskModuleState,
  sessionId: string | null | undefined,
  updater: (session: AskSession) => AskSession,
): AskModuleState {
  const ensured = ensureAskSession(ask)
  const active =
    (sessionId ? ensured.sessions.find((session) => session.id === sessionId) : null) ??
    getCurrentAskSession(ensured)
  if (!active) return ensured
  const updated = updater(active)
  const sessions = ensured.sessions.map((session) => (session.id === active.id ? updated : session))
  return deriveAskModuleState(sessions, updated.id)
}

export function prependAskSession(ask: AskModuleState, session: AskSession): AskModuleState {
  return deriveAskModuleState([session, ...ask.sessions], session.id)
}

export function switchAskSession(ask: AskModuleState, sessionId: string): AskModuleState {
  if (!ask.sessions.some((session) => session.id === sessionId)) return deriveAskModuleState(ask.sessions, ask.currentSessionId)
  return deriveAskModuleState(ask.sessions, sessionId)
}

export function deleteAskSession(ask: AskModuleState, sessionId: string): AskModuleState {
  const remaining = ask.sessions.filter((session) => session.id !== sessionId)
  if (!remaining.length) {
    const nextSession = createAskSession()
    return deriveAskModuleState([nextSession], nextSession.id)
  }
  const nextCurrentId = ask.currentSessionId === sessionId ? remaining[0]?.id ?? null : ask.currentSessionId
  return deriveAskModuleState(remaining, nextCurrentId)
}

export function readAskModuleStateFromStorage(raw: string | null): AskModuleState | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as AskStoreV2Payload | AskStoreV1Payload
    if (Array.isArray((parsed as AskStoreV2Payload).sessions)) {
      const payload = parsed as AskStoreV2Payload
      const sessionRows = payload.sessions as unknown[]
      const sessions = sessionRows
        .map((session: unknown, index: number) => normalizeSessionPayload(session, index))
        .filter((session): session is AskSession => session !== null)
      if (!sessions.length) return null
      return deriveAskModuleState(sessions, normalizeText(payload.currentSessionId) || sessions[0].id)
    }

    const legacy = normalizeLegacyPayload(parsed as AskStoreV1Payload)
    if (!legacy) return null
    return deriveAskModuleState([legacy], legacy.id)
  } catch {
    return null
  }
}

export function serializeAskModuleState(ask: AskModuleState): string {
  return JSON.stringify({
    version: ASK_STORE_VERSION,
    currentSessionId: ask.currentSessionId ?? undefined,
    sessions: ask.sessions.map((session) => ({
      id: session.id,
      title: session.title || undefined,
      createdAt: session.createdAt,
      updatedAt: session.updatedAt,
      draft: { question: session.draftQuestion, k: clampK(session.draftK) },
      currentId: session.currentId ?? undefined,
      items: session.history,
    })),
  })
}
