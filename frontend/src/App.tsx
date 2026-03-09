import { useState, useCallback, useEffect, useRef, type CSSProperties } from 'react'
import { BrowserRouter, Navigate, Routes, Route, useNavigate } from 'react-router-dom'
import { GlobalStateProvider, useGlobalState } from './state/store'
import TopBar from './components/TopBar'
import StatusBar from './components/StatusBar'
import LeftPanel from './components/LeftPanel'
import RightPanel from './components/RightPanel'
import GraphCanvas from './components/GraphCanvas'
import { resolveOverview3DPanelState, type OverviewMode } from './components/overview3dLayout'
import PaperDetailPage from './pages/PaperDetailPage'
import TextbookDetailPage from './pages/TextbookDetailPage'
import PageWorkbench from './components/PageWorkbench'
import FusionPage from './pages/FusionPage'
import OpsWorkbench from './pages/OpsWorkbench'
import IngestPage from './pages/IngestPage'
import DiscoveryPage from './pages/DiscoveryPage'
import { I18nProvider, useI18n } from './i18n'
import type { ModuleId, SelectedNode } from './state/types'
import './components/layout.css'

type WorkspacePreset = 'focus' | 'balanced' | 'analysis'
type OverviewGraphMode = OverviewMode

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function shortText(value: string, max = 30) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  if (!text || text.length <= max) return text
  return `${text.slice(0, Math.max(1, max - 3))}...`
}

function Shell() {
  const { state, dispatch } = useGlobalState()
  const { t } = useI18n()
  const { activeModule, graphElements, graphLayout, layoutTrigger, transitioning, selectedNode } = state
  const nav = useNavigate()

  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [workspacePreset, setWorkspacePreset] = useState<WorkspacePreset>('balanced')
  const [overviewGraphMode, setOverviewGraphMode] = useState<OverviewGraphMode>('3d')
  const [leftDrawerOpen, setLeftDrawerOpen] = useState(false)
  const [rightDrawerOpen, setRightDrawerOpen] = useState(false)
  const [leftWidth, setLeftWidth] = useState(300)
  const [rightWidth, setRightWidth] = useState(340)
  const [resizing, setResizing] = useState<null | 'left' | 'right'>(null)
  const panelState = resolveOverview3DPanelState({
    activeModule,
    overviewMode: overviewGraphMode,
    hasGraphData: graphElements.length > 0,
    leftCollapsed,
    rightCollapsed,
    leftDrawerOpen,
    rightDrawerOpen,
  })
  const floatingPanelMode = panelState.immersive
  const layoutLeftCollapsed = panelState.layoutLeftCollapsed
  const layoutRightCollapsed = panelState.layoutRightCollapsed
  const leftPanelCollapsed = panelState.leftPanelCollapsed
  const rightPanelCollapsed = panelState.rightPanelCollapsed

  const handleSelectNode = useCallback(
    (node: SelectedNode | null) => {
      dispatch({ type: 'SET_SELECTED', node })
      if (!node) return
      if (floatingPanelMode) {
        setRightDrawerOpen(true)
        return
      }
      if (rightCollapsed) setRightCollapsed(false)
    },
    [dispatch, floatingPanelMode, rightCollapsed],
  )

  const toggleLeftPanel = useCallback(() => {
    if (floatingPanelMode) {
      setLeftDrawerOpen((value) => !value)
      return
    }
    setLeftCollapsed((value) => !value)
  }, [floatingPanelMode])

  const toggleRightPanel = useCallback(() => {
    if (floatingPanelMode) {
      setRightDrawerOpen((value) => !value)
      return
    }
    setRightCollapsed((value) => !value)
  }, [floatingPanelMode])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (workspacePreset === 'focus') {
        setLeftCollapsed(true)
        setRightCollapsed(true)
        return
      }
      if (workspacePreset === 'analysis') {
        setLeftCollapsed(false)
        setRightCollapsed(false)
        setLeftWidth(320)
        setRightWidth(430)
        return
      }
      setLeftCollapsed(false)
      setRightCollapsed(false)
      setLeftWidth(300)
      setRightWidth(340)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [workspacePreset])

  useEffect(() => {
    if (!resizing) return

    const handleMove = (evt: MouseEvent) => {
      if (resizing === 'left') {
        setLeftWidth(clamp(evt.clientX - 8, 240, 620))
      } else {
        setRightWidth(clamp(window.innerWidth - evt.clientX - 8, 280, 620))
      }
    }
    const handleUp = () => setResizing(null)

    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
    return () => {
      document.body.style.userSelect = ''
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }
  }, [resizing])

  useEffect(() => {
    if (activeModule !== 'ask') return
    const timer = window.setTimeout(() => {
      if (workspacePreset === 'focus') setWorkspacePreset('balanced')
      setLeftCollapsed(false)
      setRightCollapsed(false)
      setLeftWidth((value) => Math.max(value, 500))
      setRightWidth((value) => Math.max(value, 500))
    }, 0)
    return () => window.clearTimeout(timer)
  }, [activeModule, workspacePreset])

  useEffect(() => {
    if (activeModule !== 'overview' && overviewGraphMode !== '2d') {
      setOverviewGraphMode('2d')
    }
  }, [activeModule, overviewGraphMode])

  useEffect(() => {
    if (floatingPanelMode) return
    if (leftDrawerOpen) setLeftDrawerOpen(false)
    if (rightDrawerOpen) setRightDrawerOpen(false)
  }, [floatingPanelMode, leftDrawerOpen, rightDrawerOpen])

  const frameStyle = {
    '--left-panel-w': `${leftWidth}px`,
    '--right-panel-w': `${rightWidth}px`,
  } as CSSProperties

  const frameClass = [
    'kgFrame',
    activeModule === 'ask' ? 'is-ask-mode' : '',
    layoutLeftCollapsed ? 'left-collapsed' : '',
    layoutRightCollapsed ? 'right-collapsed' : '',
    floatingPanelMode ? 'is-floating-panel-mode' : '',
    resizing ? 'is-resizing' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="kgShell">
      <TopBar />
      <div className="kgWorkBar">
        <div className="kgWorkBarPrimary">
          <button className="kgBtn kgBtn--sm kgBtn--primary" onClick={() => nav('/ingest')}>
            {t('导入中心', 'Import Center')}
          </button>
          <button className="kgBtn kgBtn--sm" onClick={() => nav('/discovery')}>
            {t('科学发现', 'Discovery')}
          </button>
          <button className="kgBtn kgBtn--sm" onClick={() => dispatch({ type: 'RELAYOUT' })}>
            {t('重新布局', 'Re-layout')}
          </button>
        </div>
        <div className="kgWorkBarSecondary">
          <div className="kgPresetWrap">
            <button
              className={`kgBtn kgBtn--sm${workspacePreset === 'focus' ? ' kgBtn--primary' : ''}`}
              onClick={() => setWorkspacePreset('focus')}
            >
              {t('专注', 'Focus')}
            </button>
            <button
              className={`kgBtn kgBtn--sm${workspacePreset === 'balanced' ? ' kgBtn--primary' : ''}`}
              onClick={() => setWorkspacePreset('balanced')}
            >
              {t('均衡', 'Balanced')}
            </button>
            <button
              className={`kgBtn kgBtn--sm${workspacePreset === 'analysis' ? ' kgBtn--primary' : ''}`}
              onClick={() => setWorkspacePreset('analysis')}
            >
              {t('分析', 'Analysis')}
            </button>
          </div>
          <div className="kgWorkHint">
            {selectedNode
              ? t(`当前节点: ${shortText(selectedNode.label)}`, `Current Node: ${shortText(selectedNode.label)}`)
              : t('未选中节点', 'No Node Selected')}
          </div>
        </div>
      </div>

      <div className={frameClass} style={frameStyle}>
        <LeftPanel collapsed={leftPanelCollapsed} floating={floatingPanelMode} onToggle={toggleLeftPanel} />
        <div
          className={`kgResize kgResize--left${layoutLeftCollapsed ? ' is-hidden' : ''}`}
          onMouseDown={() => {
            if (!layoutLeftCollapsed) setResizing('left')
          }}
          title={t('拖动调整左侧面板宽度', 'Drag to resize left panel')}
        />
        <GraphCanvas
          elements={graphElements}
          layout={graphLayout}
          layoutTrigger={layoutTrigger}
          overviewMode={overviewGraphMode}
          onOverviewModeChange={setOverviewGraphMode}
          transitioning={transitioning}
          onSelectNode={handleSelectNode}
        />
        <div
          className={`kgResize kgResize--right${layoutRightCollapsed ? ' is-hidden' : ''}`}
          onMouseDown={() => {
            if (!layoutRightCollapsed) setResizing('right')
          }}
          title={t('拖动调整右侧面板宽度', 'Drag to resize right panel')}
        />
        <RightPanel collapsed={rightPanelCollapsed} floating={floatingPanelMode} onToggle={toggleRightPanel} />
      </div>
      <StatusBar />
    </div>
  )
}

function ShellRoute({ module }: { module?: ModuleId }) {
  const { state, switchModule } = useGlobalState()
  const initializedRef = useRef(false)

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    if (module && state.activeModule !== module) switchModule(module)
  }, [module, state.activeModule, switchModule])

  return <Shell />
}

function AppRoutes() {
  const { t } = useI18n()
  return (
    <Routes>
      <Route
        path="/ask"
        element={<ShellRoute module="ask" />}
      />
      <Route path="/ask/workbench" element={<Navigate to="/ask" replace />} />
      <Route
        path="/fusion"
        element={
          <PageWorkbench title={t('跨源融合', 'Cross-source Fusion')}>
            <FusionPage />
          </PageWorkbench>
        }
      />
      <Route
        path="/ops"
        element={
          <PageWorkbench title={t('运维工作台', 'Operations Workbench')}>
            <OpsWorkbench />
          </PageWorkbench>
        }
      />
      <Route
        path="/ingest"
        element={
          <PageWorkbench title={t('导入中心', 'Import Center')}>
            <IngestPage />
          </PageWorkbench>
        }
      />
      <Route
        path="/discovery"
        element={
          <PageWorkbench title={t('科学问题发现', 'Scientific Discovery')}>
            <DiscoveryPage />
          </PageWorkbench>
        }
      />
      <Route path="/paper/:paperId" element={<PaperDetailWrapper />} />
      <Route path="/textbooks/:textbookId" element={<TextbookDetailWrapper />} />
      <Route path="*" element={<ShellRoute />} />
    </Routes>
  )
}

function PaperDetailWrapper() {
  const nav = useNavigate()
  const { t } = useI18n()
  return (
    <div style={{ height: '100vh', overflow: 'auto', background: 'var(--bg)', color: 'var(--text)', padding: 20 }}>
      <button className="kgBtn kgBtn--sm" onClick={() => nav(-1)} style={{ marginBottom: 16 }}>
        {t('返回图谱', 'Back to Graph')}
      </button>
      <PaperDetailPage />
    </div>
  )
}

function TextbookDetailWrapper() {
  const nav = useNavigate()
  const { t } = useI18n()
  return (
    <div style={{ height: '100vh', overflow: 'auto', background: 'var(--bg)', color: 'var(--text)', padding: 20 }}>
      <button className="kgBtn kgBtn--sm" onClick={() => nav(-1)} style={{ marginBottom: 16 }}>
        {t('返回图谱', 'Back to Graph')}
      </button>
      <TextbookDetailPage />
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <I18nProvider>
        <GlobalStateProvider>
          <AppRoutes />
        </GlobalStateProvider>
      </I18nProvider>
    </BrowserRouter>
  )
}

