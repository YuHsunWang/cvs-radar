import { describe, expect, it } from 'vitest'
import {
  Product,
  applyAdvanced,
  dateToOffset,
  displayCategory,
  filterByCategory,
  filterHasScore,
  formatDisplayDate,
  offsetToDate,
  sortProducts,
} from './data'

function product(overrides: Partial<Product>): Product {
  return {
    id: '7-11::測試商品',
    brand: '7-11',
    productName: '測試商品',
    price: 50,
    category: '飲料',
    fairScore: 70,
    recommendationScore: 78,
    consensus: '一致好評',
    confidence: '中',
    nPosts: 1,
    nComments: 2,
    volumeLevel: '中等',
    positivePct: 60,
    neutralPct: 20,
    negativePct: 20,
    likes: [],
    cautions: [],
    excerpt: '',
    postUrls: [],
    latestDate: '2026-06-15',
    ...overrides,
  }
}

describe('applyAdvanced', () => {
  it('treats both date boundaries as inclusive and drops undated products', () => {
    const products = [
      product({ id: 'start', latestDate: '2026-06-01' }),
      product({ id: 'middle', latestDate: '2026-06-15' }),
      product({ id: 'end', latestDate: '2026-06-30' }),
      product({ id: 'outside', latestDate: '2026-07-01' }),
      product({ id: 'undated', latestDate: null }),
    ]

    expect(
      applyAdvanced(products, { minScore: 0, fromDate: '2026-06-01', toDate: '2026-06-30' }).map(
        ({ id }) => id,
      ),
    ).toEqual(['start', 'middle', 'end'])
  })

  it('keeps the minimum-score condition when no date range is active', () => {
    const products = [
      product({ id: 'low', recommendationScore: 59 }),
      product({ id: 'pass', recommendationScore: 60 }),
    ]
    expect(applyAdvanced(products, { minScore: 60, fromDate: '', toDate: '' }).map(({ id }) => id)).toEqual([
      'pass',
    ])
  })
})

describe('filterByCategory', () => {
  const products = [
    product({ id: 'meal', category: '便當' }),
    product({ id: 'savory', category: '鹹食' }),
    product({ id: 'noodles', category: '泡麵' }),
    product({ id: 'dessert', category: '甜點' }),
    product({ id: 'milk', category: '乳品' }),
    product({ id: 'merch', category: '周邊' }),
    product({ id: 'unknown', category: '' }),
  ]

  it('groups meal categories around the user eating intent', () => {
    expect(filterByCategory(products, '正餐').map(({ id }) => id)).toEqual(['meal', 'savory', 'noodles'])
  })

  it('groups dairy with drinks and merchandise with other', () => {
    expect(filterByCategory(products, '飲料').map(({ id }) => id)).toEqual(['milk'])
    expect(filterByCategory(products, '其他').map(({ id }) => id)).toEqual(['merch', 'unknown'])
  })

  it('returns every product when no category is selected', () => {
    expect(filterByCategory(products, null)).toEqual(products)
  })
})

describe('filterHasScore', () => {
  it('hides only products without a recommendation score when the quick filter is enabled', () => {
    const products = [product({ id: 'scored', recommendationScore: 78 }), product({ id: 'unscored', recommendationScore: null })]

    expect(filterHasScore(products, true).map(({ id }) => id)).toEqual(['scored'])
    expect(filterHasScore(products, false)).toEqual(products)
  })
})

describe('date slider offsets', () => {
  it('round-trips UTC calendar days, including the minimum and maximum bounds', () => {
    const minDate = '2026-02-27'
    const maxDate = '2026-03-03'

    expect(dateToOffset(minDate, minDate)).toBe(0)
    expect(dateToOffset(maxDate, minDate)).toBe(4)
    expect(offsetToDate(0, minDate)).toBe(minDate)
    expect(offsetToDate(dateToOffset(maxDate, minDate), minDate)).toBe(maxDate)
  })
})

describe('displayCategory', () => {
  it('uses the same vocabulary as the category chips without changing filter groups', () => {
    expect(displayCategory('便當')).toBe('正餐')
    expect(displayCategory('乳品')).toBe('飲料')
    expect(displayCategory('')).toBe('其他')
  })
})

describe('formatDisplayDate', () => {
  it('converts UTC timestamps to the Taiwan calendar date', () => {
    expect(formatDisplayDate('2026-07-10T23:55:11+00:00')).toBe('2026/07/11')
  })

  it('keeps date-only values readable', () => {
    expect(formatDisplayDate('2026-07-05')).toBe('2026/07/05')
  })
})

describe('sortProducts', () => {
  const products = [
    product({ id: 'a', fairScore: 80, recommendationScore: 93, nComments: 3, latestDate: '2026-06-01' }),
    product({ id: 'b', fairScore: 60, recommendationScore: 72, nComments: 8, latestDate: '2026-06-20' }),
    product({ id: 'c', fairScore: 70, recommendationScore: 84, nComments: 5, latestDate: '2026-06-10' }),
  ]

  it.each([
    ['latestDateDesc', ['b', 'c', 'a']],
    ['latestDateAsc', ['a', 'c', 'b']],
    ['volumeDesc', ['b', 'c', 'a']],
    ['volumeAsc', ['a', 'c', 'b']],
    ['fairScoreDesc', ['a', 'c', 'b']],
    ['fairScoreAsc', ['b', 'c', 'a']],
  ] as const)('sorts %s in the requested direction', (sortKey, expected) => {
    expect(sortProducts(products, sortKey).map(({ id }) => id)).toEqual(expected)
  })

  it('uses volume and then recency to produce useful score tie-breaks', () => {
    const tied = [
      product({ id: 'old-low-volume', fairScore: 70, recommendationScore: 84, nComments: 2, latestDate: '2026-05-01' }),
      product({ id: 'new-high-volume', fairScore: 70, recommendationScore: 84, nComments: 8, latestDate: '2026-06-01' }),
      product({ id: 'old-high-volume', fairScore: 70, recommendationScore: 84, nComments: 8, latestDate: '2026-05-01' }),
    ]

    expect(sortProducts(tied, 'fairScoreDesc').map(({ id }) => id)).toEqual([
      'new-high-volume',
      'old-high-volume',
      'old-low-volume',
    ])
  })

  it('uses the unrounded fair score to preserve ranking inside a calibrated-score tie', () => {
    const tied = [
      product({ id: 'lower', fairScore: 79, recommendationScore: 92 }),
      product({ id: 'higher', fairScore: 80, recommendationScore: 92 }),
    ]

    expect(sortProducts(tied, 'fairScoreDesc').map(({ id }) => id)).toEqual(['higher', 'lower'])
    expect(sortProducts(tied, 'fairScoreAsc').map(({ id }) => id)).toEqual(['lower', 'higher'])
  })
})
