import { describe, expect, it } from 'vitest'
import {
  DATA_STALE_DAYS,
  Product,
  applyAdvanced,
  comprehensiveScore,
  consensusTone,
  dataAgeDays,
  dateToOffset,
  displayCategory,
  filterByCategory,
  filterHasScore,
  formatDisplayDate,
  isDataStale,
  normalizeDateRange,
  offsetToDate,
  recentRecommendationScore,
  sentimentSegments,
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
      applyAdvanced(products, { fromDate: '2026-06-01', toDate: '2026-06-30' }).map(
        ({ id }) => id,
      ),
    ).toEqual(['start', 'middle', 'end'])
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

  it('finds upstream categories shown as other under the other filter', () => {
    expect(filterByCategory([product({ id: 'new', category: '新品類' })], '其他').map(({ id }) => id)).toEqual(['new'])
  })

  it('returns every product when no category is selected', () => {
    expect(filterByCategory(products, null)).toEqual(products)
  })
})

describe('filterHasScore', () => {
  it('hides products without a reliable comprehensive score when the quick filter is enabled', () => {
    const products = [
      product({ id: 'scored', fairScore: 65, recommendationScore: 78 }),
      product({ id: 'unscored', fairScore: 65, recommendationScore: null }),
    ]

    expect(filterHasScore(products, true).map(({ id }) => id)).toEqual(['scored'])
    expect(filterHasScore(products, false)).toEqual(products)
  })
})

describe('comprehensiveScore', () => {
  it('uses the calibrated recommendation score as the canonical public score', () => {
    expect(comprehensiveScore(product({ fairScore: 20, recommendationScore: 91 }))).toBe(91)
  })

  it('preserves a null recommendation score even when a Bayesian score exists', () => {
    expect(comprehensiveScore(product({ fairScore: 75, recommendationScore: null }))).toBeNull()
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

  it('normalizes the full range to no date filter so undated products stay eligible', () => {
    const fullRange = normalizeDateRange('2026-02-27', '2026-03-03', '2026-02-27', '2026-03-03')
    expect(fullRange).toEqual({
      fromDate: '',
      toDate: '',
    })
    expect(applyAdvanced([product({ latestDate: null })], { ...fullRange })).toHaveLength(1)
    expect(normalizeDateRange('2026-02-28', '2026-03-03', '2026-02-27', '2026-03-03')).toEqual({
      fromDate: '2026-02-28',
      toDate: '2026-03-03',
    })
  })
})

describe('displayCategory', () => {
  it('uses the same vocabulary as the category chips without changing filter groups', () => {
    expect(displayCategory('便當')).toBe('正餐')
    expect(displayCategory('乳品')).toBe('飲料')
    expect(displayCategory('')).toBe('其他')
  })
})

describe('consensusTone', () => {
  it('renders the dominant mixed-consensus enum as mixed', () => {
    expect(consensusTone('褒貶不一')).toBe('mixed')
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

describe('data freshness', () => {
  const now = Date.parse('2026-07-23T12:00:00+08:00')

  it('treats a recent data timestamp as fresh', () => {
    const recent = new Date(now - (DATA_STALE_DAYS - 1) * 24 * 60 * 60 * 1000).toISOString()

    expect(dataAgeDays(recent, now)).toBe(DATA_STALE_DAYS - 1)
    expect(isDataStale(recent, now)).toBe(false)
  })

  it('treats data older than the threshold as stale', () => {
    const stale = new Date(now - (DATA_STALE_DAYS + 1) * 24 * 60 * 60 * 1000).toISOString()

    expect(dataAgeDays(stale, now)).toBe(DATA_STALE_DAYS + 1)
    expect(isDataStale(stale, now)).toBe(true)
  })

  it.each(['not-a-date', ''])('treats %j as unknown without throwing', (value) => {
    expect(dataAgeDays(value, now)).toBeNull()
    expect(isDataStale(value, now)).toBe(false)
  })
})

describe('sentimentSegments', () => {
  it('normalizes non-low-confidence sentiment percentages for the compact card bar', () => {
    expect(sentimentSegments(product({ positivePct: 2, neutralPct: 1, negativePct: 1 }))).toEqual([
      { label: '正評', value: 50, className: 'bg-[#5A9F28]' },
      { label: '中立', value: 25, className: 'bg-[#9B9A92]' },
      { label: '負評', value: 25, className: 'bg-[#E84D4D]' },
    ])
  })

  it('hides sentiment bars when confidence is low or no percentages exist', () => {
    expect(sentimentSegments(product({ confidence: '低' }))).toEqual([])
    expect(
      sentimentSegments(product({ positivePct: null, neutralPct: null, negativePct: null })),
    ).toEqual([])
  })
})

describe('sortProducts', () => {
  const products = [
    product({ id: 'a', fairScore: 80, recommendationScore: 93, nComments: 3, latestDate: '2026-06-01' }),
    product({ id: 'b', fairScore: 60, recommendationScore: 72, nComments: 8, latestDate: '2026-06-20' }),
    product({ id: 'c', fairScore: 70, recommendationScore: 84, nComments: 5, latestDate: '2026-06-10' }),
  ]

  it.each([
    ['recentRecommendationDesc', ['b', 'c', 'a']],
    ['discussionHeatDesc', ['b', 'c', 'a']],
    ['fairScoreDesc', ['a', 'c', 'b']],
    ['fairScoreAsc', ['b', 'c', 'a']],
  ] as const)('sorts %s in the requested direction', (sortKey, expected) => {
    expect(sortProducts(products, sortKey).map(({ id }) => id)).toEqual(expected)
  })

  it('boosts more-discussed products when score and recency are equal', () => {
    const equallyScoredAndRecent = [
      product({ id: 'low-volume', productName: '甲', nPosts: 1, nComments: 0, latestDate: '2026-06-15' }),
      product({ id: 'high-volume', productName: '乙', nPosts: 6, nComments: 12, latestDate: '2026-06-15' }),
    ]

    expect(sortProducts(equallyScoredAndRecent, 'recentRecommendationDesc').map(({ id }) => id)).toEqual([
      'high-volume',
      'low-volume',
    ])
  })

  it('returns no recent recommendation score when the recommendation score is unavailable', () => {
    expect(recentRecommendationScore(product({ fairScore: 75, recommendationScore: null }))).toBeNull()
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

  it('sorts score modes by recommendation score rather than Bayesian fair score', () => {
    const opposedScores = [
      product({ id: 'higher-fair', fairScore: 90, recommendationScore: 60 }),
      product({ id: 'higher-recommendation', fairScore: 40, recommendationScore: 80 }),
    ]

    expect(sortProducts(opposedScores, 'fairScoreDesc').map(({ id }) => id)).toEqual([
      'higher-recommendation',
      'higher-fair',
    ])
    expect(sortProducts(opposedScores, 'fairScoreAsc').map(({ id }) => id)).toEqual([
      'higher-fair',
      'higher-recommendation',
    ])
  })
})
