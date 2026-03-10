// frontend/src/components/StatusBar.tsx
import { useI18n } from '../i18n'
import { useGlobalState } from '../state/store'

const MODULE_LABELS: Record<string, { zh: string; en: string }> = {
  overview: { zh: '全局总览', en: 'Global Overview' },
  papers: { zh: '论文引文网络', en: 'Paper Citation Network' },
  ask: { zh: '图谱增强问答', en: 'GraphRAG QA' },
  evolution: { zh: '命题演化', en: 'Proposition Evolution' },
  textbooks: { zh: '教材知识图谱', en: 'Textbook Knowledge Graph' },
  ops: { zh: '运维工作台', en: 'Ops Workbench' },
}

export default function StatusBar() {
  const { state } = useGlobalState()
  const { t } = useI18n()
  const { activeModule, graphElements, transitioning } = state

  const nodeCount = graphElements.filter((e) => e.group === 'nodes').length
  const edgeCount = graphElements.filter((e) => e.group === 'edges').length
  const moduleText = MODULE_LABELS[activeModule] ? t(MODULE_LABELS[activeModule].zh, MODULE_LABELS[activeModule].en) : activeModule

  return (
    <footer className="kgStatusBar">
      <div className="kgStatusItem">
        <span>{t('模块', 'Module')}</span>
        <b>{moduleText}</b>
      </div>
      <div className="kgStatusDivider" />
      <div className="kgStatusItem">
        <span>{t('节点', 'Nodes')}</span>
        <b>{nodeCount}</b>
      </div>
      <div className="kgStatusItem">
        <span>{t('关系', 'Edges')}</span>
        <b>{edgeCount}</b>
      </div>
      {transitioning && (
        <>
          <div className="kgStatusDivider" />
          <div className="kgStatusItem" style={{ color: 'var(--accent)' }}>
            <span>{t('正在切换模块...', 'Switching Module...')}</span>
          </div>
        </>
      )}
    </footer>
  )
}
