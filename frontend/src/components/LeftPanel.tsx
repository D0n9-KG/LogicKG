import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { useI18n } from '../i18n'
import { useGlobalState } from '../state/store'

const OverviewPanel = lazy(() => import('../panels/OverviewPanel'))
const PapersPanel = lazy(() => import('../panels/PapersPanel'))
const AskPanel = lazy(() => import('../panels/AskPanel'))
const TextbooksPanel = lazy(() => import('../panels/TextbooksPanel'))
const OpsPanel = lazy(() => import('../panels/OpsPanel'))

const PANEL_ICONS: Record<string, string> = {
  overview: 'O',
  papers: 'P',
  ask: 'Q',
  textbooks: 'T',
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
        <div className="kgPanelIcon" onClick={onToggle} title={t('灞曞紑宸︿晶闈㈡澘', 'Expand Left Panel')}>
          <button className="kgPanelIconBtn" type="button">
            O
          </button>
          <button className="kgPanelIconBtn" type="button">
            {PANEL_ICONS[activeModule] ?? 'M'}
          </button>
        </div>
        <div aria-hidden="true" style={{ display: 'none' }}>
          <Suspense fallback={null}>{renderContent()}</Suspense>
        </div>
      </aside>
    )
  }

  function renderContent() {
    if (activeModule === 'overview') return <OverviewPanel />
    if (activeModule === 'papers') return <PapersPanel />
    if (activeModule === 'ask') return <AskPanel />
    if (activeModule === 'textbooks') return <TextbooksPanel />
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
        <button className="kgPanelCollapseBtn" type="button" onClick={onToggle} title={t('鏀惰捣', 'Collapse')}>
          {'<'}
        </button>
      </div>
      <div className={`kgPanelContent${transitioning ? ' is-transitioning' : ''}`}>
        <Suspense fallback={<PanelFallback label={activeModule.toUpperCase()} message={t('姝ｅ湪鍔犺浇妯″潡...', 'Loading module...')} />}>
          {renderContent()}
        </Suspense>
      </div>
    </aside>
  )
}

function PanelFallback({ label, message }: { label: string; message: string }) {
  return (
    <div className="kgPanelBody kgStack" aria-busy="true">
      <div className="kgCard">
        <div className="kgCardTitle">{label}</div>
        <div className="text-faint" style={{ fontSize: 11 }}>
          {message}
        </div>
      </div>
    </div>
  )
}
