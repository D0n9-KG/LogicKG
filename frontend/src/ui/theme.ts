export type UiTheme = 'research' | 'executive'

export const UI_THEME_STORAGE_KEY = 'logickg.ui.theme'

export function normalizeUiTheme(value: unknown): UiTheme {
  return value === 'executive' ? 'executive' : 'research'
}
