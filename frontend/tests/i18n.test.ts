import { describe, expect, test } from 'vitest'

import { LOCALE_STORAGE_KEY, normalizeLocale, resolveInitialLocale, translate } from '../src/i18n'

describe('i18n helpers', () => {
  test('normalizeLocale accepts supported locale ids only', () => {
    expect(normalizeLocale('zh-CN')).toBe('zh-CN')
    expect(normalizeLocale('en-US')).toBe('en-US')
    expect(normalizeLocale('zh')).toBe('zh-CN')
    expect(normalizeLocale('en')).toBe('en-US')
    expect(normalizeLocale('fr-FR')).toBeNull()
    expect(normalizeLocale('')).toBeNull()
  })

  test('resolveInitialLocale prefers stored locale, then browser language, then zh-CN', () => {
    expect(resolveInitialLocale('en-US', 'zh-CN')).toBe('en-US')
    expect(resolveInitialLocale('zh-CN', 'en-US')).toBe('zh-CN')
    expect(resolveInitialLocale('invalid', 'en-GB')).toBe('en-US')
    expect(resolveInitialLocale(null, 'zh-TW')).toBe('zh-CN')
    expect(resolveInitialLocale(undefined, undefined)).toBe('zh-CN')
  })

  test('translate returns locale-specific copy', () => {
    expect(translate('zh-CN', '导入中心', 'Import Center')).toBe('导入中心')
    expect(translate('en-US', '导入中心', 'Import Center')).toBe('Import Center')
  })

  test('storage key is stable for persisted locale settings', () => {
    expect(LOCALE_STORAGE_KEY).toBe('logickg.ui.locale.v1')
  })
})
