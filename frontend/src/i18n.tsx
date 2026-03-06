/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

export type UILocale = 'zh-CN' | 'en-US'

export const LOCALE_STORAGE_KEY = 'logickg.ui.locale.v1'

export function normalizeLocale(value: unknown): UILocale | null {
  const text = String(value ?? '').trim().toLowerCase()
  if (!text) return null
  if (text === 'zh' || text.startsWith('zh-')) return 'zh-CN'
  if (text === 'en' || text.startsWith('en-')) return 'en-US'
  return null
}

export function resolveInitialLocale(storedValue: unknown, browserLanguage?: unknown): UILocale {
  const storedLocale = normalizeLocale(storedValue)
  if (storedLocale) return storedLocale
  const browserLocale = normalizeLocale(browserLanguage)
  if (browserLocale) return browserLocale
  return 'zh-CN'
}

export function translate(locale: UILocale, zh: string, en: string): string {
  return locale === 'zh-CN' ? zh : en
}

type I18nContextValue = {
  locale: UILocale
  setLocale: (locale: UILocale) => void
  toggleLocale: () => void
  t: (zh: string, en: string) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function readStoredLocale(): UILocale | null {
  if (typeof window === 'undefined') return null
  try {
    return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY))
  } catch {
    return null
  }
}

function readBrowserLocale(): UILocale | null {
  if (typeof window === 'undefined') return null
  return normalizeLocale(window.navigator.language)
}

function persistLocale(locale: UILocale) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  } catch {
    // Ignore browser storage errors in private mode.
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<UILocale>(() => resolveInitialLocale(readStoredLocale(), readBrowserLocale()))

  const value = useMemo<I18nContextValue>(() => {
    const setLocale = (next: UILocale) => {
      setLocaleState(next)
      persistLocale(next)
    }

    const toggleLocale = () => {
      const next = locale === 'zh-CN' ? 'en-US' : 'zh-CN'
      setLocale(next)
    }

    return {
      locale,
      setLocale,
      toggleLocale,
      t: (zh: string, en: string) => translate(locale, zh, en),
    }
  }, [locale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside I18nProvider')
  return ctx
}
