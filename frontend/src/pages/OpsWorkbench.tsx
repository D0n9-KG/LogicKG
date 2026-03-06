import { useState } from 'react'

import { useI18n } from '../i18n'
import ConfigCenterPage from './ConfigCenterPage'
import TasksPage from './TasksPage'
import UnresolvedPage from './UnresolvedPage'

type Tab = 'tasks' | 'config' | 'unresolved'

const TABS: Array<{ id: Tab; zh: { label: string; desc: string }; en: { label: string; desc: string } }> = [
  {
    id: 'tasks',
    zh: { label: '任务队列', desc: '后端任务、进度追踪与重建入口。' },
    en: { label: 'Task Queue', desc: 'Backend jobs, progress tracking, and rebuild actions.' },
  },
  {
    id: 'config',
    zh: { label: '配置中心', desc: '集中管理参数、抽取策略与调优助手。' },
    en: { label: 'Config Center', desc: 'Centralized parameters, extraction policy, and tuning assistant.' },
  },
  {
    id: 'unresolved',
    zh: { label: '未解析引用', desc: '参考文献补全队列与 CrossRef 解析状态。' },
    en: { label: 'Unresolved Cites', desc: 'Reference recovery queue and CrossRef resolution status.' },
  },
]

export default function OpsWorkbench() {
  const { t } = useI18n()
  const [active, setActive] = useState<Tab>('tasks')

  return (
    <div>
      <div className="cc-top-tabs" role="tablist" aria-label={t('运维分区', 'Ops Sections')}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active === tab.id}
            className={`cc-top-tab${active === tab.id ? ' is-active' : ''}`}
            onClick={() => setActive(tab.id)}
            title={t(tab.zh.desc, tab.en.desc)}
          >
            {t(tab.zh.label, tab.en.label)}
          </button>
        ))}
      </div>

      {active === 'tasks' && <TasksPage />}
      {active === 'config' && <ConfigCenterPage />}
      {active === 'unresolved' && <UnresolvedPage />}
    </div>
  )
}
