import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiBaseUrl, apiGet, apiPost } from '../api'
import MarkdownView from '../components/MarkdownView'
import { useI18n } from '../i18n'
import { resolveAskGraph, type AskApiResponse } from '../loaders/ask'
import { loadOverviewGraph } from '../loaders/overview'
import { loadScope, saveScope, scopeLabel, type Scope } from '../scope'
import { ASK_STORE_EVENT, ASK_STORE_KEY, getCurrentAskSession, isAskStatePristine, readAskModuleStateFromStorage, serializeAskModuleState } from '../state/askSessions'
import { useGlobalState } from '../state/store'
import type { AskItem, AskSession, GraphElement } from '../state/types'
import {
  buildConversationPayload,
  buildChatMessages,
  assistantTurnText,
  buildScopePaperOptions,
  getScopePaperRenderState,
  shouldAutoRetryWithAllScope,
  toConversationTurns,
  toggleScopePaperIds,
  type ScopePaperApiRow,
} from './askPanelModel'

const OVERVIEW_GRAPH_PAPER_LIMIT = 400
const OVERVIEW_GRAPH_EDGE_LIMIT = 1200
const SCOPE_LIST_PAGE_SIZE = 120

const EXAMPLES_ZH = ['这篇论文的主要方法是什么？', '核心结论是什么？', '用一句话概括贡献。']
const EXAMPLES_EN = [
  'What is the main method of this paper?',
  'What is the core conclusion?',
  'Summarize the contribution in one sentence.',
]

type PaperListResponse = {
  papers?: Array<{
    paper_id?: string
    paper_source?: string
    title?: string
    year?: number
  }>
}

function makeId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function clampK(value: unknown) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 8
  return Math.max(1, Math.min(20, Math.round(n)))
}

function normalizeText(value: unknown): string {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
}

function parseJsonSafe<T>(value: string): T | null {
  try {
    return JSON.parse(value) as T
  } catch {
    return null
  }
}

async function streamAskRequest(
  payload: unknown,
  onDelta: (delta: string) => void,
): Promise<AskApiResponse> {
  const res = await fetch(`${apiBaseUrl()}/rag/ask_v2_stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    throw new Error(await res.text())
  }
  if (!res.body) {
    throw new Error('Streaming response body missing')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let donePayload: AskApiResponse | null = null

  const handleSseBlock = (rawBlock: string) => {
    const lines = rawBlock.split(/\r?\n/)
    let event = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
    const dataText = dataLines.join('\n')
    if (!dataText) return

    if (event === 'delta') {
      const parsed = parseJsonSafe<{ delta?: unknown }>(dataText)
      const delta = String(parsed?.delta ?? '')
      if (delta) onDelta(delta)
      return
    }

    if (event === 'done') {
      const parsed = parseJsonSafe<AskApiResponse>(dataText)
      if (parsed) donePayload = parsed
      return
    }

    if (event === 'error') {
      const parsed = parseJsonSafe<{ error?: unknown }>(dataText)
      const message = String(parsed?.error ?? dataText)
      throw new Error(message || 'Streaming request failed')
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let match = buffer.match(/\r?\n\r?\n/)
    while (match && typeof match.index === 'number') {
      const splitIndex = match.index
      const block = buffer.slice(0, splitIndex)
      buffer = buffer.slice(splitIndex + match[0].length)
      handleSseBlock(block)
      match = buffer.match(/\r?\n\r?\n/)
    }
  }

  const tail = buffer.trim()
  if (tail) handleSseBlock(tail)
  if (!donePayload) throw new Error('Streaming ended without done payload')
  return donePayload
}

function emitAskStoreChanged() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(ASK_STORE_EVENT))
}

function persistAskStore(serialized: string) {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') return
  localStorage.setItem(ASK_STORE_KEY, serialized)
  emitAskStoreChanged()
}

function sessionTitle(session: AskSession, fallback: string) {
  return normalizeText(session.title) || fallback
}

function sessionPreview(session: AskSession, locale: 'zh-CN' | 'en-US') {
  const latest = session.history[0]
  if (latest) return normalizeText(latest.question) || assistantTurnText(latest, locale)
  return normalizeText(session.draftQuestion)
}

function toRequestScope(scope: Scope): { mode: 'all' } | { mode: 'collection'; collection_id: string } | { mode: 'papers'; paper_ids: string[] } {
  if (scope.mode === 'collection') {
    return { mode: 'collection', collection_id: scope.collectionId ?? '' }
  }
  if (scope.mode === 'papers') {
    return { mode: 'papers', paper_ids: scope.paperIds ?? [] }
  }
  return { mode: 'all' }
}

export default function AskPanel() {
  const { state, dispatch } = useGlobalState()
  const { locale, t } = useI18n()
  const { ask } = state
  const hydratedRef = useRef(false)
  const chatListRef = useRef<HTMLDivElement | null>(null)
  const overviewGraphCacheRef = useRef<GraphElement[] | null>(null)
  const overviewGraphPromiseRef = useRef<Promise<GraphElement[]> | null>(null)

  const [, setScopeVersion] = useState(0)
  const [scopeQuery, setScopeQuery] = useState('')
  const [scopeRenderLimit, setScopeRenderLimit] = useState(SCOPE_LIST_PAGE_SIZE)
  const [scopeShowSelectedOnly, setScopeShowSelectedOnly] = useState(false)
  const [paperCatalog, setPaperCatalog] = useState<ScopePaperApiRow[]>([])
  const [paperCatalogLoading, setPaperCatalogLoading] = useState(false)
  const [paperCatalogError, setPaperCatalogError] = useState('')

  const currentSession = useMemo(() => getCurrentAskSession(ask), [ask])
  const current = useMemo(() => {
    const sessionHistory = currentSession?.history ?? []
    const sessionCurrentId = currentSession?.currentId ?? null
    if (sessionCurrentId) {
      const matched = sessionHistory.find((item) => item.id === sessionCurrentId)
      if (matched) return matched
    }
    return sessionHistory[0]
  }, [currentSession])
  const hasGraphNodes = useMemo(
    () => state.graphElements.some((item) => item.group === 'nodes'),
    [state.graphElements],
  )

  const busy = current?.status === 'running'
  const conversationTurns = useMemo(
    () => toConversationTurns(currentSession?.history ?? [], currentSession?.currentId ?? null),
    [currentSession],
  )
  const chatMessages = useMemo(() => buildChatMessages(conversationTurns, locale), [conversationTurns, locale])
  const latestChatMessageText = chatMessages[chatMessages.length - 1]?.text ?? ''
  const examples = locale === 'zh-CN' ? EXAMPLES_ZH : EXAMPLES_EN

  useEffect(() => {
    const el = chatListRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [chatMessages.length, current?.status, latestChatMessageText])

  useEffect(() => {
    if (hydratedRef.current) return
    hydratedRef.current = true

    if (!isAskStatePristine(ask)) return

    if (typeof window === 'undefined' || typeof localStorage === 'undefined') return
    const restored = readAskModuleStateFromStorage(localStorage.getItem(ASK_STORE_KEY))
    if (!restored) return
    dispatch({ type: 'ASK_RESTORE', ask: restored })
  }, [ask, dispatch])

  useEffect(() => {
    persistAskStore(serializeAskModuleState(ask))
  }, [ask])

  useEffect(() => {
    if (ask.currentId || ask.history.length === 0 || !ask.currentSessionId) return
    dispatch({ type: 'ASK_SET_CURRENT', id: ask.history[0].id, sessionId: ask.currentSessionId })
  }, [ask.currentId, ask.currentSessionId, ask.history, dispatch])

  useEffect(() => {
    let cancelled = false

    const applyOverview = (elements: GraphElement[]) => {
      if (cancelled) return
      dispatch({ type: 'SET_GRAPH', elements, layout: 'cose' })
      dispatch({ type: 'SET_TRANSITIONING', value: false })
    }

    const ensureOverviewGraph = () => {
      if (overviewGraphCacheRef.current?.length) {
        applyOverview(overviewGraphCacheRef.current)
        return
      }

      if (!overviewGraphPromiseRef.current) {
        overviewGraphPromiseRef.current = loadOverviewGraph(OVERVIEW_GRAPH_PAPER_LIMIT, OVERVIEW_GRAPH_EDGE_LIMIT)
          .then((elements) => {
            overviewGraphCacheRef.current = elements
            return elements
          })
          .finally(() => {
            overviewGraphPromiseRef.current = null
          })
      }

      overviewGraphPromiseRef.current
        .then((elements) => {
          applyOverview(elements)
        })
        .catch(() => {
          if (cancelled) return
          dispatch({ type: 'SET_TRANSITIONING', value: false })
        })
    }

    if (!current) {
      dispatch({ type: 'SET_SELECTED', node: null })
      dispatch({ type: 'SET_TRANSITIONING', value: false })
      ensureOverviewGraph()
      return () => {
        cancelled = true
      }
    }

    if (current.status === 'done') {
      const fallbackGraph = overviewGraphCacheRef.current ?? []
      const askGraphElements = resolveAskGraph(
        {
          answer: current.answer,
          evidence: current.evidence ?? [],
          fusion_evidence: current.fusionEvidence ?? [],
          dual_evidence_coverage: current.dualEvidenceCoverage ?? false,
          graph_context: current.graphContext ?? [],
          structured_knowledge: current.structuredKnowledge ?? null,
          structured_evidence: current.structuredEvidence ?? [],
          grounding: current.grounding ?? [],
        },
        fallbackGraph,
      )
      if (askGraphElements === fallbackGraph) {
        if (fallbackGraph.length) {
          dispatch({ type: 'SET_GRAPH', elements: fallbackGraph, layout: 'cose' })
        } else {
          ensureOverviewGraph()
        }
      } else {
        dispatch({ type: 'SET_GRAPH', elements: askGraphElements, layout: 'breadthfirst' })
      }
    } else if (!hasGraphNodes) {
      // Keep a visible graph while streaming the first answer.
      ensureOverviewGraph()
    }

    dispatch({ type: 'SET_SELECTED', node: null })
    dispatch({ type: 'SET_TRANSITIONING', value: false })
    return () => {
      cancelled = true
    }
  }, [current, hasGraphNodes, dispatch])

  useEffect(() => {
    const refresh = () => setScopeVersion((v) => v + 1)
    window.addEventListener('storage', refresh)
    window.addEventListener('logickg:scope_changed', refresh)
    return () => {
      window.removeEventListener('storage', refresh)
      window.removeEventListener('logickg:scope_changed', refresh)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const startTimer = window.setTimeout(() => {
      setPaperCatalogLoading(true)
      setPaperCatalogError('')
    }, 0)
    void apiGet<PaperListResponse>('/graph/papers?limit=2000')
      .then((res) => {
        if (cancelled) return
        const rows: ScopePaperApiRow[] = []
        for (const row of res.papers ?? []) {
          const id = normalizeText(row.paper_id)
          if (!id) continue
          const year = Number.isFinite(Number(row.year)) ? Number(row.year) : undefined
          rows.push({
            id,
            label: normalizeText(row.title) || normalizeText(row.paper_source) || id,
            year,
          })
        }
        setPaperCatalog(rows)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setPaperCatalog([])
        setPaperCatalogError(String((error as { message?: unknown } | null)?.message ?? error))
      })
      .finally(() => {
        if (!cancelled) setPaperCatalogLoading(false)
      })
    return () => {
      cancelled = true
      window.clearTimeout(startTimer)
    }
  }, [])

  const scope = loadScope()
  const scopePaperIds = useMemo(
    () => (scope.mode === 'papers' ? (scope.paperIds ?? []).map(String).filter(Boolean) : []),
    [scope.mode, scope.paperIds],
  )
  const scopePaperIdSet = useMemo(() => new Set(scopePaperIds), [scopePaperIds])

  const scopePaperOptions = useMemo(() => buildScopePaperOptions(paperCatalog), [paperCatalog])
  const scopePaperOptionMap = useMemo(() => new Map(scopePaperOptions.map((item) => [item.id, item])), [scopePaperOptions])

  const filteredScopePaperOptions = useMemo(() => {
    const query = scopeQuery.trim().toLowerCase()
    const scopedOptions = scopeShowSelectedOnly
      ? scopePaperOptions.filter((item) => scopePaperIdSet.has(item.id))
      : scopePaperOptions
    if (!query) return scopedOptions
    return scopedOptions.filter((item) => {
      const haystack = `${item.id} ${item.label} ${item.year ?? ''}`.toLowerCase()
      return haystack.includes(query)
    })
  }, [scopePaperIdSet, scopePaperOptions, scopeQuery, scopeShowSelectedOnly])

  const scopePaperRenderState = useMemo(
    () => getScopePaperRenderState(filteredScopePaperOptions, scopeRenderLimit),
    [filteredScopePaperOptions, scopeRenderLimit],
  )

  const submitQuestion = async (question: string, k: number, requestedScope: Scope) => {
    if (!question.trim() || busy) return

    const sessionId = ask.currentSessionId ?? currentSession?.id ?? null
    const id = makeId()
    const item: AskItem = {
      id,
      question: question.trim(),
      k: clampK(k),
      createdAt: Date.now(),
      status: 'running',
      answer: '',
      evidence: [],
      fusionEvidence: [],
      dualEvidenceCoverage: false,
      graphContext: [],
      structuredKnowledge: null,
      structuredEvidence: [],
      grounding: [],
      intent: '',
      retrievalPlan: '',
      queryPlan: null,
      retrievalMode: '',
      notice: '',
      insufficientScopeEvidence: false,
      error: '',
    }

    dispatch({ type: 'ASK_ADD_ITEM', item, sessionId: sessionId ?? undefined })
    dispatch({ type: 'ASK_SET_CURRENT', id, sessionId: sessionId ?? undefined })
    dispatch({ type: 'SET_SELECTED', node: null })

    try {
      const payload = {
        question: question.trim(),
        k: clampK(k),
        locale,
        conversation: buildConversationPayload(currentSession?.history ?? [], currentSession?.currentId ?? null, locale),
      }

        const requestWithStreaming = async (scopePayload: ReturnType<typeof toRequestScope>) => {
          let streamedAnswer = ''
          try {
            const response = await streamAskRequest(
              {
                ...payload,
                scope: scopePayload,
              },
              (delta) => {
                streamedAnswer += delta
                dispatch({
                  type: 'ASK_UPDATE_ITEM',
                  id,
                  sessionId: sessionId ?? undefined,
                  patch: {
                    status: 'running',
                    answer: streamedAnswer,
                    error: '',
                  },
                })
              },
            )
            if (!normalizeText(response.answer) && normalizeText(streamedAnswer)) {
              return { ...response, answer: streamedAnswer }
            }
            return response
          } catch {
            return apiPost<AskApiResponse>('/rag/ask_v2', {
              ...payload,
              scope: scopePayload,
            })
          }
        }

        let response = await requestWithStreaming(toRequestScope(requestedScope))
        let autoExpanded = false

        if (shouldAutoRetryWithAllScope(requestedScope.mode, response)) {
          autoExpanded = true
          dispatch({
            type: 'ASK_UPDATE_ITEM',
            id,
            sessionId: sessionId ?? undefined,
            patch: {
              status: 'running',
              answer: '',
              error: '',
            },
          })
          try {
            response = await requestWithStreaming({ mode: 'all' })
          } catch (retryError: unknown) {
            const retryMessage = normalizeText((retryError as { message?: unknown } | null)?.message ?? retryError)
            response = {
              ...response,
              message: [
                normalizeText(response.message),
                retryMessage
                  ? t(`自动扩大全图重试失败: ${retryMessage}`, `Auto-retry on full graph failed: ${retryMessage}`)
                  : t('自动扩大全图重试失败。', 'Auto-retry on full graph failed.'),
              ]
                .filter(Boolean)
                .join(' '),
            }
          }
        }

        const noticeParts: string[] = []
        if (autoExpanded) {
          noticeParts.push(
            t(
              '当前范围证据不足，已自动扩大到全图重试。',
              'Evidence is insufficient in the current scope. Retried automatically on full graph.',
            ),
          )
        }
        const responseMessage = normalizeText(response.message)
        if (responseMessage) noticeParts.push(responseMessage)

        dispatch({
          type: 'ASK_UPDATE_ITEM',
          id,
          sessionId: sessionId ?? undefined,
          patch: {
            status: 'done',
            answer: response.answer ?? '',
            evidence: response.evidence ?? [],
            fusionEvidence: response.fusion_evidence ?? [],
            dualEvidenceCoverage: Boolean(response.dual_evidence_coverage),
            graphContext: response.graph_context ?? [],
            structuredKnowledge: response.structured_knowledge ?? null,
            structuredEvidence: response.structured_evidence ?? [],
            grounding: response.grounding ?? [],
            intent: response.query_plan?.intent ?? '',
            retrievalPlan: response.query_plan?.retrieval_plan ?? '',
            queryPlan: response.query_plan ?? null,
            retrievalMode: response.retrieval_mode ?? '',
            notice: noticeParts.join(' '),
            insufficientScopeEvidence: Boolean(response.insufficient_scope_evidence),
            error: '',
          },
        })
      } catch (error: unknown) {
      dispatch({
        type: 'ASK_UPDATE_ITEM',
        id,
        sessionId: sessionId ?? undefined,
        patch: {
          status: 'error',
          error: String((error as { message?: unknown } | null)?.message ?? error),
        },
      })
    }
  }
  const submitAsk = async () => {
    const question = ask.draftQuestion.trim()
    if (!question || busy) return
    await submitQuestion(question, ask.draftK, scope)
  }

  const toggleScopePaper = useCallback(
    (paperId: string) => {
      const nextIds = toggleScopePaperIds(scopePaperIds, paperId)
      if (nextIds.length) {
        saveScope({ mode: 'papers', paperIds: nextIds })
      } else {
        saveScope({ mode: 'all' })
      }
    },
    [scopePaperIds],
  )

  const startNewSessionWithAllGraph = useCallback(() => {
    saveScope({ mode: 'all' })
    dispatch({ type: 'ASK_CREATE_SESSION' })
    dispatch({ type: 'SET_SELECTED', node: null })
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    setScopeQuery('')
    setScopeRenderLimit(SCOPE_LIST_PAGE_SIZE)
  }, [dispatch])

  const retryCurrentOnAllScope = async () => {
    if (!current || busy) return
    saveScope({ mode: 'all' })
    dispatch({ type: 'ASK_SET_DRAFT', question: current.question, k: current.k, sessionId: currentSession?.id })
    await submitQuestion(current.question, current.k, { mode: 'all' })
  }

  const deleteSession = useCallback(
    (sessionId: string) => {
      dispatch({ type: 'ASK_DELETE_SESSION', sessionId })
      dispatch({ type: 'SET_SELECTED', node: null })
      dispatch({ type: 'SET_TRANSITIONING', value: true })
    },
    [dispatch],
  )

  return (
    <div className="kgPanelBody kgStack kgAskChatShell">
      <div className="kgAskPanelSection">
        <div className="kgSectionTitle" style={{ marginTop: 0 }}>
          {t('历史会话', 'Sessions')}
        </div>
        <div className="kgStack kgAskHistoryList">
          {ask.sessions.map((session) => {
            const active = currentSession?.id === session.id
            const title = sessionTitle(session, t('新会话', 'New Session'))
            const preview = sessionPreview(session, locale) || t('暂无内容', 'No turns yet')
            return (
              <div key={session.id} className={`kgListItem${active ? ' is-active' : ''} kgAskHistoryItem`}>
                <div className="kgAskSessionRow">
                  <button
                    type="button"
                    className="kgAskSessionMain"
                    disabled={busy}
                    onClick={() => dispatch({ type: 'ASK_SWITCH_SESSION', sessionId: session.id })}
                  >
                    <div className="kgListItemTitle truncate">{title}</div>
                    <div className="kgListItemMeta truncate">{preview}</div>
                    <div className="kgListItemMeta">
                      <span>{t('轮次', 'Turns')}: {session.history.length}</span>
                      <span>{new Date(session.updatedAt).toLocaleString(locale)}</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    className="kgBtn kgBtn--sm"
                    disabled={busy}
                    onClick={() => deleteSession(session.id)}
                    title={t('删除会话', 'Delete session')}
                  >
                    {t('删除', 'Delete')}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="kgAskPanelSection kgAskConversationSection">
        <div className="kgSectionTitle" style={{ marginTop: 0 }}>
          {t('对话助手', 'Conversation')}
        </div>
        {chatMessages.length === 0 ? (
          <div className="kgCard kgAskConversationEmpty" style={{ marginBottom: 0 }}>
            <div className="kgCardBody kgStack">
              <div>{t('还没有会话记录。输入问题后点击“提问”，结果会按聊天流直接追加。', 'No conversation yet. Ask a question to start streaming replies in chat.')}</div>
              <div className="kgRow" style={{ flexWrap: 'wrap', gap: 6 }}>
                {examples.map((example) => (
                  <button
                    key={`ask-empty-example-${example}`}
                    className="kgTag"
                    type="button"
                    style={{ cursor: 'pointer' }}
                    onClick={() => dispatch({ type: 'ASK_SET_DRAFT', question: example })}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="kgAskChatList kgAskChatList--assistant" ref={chatListRef}>
            {chatMessages.map((message) => {
              const isUser = message.role === 'user'
              const isAssistantError = !isUser && message.status === 'error'
              const isRunningAssistant = !isUser && message.status === 'running'
              const hasLiveDelta = isRunningAssistant && normalizeText(message.text) !== assistantTurnText({ status: 'running' }, locale)
              const renderedText = message.text
              return (
                <div
                  key={message.id}
                  className={`kgAskMessageRow ${isUser ? 'is-user' : 'is-assistant'}${message.active ? ' is-active' : ''}`}
                >
                  <button
                    type="button"
                    className={[
                      'kgAskMessageBubble',
                      isUser ? 'kgAskMessageBubble--user' : 'kgAskMessageBubble--assistant',
                      message.active ? 'is-active' : '',
                      isAssistantError ? 'is-error' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => dispatch({ type: 'ASK_SET_CURRENT', id: message.turnId })}
                  >
                    <div className="kgAskMessageHead">
                      <span className="kgAskMessageRole">{isUser ? t('你', 'You') : t('助手', 'Assistant')}</span>
                      <span className="kgAskMessageMeta">{new Date(message.createdAt).toLocaleTimeString()}</span>
                    </div>
                    {!isUser && message.markdown ? (
                      <MarkdownView markdown={renderedText} className="kgAskAnswerMarkdown kgAskAnswerMarkdown--chat" />
                    ) : (
                      <div>{renderedText}</div>
                    )}
                    {!isUser && (
                      <div className="kgAskMessageFoot">
                        {t('状态', 'Status')}: {message.status} · k={message.k}
                        {isRunningAssistant && (
                          <span className="kgAskStreamTag">{hasLiveDelta ? t('流式输出中...', 'Streaming...') : t('处理中...', 'Processing...')}</span>
                        )}
                      </div>
                    )}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="kgAskPanelSection kgAskComposerSection">
        <div className="kgAskInputMeta">
          <span>{t('当前范围', 'Current Scope')}: {scopeLabel(scope, locale)}</span>
          <span>{t('会话轮次', 'Turns')}: {ask.history.length} · {t('Ctrl+Enter 发送', 'Ctrl+Enter to send')}</span>
        </div>
        <label className="sr-only" htmlFor="ask-draft-question">
          {t('问题输入', 'Question input')}
        </label>
        <textarea
          id="ask-draft-question"
          name="ask_draft_question"
          className="kgTextarea"
          aria-label={t('问题输入', 'Question input')}
          value={ask.draftQuestion}
          onChange={(event) => dispatch({ type: 'ASK_SET_DRAFT', question: event.target.value })}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              event.preventDefault()
              void submitAsk()
            }
          }}
          placeholder={t('输入你想问的问题...', 'Type your question...')}
          rows={3}
        />
        <div className="kgRow" style={{ marginTop: 8, flexWrap: 'wrap' }}>
          <label className="kgLabel" htmlFor="ask-draft-k" style={{ margin: 0 }}>
            k
          </label>
          <input
            id="ask-draft-k"
            name="ask_draft_k"
            className="kgInput"
            style={{ width: 70 }}
            type="number"
            aria-label={t('检索数量 k', 'Retrieval count k')}
            min={1}
            max={20}
            value={ask.draftK}
            onChange={(event) => dispatch({ type: 'ASK_SET_DRAFT', k: clampK(event.target.value) })}
          />
          <button className="kgBtn kgBtn--sm kgBtn--primary" disabled={!ask.draftQuestion.trim() || busy} onClick={() => void submitAsk()}>
            {busy ? t('思考中...', 'Thinking...') : t('提问', 'Ask')}
          </button>
          <button
            className="kgBtn kgBtn--sm"
            type="button"
            onClick={() => dispatch({ type: 'ASK_SET_DRAFT', question: '' })}
            disabled={!ask.draftQuestion.trim() || busy}
          >
            {t('清空输入', 'Clear')}
          </button>
          <button className="kgBtn kgBtn--sm" type="button" onClick={startNewSessionWithAllGraph} disabled={busy}>
            {t('新建问答（全图）', 'New Session (All Graph)')}
          </button>
        </div>

        {current?.status === 'done' && current.insufficientScopeEvidence && (
          <div className="kgRow" style={{ marginTop: 8, flexWrap: 'wrap', gap: 6 }}>
            <span className="kgTag">{t('当前范围证据不足', 'Insufficient Evidence in Scope')}</span>
            <button className="kgBtn kgBtn--sm" type="button" disabled={busy} onClick={() => void retryCurrentOnAllScope()}>
              {t('扩大全图重试当前问题', 'Retry on Full Graph')}
            </button>
          </div>
        )}

        <div className="kgRow" style={{ marginTop: 6, flexWrap: 'wrap', gap: 6 }}>
          {examples.map((example) => (
            <button
              key={example}
              className="kgTag"
              style={{ cursor: 'pointer' }}
              type="button"
              onClick={() => dispatch({ type: 'ASK_SET_DRAFT', question: example })}
            >
              {example}
            </button>
          ))}
        </div>
      </div>

      <details className="kgAskPanelSection kgAskScopeDetails">
        <summary className="kgSectionTitle">{t('RAG 范围设置', 'RAG Scope')}</summary>
        <div className="kgAskInputMeta">
          <span>{t('可选节点', 'Candidates')}: {scopePaperOptions.length}</span>
          <span>{t('已选节点', 'Selected')}: {scopePaperIds.length}</span>
        </div>
        {scope.mode === 'papers' && scopePaperIds.length > 0 ? (
          <div className="kgAskScopeSelected">
            <div className="kgAskScopeSelectedTitle">{t('当前用于 RAG 的 paper 节点', 'Paper nodes currently used for RAG')}</div>
            <div className="kgRow" style={{ marginTop: 6, flexWrap: 'wrap', gap: 6 }}>
              {scopePaperIds.slice(0, 12).map((paperId) => (
                <button
                  key={`ask-selected-paper-${paperId}`}
                  className="kgTag"
                  type="button"
                  style={{ cursor: 'pointer' }}
                  title={t('点击移除该节点', 'Click to remove')}
                  onClick={() => toggleScopePaper(paperId)}
                >
                  {scopePaperOptionMap.get(paperId)?.label ?? paperId}
                </button>
              ))}
              {scopePaperIds.length > 12 && <span className="kgTag">+{scopePaperIds.length - 12}</span>}
            </div>
          </div>
        ) : (
          <div className="text-faint" style={{ marginTop: 6, fontSize: 11 }}>
            {t('当前使用全图范围，没有显式 paper 节点过滤。', 'Using full-graph scope with no explicit paper filter.')}
          </div>
        )}
        <div className="kgRow" style={{ marginTop: 8 }}>
          <label className="sr-only" htmlFor="ask-scope-query">
            {t('搜索论文节点', 'Search paper nodes')}
          </label>
          <input
            id="ask-scope-query"
            name="ask_scope_query"
            className="kgInput kgFill"
            aria-label={t('搜索论文节点', 'Search paper nodes')}
            value={scopeQuery}
            onChange={(event) => {
              setScopeQuery(event.target.value)
              setScopeRenderLimit(SCOPE_LIST_PAGE_SIZE)
            }}
            placeholder={t('搜索论文节点（ID/标题）', 'Search paper nodes (ID/title)')}
          />
          <button
            className="kgBtn kgBtn--sm"
            type="button"
            disabled={scopePaperIds.length === 0}
            onClick={() => {
              setScopeShowSelectedOnly((value) => !value)
              setScopeRenderLimit(SCOPE_LIST_PAGE_SIZE)
            }}
          >
            {scopeShowSelectedOnly ? t('查看全部候选', 'Show All') : t('仅看已选', 'Selected Only')}
          </button>
          <button
            className="kgBtn kgBtn--sm"
            type="button"
            onClick={() => {
              saveScope({ mode: 'all' })
              setScopeShowSelectedOnly(false)
            }}
          >
            {t('切换全图', 'Use Full Graph')}
          </button>
        </div>
        {paperCatalogLoading && <div className="text-faint" style={{ marginTop: 6, fontSize: 11 }}>{t('正在加载论文节点...', 'Loading paper nodes...')}</div>}
        {!paperCatalogLoading && paperCatalogError && (
          <div style={{ marginTop: 6, fontSize: 11, color: 'var(--danger)' }}>{paperCatalogError}</div>
        )}
        <div className="kgAskScopeList">
          {filteredScopePaperOptions.length === 0 ? (
            <div className="text-faint" style={{ fontSize: 11 }}>{t('当前条件下没有可选论文节点。', 'No paper nodes match current filters.')}</div>
          ) : (
            scopePaperRenderState.visible.map((paper) => {
              const checked = scopePaperIdSet.has(paper.id)
              return (
                <label key={`ask-paper-opt-${paper.id}`} className={`kgAskScopeItem${checked ? ' is-active' : ''}`}>
                  <input type="checkbox" checked={checked} onChange={() => toggleScopePaper(paper.id)} />
                  <span className="kgFill truncate">{paper.label}</span>
                  {paper.year && <span className="kgTag">{paper.year}</span>}
                  <span className="kgTag">{paper.source}</span>
                </label>
              )
            })
          )}
        </div>
        {scopePaperRenderState.hasMore && (
          <div className="kgRow" style={{ marginTop: 8, justifyContent: 'center' }}>
            <button
              className="kgBtn kgBtn--sm"
              type="button"
              onClick={() => setScopeRenderLimit((prev) => prev + SCOPE_LIST_PAGE_SIZE)}
            >
              {t(`加载更多（剩余 ${scopePaperRenderState.remaining}）`, `Load more (${scopePaperRenderState.remaining} left)`)}
            </button>
          </div>
        )}
      </details>
    </div>
  )
}
