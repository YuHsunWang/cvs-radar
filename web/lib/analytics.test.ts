import { describe, expect, it } from 'vitest'
import { hasUnfinishedZhuyin } from './analytics'

describe('hasUnfinishedZhuyin', () => {
  // Real search_no_result terms from GA4 (2026-10-29): half-typed IME text.
  it('flags text still being composed', () => {
    for (const q of ['ㄅ', 'ㄩˋ', 'ㄕㄨㄤˉ ㄖㄨ', '檸檬白ㄐㄧㄤ']) expect(hasUnfinishedZhuyin(q)).toBe(true)
  })

  // Finished queries must still be tracked, or the content-gap report goes blind.
  it('keeps finished queries', () => {
    for (const q of ['檸檬白醬', '益活', 'Iselc', '7-11 飯糰']) expect(hasUnfinishedZhuyin(q)).toBe(false)
  })
})
