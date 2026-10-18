import { describe, expect, it } from 'vitest'
import { DEFAULT_SORT, readViewParams, viewSearch } from './view-url'

describe('shareable shelf links', () => {
  it('round-trips a filtered view with a Chinese product id', () => {
    // Product ids look like 「7-11::麻油雞飯糰」; a link pasted on PTT must reopen that exact card.
    const state = {
      query: '布丁', brand: '全家', category: '甜點' as const, datePreset: '1m',
      sortKey: 'comprehensiveDesc' as const, hideNoScore: true, product: '7-11::麻油雞飯糰',
    }
    expect(readViewParams(viewSearch(state))).toEqual(state)
  })

  it('keeps a plain visit at a bare URL', () => {
    // Defaults stay out of the query string so the canonical page is not split into variants.
    expect(viewSearch(readViewParams(''))).toBe('')
    expect(readViewParams('').sortKey).toBe(DEFAULT_SORT)
  })

  it('opens on recent recommendation, not raw score', () => {
    // Raw score puts one-review 100s first; the user ruled 1–3 reviewers cannot carry a top score.
    // Discussion heat was tried and opened on 25- and 13-point products, so it is not the default either.
    expect(DEFAULT_SORT).toBe('recentRecommendationDesc')
  })

  it('ignores values the shelf does not offer', () => {
    const state = readViewParams('?brand=Costco&cat=火鍋&sort=random&date=9y')
    expect(state.brand).toBeNull()
    expect(state.category).toBeNull()
    expect(state.sortKey).toBe(DEFAULT_SORT)
    expect(state.datePreset).toBe('all')
  })
})
