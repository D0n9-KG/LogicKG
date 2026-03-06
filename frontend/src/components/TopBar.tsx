import { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { apiGet } from '../api'
import { useI18n } from '../i18n'
import { useGlobalState } from '../state/store'
import type { ModuleId } from '../state/types'

type LocalizedText = {
  zh: string
  en: string
}

type ModuleNavItem = {
  id: string
  label: LocalizedText
  note: LocalizedText
  moduleId?: ModuleId
  href?: string
}

const MODULES: ModuleNavItem[] = [
  { id: 'overview', moduleId: 'overview', label: { zh: '总览', en: 'Overview' }, note: { zh: '全局知识图谱', en: 'Global KG' } },
  { id: 'papers', moduleId: 'papers', label: { zh: '论文', en: 'Papers' }, note: { zh: '引用网络', en: 'Citation Net' } },
  { id: 'ask', moduleId: 'ask', label: { zh: '问答', en: 'Ask' }, note: { zh: '图谱增强问答', en: 'GraphRAG' } },
  { id: 'textbooks', moduleId: 'textbooks', label: { zh: '教材', en: 'Textbooks' }, note: { zh: '知识结构', en: 'Knowledge Base' } },
  { id: 'fusion', label: { zh: '融合', en: 'Fusion' }, note: { zh: '跨源关联', en: 'Cross-source' }, href: '/fusion' },
  { id: 'discovery', label: { zh: '发现', en: 'Discovery' }, note: { zh: '问题挖掘', en: 'Question Mining' }, href: '/discovery' },
  { id: 'ops', label: { zh: '运维', en: 'Ops' }, note: { zh: '任务与配置', en: 'Tasks & Config' }, href: '/ops' },
]

type ApiStatus = 'checking' | 'ok' | 'error'

export default function TopBar() {
  const { state, switchModule } = useGlobalState()
  const { locale, setLocale, t } = useI18n()
  const { activeModule, graphElements } = state
  const nav = useNavigate()
  const location = useLocation()

  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking')

  useEffect(() => {
    let cancelled = false

    async function check() {
      try {
        await apiGet<unknown>('/health')
        if (!cancelled) setApiStatus('ok')
      } catch {
        if (!cancelled) setApiStatus('error')
      }
    }

    void check()
    const interval = setInterval(() => void check(), 30_000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const nodeCount = graphElements.filter((e) => e.group === 'nodes').length
  const edgeCount = graphElements.filter((e) => e.group === 'edges').length

  function isActive(m: ModuleNavItem): boolean {
    if (m.href) return location.pathname === m.href || location.pathname.startsWith(`${m.href}/`)
    return activeModule === m.moduleId
  }

  function handleClick(m: ModuleNavItem) {
    if (m.href) {
      nav(m.href)
      return
    }

    if (m.moduleId) {
      if (location.pathname !== '/') nav('/')
      if (activeModule !== m.moduleId) switchModule(m.moduleId)
    }
  }

  return (
    <header className="kgTopBar">
      <a
        className="kgBrand"
        href="/"
        onClick={(e) => {
          e.preventDefault()
          nav('/')
          if (activeModule !== 'overview') switchModule('overview')
        }}
      >
        <div className="kgBrandMark">KG</div>
        <div>
          <span className="kgBrandName">LogicKG</span>
          <small className="kgBrandSub">{t('科研知识中枢', 'Research Brain')}</small>
        </div>
      </a>

      <nav className="kgModuleNav" aria-label={t('模块导航', 'Module Navigation')}>
        {MODULES.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`kgModuleBtn${isActive(m) ? ' is-active' : ''}`}
            onClick={() => handleClick(m)}
          >
            <span>{t(m.label.zh, m.label.en)}</span>
            <small>{t(m.note.zh, m.note.en)}</small>
          </button>
        ))}
      </nav>

      <div className="kgTopBarRight">
        <div
          role="group"
          aria-label={t('界面语言', 'Interface Language')}
          style={{ display: 'inline-flex', gap: 4, padding: 2, border: '1px solid var(--border)', borderRadius: 999 }}
        >
          <button
            type="button"
            className="kgBtn kgBtn--sm"
            style={{ padding: '2px 8px', minWidth: 36, opacity: locale === 'zh-CN' ? 1 : 0.7 }}
            onClick={() => setLocale('zh-CN')}
            title={t('切换到中文界面', 'Switch to Chinese')}
          >
            中
          </button>
          <button
            type="button"
            className="kgBtn kgBtn--sm"
            style={{ padding: '2px 8px', minWidth: 36, opacity: locale === 'en-US' ? 1 : 0.7 }}
            onClick={() => setLocale('en-US')}
            title={t('切换到英文界面', 'Switch to English')}
          >
            EN
          </button>
        </div>
        <span style={{ fontSize: 10, color: 'var(--faint)', fontFamily: 'var(--font-mono)' }}>
          {nodeCount}N | {edgeCount}E
        </span>
        <div
          className={`kgApiDot${apiStatus === 'error' ? ' is-error' : apiStatus === 'checking' ? ' is-checking' : ''}`}
          title={`${t('接口状态', 'API Status')}: ${apiStatus}`}
        />
      </div>
    </header>
  )
}
