import { describe, expect, it } from 'vitest'
import { THEME_STORAGE_KEY, themeInitScript } from './theme'

function run(stored: string | null | 'throws', systemDark: boolean) {
  const documentElement = { dataset: {} as Record<string, string> }
  const localStorage = {
    getItem(key: string) {
      expect(key).toBe(THEME_STORAGE_KEY)
      if (stored === 'throws') throw new Error('blocked')
      return stored
    },
  }
  const matchMedia = () => ({ matches: systemDark })
  new Function('localStorage', 'matchMedia', 'document', themeInitScript)(localStorage, matchMedia, { documentElement })
  return documentElement.dataset.theme
}

describe('themeInitScript', () => {
  it('follows the device setting until the visitor chooses', () => {
    expect(run(null, true)).toBe('dark')
    expect(run(null, false)).toBe('light')
  })

  it('keeps the visitor choice over the device setting', () => {
    expect(run('light', true)).toBe('light')
    expect(run('dark', false)).toBe('dark')
  })

  it('falls back to the device setting when storage is blocked or holds junk', () => {
    expect(run('throws', true)).toBe('dark')
    expect(run('purple', true)).toBe('dark')
  })
})
