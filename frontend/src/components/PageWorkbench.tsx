// frontend/src/components/PageWorkbench.tsx
import { useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useI18n } from '../i18n'

interface Props {
  title: string
  children: ReactNode
}

export default function PageWorkbench({ title, children }: Props) {
  const nav = useNavigate()
  const { t } = useI18n()
  return (
    <div style={{
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--bg)',
      color: 'var(--text)',
      overflow: 'hidden',
    }}>
      {/* 顶条 */}
      <div style={{
        height: 48,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0 20px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-panel)',
        flexShrink: 0,
      }}>
        <button
          type="button"
          className="kgBtn kgBtn--sm"
          onClick={() => nav('/')}
        >
          {t('← 返回总览', '← Back to Overview')}
        </button>
        <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--accent)' }}>
          {title}
        </span>
      </div>
      {/* 内容区 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px 40px' }}>
        {children}
      </div>
    </div>
  )
}
