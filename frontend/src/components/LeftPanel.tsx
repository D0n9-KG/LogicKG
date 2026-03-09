import { useState, useRef, useEffect } from 'react'
import { useI18n } from '../i18n'
import { useGlobalState } from '../state/store'
import OverviewPanel from '../panels/OverviewPanel'
import PapersPanel from '../panels/PapersPanel'
import AskPanel from '../panels/AskPanel'
import TextbooksPanel from '../panels/TextbooksPanel'
import OpsPanel from '../panels/OpsPanel'

const PANEL_ICONS: Record<string, string> = {
  overview: 'O',
  papers: 'P',
  ask: 'Q',
  textbooks: 'T',
  fusion: 'F',
  ops: 'S',
}

type Props = {
  collapsed: boolean
  floating?: boolean
  onToggle: () => void
}

export default function LeftPanel({ collapsed, floating = false, onToggle }: Props) {
  const { state } = useGlobalState()
  const { t } = useI18n()
  const { activeModule } = state
  const [transitioning, setTransitioning] = useState(false)
  const prevModuleRef = useRef(activeModule)

  useEffect(() => {
    if (prevModuleRef.current === activeModule) return
    prevModuleRef.current = activeModule
    let stopTimer = 0
    const startTimer = window.setTimeout(() => {
      setTransitioning(true)
      stopTimer = window.setTimeout(() => setTransitioning(false), 150)
    }, 0)
    return () => {
      window.clearTimeout(startTimer)
      if (stopTimer) window.clearTimeout(stopTimer)
    }
  }, [activeModule])

  if (collapsed) {
    return (
      <aside className="kgPanel kgPanel--left">
        <div className="kgPanelIcon" onClick={onToggle} title={t('展开左侧面板', 'Expand Left Panel')}>
          <button className="kgPanelIconBtn" type="button">
            O
          </button>
          <button className="kgPanelIconBtn" type="button">
            {PANEL_ICONS[activeModule] ?? 'M'}
          </button>
        </div>
        {floating ? (
          <div aria-hidden="true" style={{ display: 'none' }}>
            {renderContent()}
          </div>
        ) : null}
      </aside>
    )
  }

  function renderContent() {
    if (activeModule === 'overview') return <OverviewPanel />
    if (activeModule === 'papers') return <PapersPanel />
    if (activeModule === 'ask') return <AskPanel />
    if (activeModule === 'textbooks') return <TextbooksPanel />
    if (activeModule === 'fusion') {
      return (
        <div className="kgPanelBody">
          <p className="text-muted" style={{ fontSize: 11 }}>
            {t('融合模块控制面板（第二阶段）', 'Fusion Module Panel (Phase 2)')}
          </p>
        </div>
      )
    }
    if (activeModule === 'ops') return <OpsPanel />
    return null
  }

  const panelClass = ['kgPanel', 'kgPanel--left', floating ? 'kgPanel--floating kgPanel--floating-left' : '']
    .filter(Boolean)
    .join(' ')

  return (
    <aside className={panelClass}>
      <div className="kgPanelHeader">
        <span className="kgPanelTitle">
          {PANEL_ICONS[activeModule]} {activeModule.toUpperCase()}
        </span>
        <button className="kgPanelCollapseBtn" type="button" onClick={onToggle} title={t('收起', 'Collapse')}>
          {'<'}
        </button>
      </div>
      <div className={`kgPanelContent${transitioning ? ' is-transitioning' : ''}`}>{renderContent()}</div>
    </aside>
  )
}
