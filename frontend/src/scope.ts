export type ScopeMode = 'all' | 'collection' | 'papers'
export type ScopeLabelLocale = 'zh-CN' | 'en-US'

export type Scope = {
  mode: ScopeMode
  collectionId?: string
  paperIds?: string[]
}

const LS_KEY = 'logickg.scope.v1'

export function emitScopeChanged() {
  window.dispatchEvent(new Event('logickg:scope_changed'))
}

export function loadScope(): Scope {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) throw new Error('empty')
    const d = JSON.parse(raw) as Partial<Scope>
    const mode = (d.mode ?? 'all') as ScopeMode
    const collectionId = typeof d.collectionId === 'string' ? d.collectionId : undefined
    const paperIds = Array.isArray(d.paperIds) ? d.paperIds.map(String).filter(Boolean) : undefined
    if (mode === 'collection') return { mode, collectionId: collectionId ?? '' }
    if (mode === 'papers') return { mode, paperIds: paperIds ?? [] }
    return { mode: 'all' }
  } catch {
    return { mode: 'all' }
  }
}

export function saveScope(scope: Scope) {
  const s: Scope =
    scope.mode === 'collection'
      ? { mode: 'collection', collectionId: String(scope.collectionId ?? '') }
      : scope.mode === 'papers'
        ? { mode: 'papers', paperIds: (scope.paperIds ?? []).map(String).filter(Boolean) }
        : { mode: 'all' }
  localStorage.setItem(LS_KEY, JSON.stringify(s))
  emitScopeChanged()
}

export function scopeFromUrl(sp: URLSearchParams): Scope | null {
  const mode = String(sp.get('scope') ?? '').trim()
  if (!mode) return null
  if (mode === 'all') return { mode: 'all' }
  if (mode === 'collection') return { mode: 'collection', collectionId: String(sp.get('cid') ?? '') }
  if (mode === 'papers') {
    const raw = String(sp.get('pids') ?? '')
    const paperIds = raw
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean)
    return { mode: 'papers', paperIds }
  }
  return null
}

export function applyScopeToUrl(sp: URLSearchParams, scope: Scope): URLSearchParams {
  const next = new URLSearchParams(sp)
  next.delete('scope')
  next.delete('cid')
  next.delete('pids')
  if (scope.mode === 'all') {
    next.set('scope', 'all')
  } else if (scope.mode === 'collection') {
    next.set('scope', 'collection')
    if (scope.collectionId) next.set('cid', scope.collectionId)
  } else if (scope.mode === 'papers') {
    next.set('scope', 'papers')
    const pids = (scope.paperIds ?? []).map(String).filter(Boolean)
    if (pids.length) next.set('pids', pids.join(','))
  }
  return next
}

export function scopeLabel(scope: Scope, locale: ScopeLabelLocale = 'zh-CN'): string {
  if (locale === 'en-US') {
    if (scope.mode === 'all') return 'All Papers'
    if (scope.mode === 'collection') return `Collection: ${scope.collectionId ?? ''}`
    return `Selected Papers: ${(scope.paperIds ?? []).length}`
  }
  if (scope.mode === 'all') return '全部论文'
  if (scope.mode === 'collection') return `论文集: ${scope.collectionId ?? ''}`
  return `已选论文: ${(scope.paperIds ?? []).length}`
}
