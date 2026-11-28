import { describe, expect, it } from 'vitest'
import { installPlatform } from './install'

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.1 Mobile/15E148 Safari/604.1'
const IPAD_DESKTOP_MODE = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.1 Safari/605.1.15'
const ANDROID = 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/131.0 Mobile Safari/537.36'

describe('installPlatform', () => {
  it('hides the button once the site already runs from the home screen', () => {
    expect(installPlatform(IPHONE, true, 5)).toBe('installed')
    expect(installPlatform(ANDROID, true, 5)).toBe('installed')
  })

  it('gives iPhone and iPad (which claims to be a Mac) the Share-sheet steps, since Safari has no install prompt', () => {
    expect(installPlatform(IPHONE, false, 5)).toBe('ios')
    expect(installPlatform(IPAD_DESKTOP_MODE, false, 5)).toBe('ios')
  })

  it('treats a real Mac and Android as browsers with their own menu or prompt', () => {
    expect(installPlatform(IPAD_DESKTOP_MODE, false, 0)).toBe('other')
    expect(installPlatform(ANDROID, false, 5)).toBe('other')
  })
})
