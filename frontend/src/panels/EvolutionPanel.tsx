// frontend/src/panels/EvolutionPanel.tsx
import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../api'
import { useI18n } from '../i18n'
import { useGlobalState } from '../state/store'
import { loadEvolutionGraph, expandEvolutionGroup } from '../loaders/evolution'

type Group = { group_id: string; label_text: string; proposition_count: number }

export default function EvolutionPanel() {
  const { state, dispatch } = useGlobalState()
  const { t } = useI18n()
  const { evolution } = state
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(false)
  const selectReqRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    const startTimer = window.setTimeout(() => setLoading(true), 0)
    Promise.all([
      apiGet<{ groups: Group[] }>('/evolution/groups?limit=50'),
      loadEvolutionGraph(50),
    ])
      .then(([res, els]) => {
        if (cancelled) return
        setGroups(res.groups ?? [])
        dispatch({ type: 'SET_GRAPH', elements: els, layout: 'cose' })
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) { setLoading(false); dispatch({ type: 'SET_TRANSITIONING', value: false }) } })
    return () => {
      cancelled = true
      window.clearTimeout(startTimer)
    }
  }, [dispatch])

  function selectGroup(groupId: string) {
    dispatch({ type: 'EVOLUTION_SELECT_GROUP', groupId })
    dispatch({ type: 'SET_TRANSITIONING', value: true })
    selectReqRef.current = groupId
    expandEvolutionGroup(groupId)
      .then((els) => {
        if (selectReqRef.current !== groupId) return
        dispatch({ type: 'MERGE_GRAPH', elements: els })
      })
      .catch(() => {})
      .finally(() => {
        if (selectReqRef.current === groupId) dispatch({ type: 'SET_TRANSITIONING', value: false })
      })
  }

  const filtered = evolution.searchQuery
    ? groups.filter((g) => g.label_text.toLowerCase().includes(evolution.searchQuery.toLowerCase()))
    : groups

  return (
    <div className="kgPanelBody kgStack">
      <input
        className="kgInput"
        placeholder={t('搜索命题群组...', 'Search proposition groups...')}
        value={evolution.searchQuery}
        onChange={(e) => dispatch({ type: 'EVOLUTION_SEARCH', query: e.target.value })}
      />
      {loading && <div className="text-faint" style={{ fontSize: 11 }}>{t('加载中...', 'Loading...')}</div>}
      <div className="kgStack" style={{ gap: 4 }}>
        {filtered.slice(0, 50).map((g) => (
          <div
            key={g.group_id}
            className={`kgListItem${evolution.selectedGroupId === g.group_id ? ' is-active' : ''}`}
            onClick={() => selectGroup(g.group_id)}
          >
            <div className="kgListItemTitle truncate">{g.label_text || g.group_id}</div>
            <div className="kgListItemMeta">{t(`${g.proposition_count} 个命题`, `${g.proposition_count} propositions`)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
