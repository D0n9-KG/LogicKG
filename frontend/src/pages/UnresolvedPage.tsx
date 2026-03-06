import { useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost } from '../api'
import { useI18n } from '../i18n'

type UnresolvedRow = {
  citing_paper_id: string
  citing_paper_source?: string
  ref_id: string
  raw: string
  crossref_json?: string
  total_mentions?: number
  ref_nums?: number[]
}

export default function UnresolvedPage() {
  const { t } = useI18n()
  const [rows, setRows] = useState<UnresolvedRow[]>([])
  const [error, setError] = useState<string>('')
  const [doiByRef, setDoiByRef] = useState<Record<string, string>>({})
  const [busyRef, setBusyRef] = useState<string>('')
  const [query, setQuery] = useState<string>('')

  async function refresh() {
    const r = await apiGet<{ unresolved: UnresolvedRow[] }>('/graph/unresolved?limit=300')
    setRows(r.unresolved ?? [])
  }

  useEffect(() => {
    refresh().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))
  }, [])

  async function resolve(refId: string) {
    const doi = (doiByRef[refId] ?? '').trim()
    if (!doi) return
    setBusyRef(refId)
    setError('')
    try {
      await apiPost<Record<string, unknown>>('/graph/resolve', { ref_id: refId, doi })
      await refresh()
    } catch (e: unknown) {
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    } finally {
      setBusyRef('')
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => `${r.raw} ${r.ref_id} ${r.citing_paper_source ?? ''}`.toLowerCase().includes(q))
  }, [query, rows])

  return (
    <div className="page">
      <div className="pageHeader">
        <div>
          <h2 className="pageTitle">{t('待解析', 'Unresolved')}</h2>
          <div className="pageSubtitle">{t('无法自动解析 DOI 的参考文献（可手动补 DOI 并写回图谱）', 'References whose DOI cannot be resolved automatically (manual DOI entry supported).')}</div>
        </div>
        <div className="pageActions">
          <span className="pill">
            <span className="kicker">{t('数量', 'Count')}</span> {filtered.length}
          </span>
          <input className="input" name="unresolved_search_query" style={{ width: 340, maxWidth: '70vw' }} value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('搜索…', 'Search...')} />
          <button className="btn" onClick={() => refresh().catch((e: unknown) => setError(String((e as { message?: unknown } | null)?.message ?? e)))}>
            {t('刷新', 'Refresh')}
          </button>
        </div>
      </div>

      {error && <div className="errorBox">{error}</div>}

      <div className="panel">
        <div className="panelHeader">
          <div className="panelTitle">{t('参考文献', 'References')}</div>
        </div>
        <div className="panelBody">
          <div className="list">
            {filtered.map((r) => (
              <div key={r.ref_id} className="itemCard">
                <div className="itemMeta">
                  {t(
                    `${r.citing_paper_source ?? r.citing_paper_id} · 引用次数 ${r.total_mentions ?? 0} · 引用编号 ${(r.ref_nums ?? []).join(', ')}`,
                    `${r.citing_paper_source ?? r.citing_paper_id} · Mentions ${r.total_mentions ?? 0} · Ref # ${(r.ref_nums ?? []).join(', ')}`,
                  )}
                </div>
                <div className="itemBody">{r.raw}</div>
                <details style={{ marginTop: 8 }}>
                  <summary style={{ cursor: 'pointer', color: 'rgba(255,255,255,0.72)' }}>{t('Crossref 候选', 'Crossref Candidates')}</summary>
                  <pre style={{ whiteSpace: 'pre-wrap', opacity: 0.85 }}>{r.crossref_json ?? ''}</pre>
                </details>
                <div className="row" style={{ marginTop: 10 }}>
                  <input
                    className="input"
                    name={`unresolved_doi_${r.ref_id}`}
                    placeholder={t('DOI（例如 10.xxxx/...）', 'DOI (for example 10.xxxx/...)')}
                    value={doiByRef[r.ref_id] ?? ''}
                    onChange={(e) => setDoiByRef({ ...doiByRef, [r.ref_id]: e.target.value })}
                  />
                  <button className="btn btnPrimary" disabled={busyRef === r.ref_id} onClick={() => resolve(r.ref_id)}>
                    {t('解析', 'Resolve')}
                  </button>
                </div>
              </div>
            ))}
          </div>
          {filtered.length === 0 && <div className="metaLine">{t('没有待解析的参考文献。', 'No unresolved references.')}</div>}
        </div>
      </div>
    </div>
  )
}
