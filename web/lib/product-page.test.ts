import { describe, expect, it } from 'vitest'
import type { Product } from './data'
import { pageProducts, productPagePath, productPageTitle, productSlug, relatedProducts } from './product-page'

function product(overrides: Partial<Product>): Product {
  return {
    id: 'x', brand: '全家', productName: '布丁', price: 45, category: '甜點',
    fairScore: 80, recommendationScore: 80, consensus: '一致好評', confidence: '中',
    nPosts: 1, nComments: 5, rawComments: 5, eligibleComments: 5, uniqueEligibleCommenters: 5,
    independentThreads: 1, volumeLevel: '中等', positivePct: 80, neutralPct: 10, negativePct: 10,
    likes: [], cautions: [], excerpt: '', reviewProvisional: false, postUrls: [], latestDate: null,
    kcal: null, nutrition: null, image: null, vegetarian: null,
    ...overrides,
  }
}

describe('productSlug', () => {
  it('keeps the Chinese name readable so the search result shows what the page is', () => {
    expect(productSlug(product({ brand: '全家', productName: '生巧風味餅乾夾心' }))).toBe('全家-生巧風味餅乾夾心')
  })

  it('turns characters that break a URL or a file path into one hyphen', () => {
    // A raw % would be read as an escape; a / would make a nested directory.
    expect(productSlug(product({ brand: '7-11', productName: '70% 黑巧/杏仁' }))).toBe('7-11-70-黑巧-杏仁')
  })
})

describe('pageProducts', () => {
  it('skips products with too few comments to make a page worth indexing', () => {
    const thin = product({ id: 'thin', productName: '冷門', eligibleComments: 2 })
    const enough = product({ id: 'ok', productName: '熱門', eligibleComments: 3 })
    expect(pageProducts([thin, enough]).map((p) => p.id)).toEqual(['ok'])
  })

  it('gives no page to two products that would share a URL, rather than letting one overwrite the other', () => {
    const a = product({ id: 'a', productName: '奶茶 大杯' })
    const b = product({ id: 'b', productName: '奶茶/大杯' })
    const c = product({ id: 'c', productName: '紅茶' })
    expect(pageProducts([a, b, c]).map((p) => p.id)).toEqual(['c'])
  })
})

describe('productPageTitle', () => {
  it('answers the 好吃嗎 query with the score', () => {
    expect(productPageTitle(product({}))).toBe('全家 布丁 好吃嗎？PTT 評價 80 分 | CVS Radar')
  })

  it('does not print a score the shelf would hide for a low-sample product', () => {
    expect(productPageTitle(product({ recommendationScore: null, consensus: '樣本不足' }))).toBe(
      '全家 布丁 好吃嗎？PTT 評價：樣本不足 | CVS Radar',
    )
  })
})

describe('relatedProducts', () => {
  it('suggests the best-scored others from the same aisle, never the page itself or an unscored one', () => {
    const self = product({ id: 'self', category: '甜點', recommendationScore: 99 })
    const best = product({ id: 'best', category: '甜點', recommendationScore: 90 })
    const ok = product({ id: 'ok', category: '甜點', recommendationScore: 70 })
    const unscored = product({ id: 'none', category: '甜點', recommendationScore: null })
    const otherAisle = product({ id: 'drink', category: '飲料', recommendationScore: 95 })
    expect(relatedProducts(self, [ok, unscored, self, otherAisle, best]).map((p) => p.id)).toEqual(['best', 'ok'])
  })

  it('stops at the limit so the page stays short', () => {
    const self = product({ id: 'self' })
    const many = Array.from({ length: 10 }, (_, i) => product({ id: `p${i}`, recommendationScore: 50 + i }))
    expect(relatedProducts(self, many, 3).map((p) => p.id)).toEqual(['p9', 'p8', 'p7'])
  })
})

describe('productPagePath', () => {
  it('ends with a slash to match the trailingSlash export', () => {
    expect(productPagePath(product({}))).toBe('/p/全家-布丁/')
  })
})
