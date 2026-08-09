import { describe, expect, it } from 'vitest'
import { Product } from './data'
import {
  buildFlavorGroups,
  comparableFlavors,
  flavorVerdict,
  groupedProductIds,
  isSoftServe,
  splitFlavors,
} from './soft-serve'

function product(overrides: Partial<Product>): Product {
  return {
    id: '全家::測試商品',
    brand: '全家',
    productName: '測試商品',
    price: 50,
    category: '冰品',
    fairScore: 70,
    recommendationScore: 78,
    consensus: '一致好評',
    confidence: '中',
    nPosts: 1,
    nComments: 2,
    rawComments: 2,
    eligibleComments: 2,
    uniqueEligibleCommenters: 2,
    independentThreads: 1,
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

function softServe(name: string, score: number | null, latestDate = '2026-06-15'): Product {
  return product({ id: `全家::${name}`, productName: name, recommendationScore: score, latestDate })
}

describe('splitFlavors', () => {
  it('keeps a single-flavour name as one flavour once the 霜淇淋 suffix is dropped', () => {
    expect(splitFlavors('梨山水蜜桃霜淇淋')).toEqual(['梨山水蜜桃'])
  })

  it('splits a swirl on either the lowercase or uppercase separator the labels use', () => {
    expect(splitFlavors('梨山水蜜桃x小農牛奶霜淇淋')).toEqual(['梨山水蜜桃', '小農牛奶'])
    expect(splitFlavors('莊園牛奶X滑爆可樂霜淇淋')).toEqual(['莊園牛奶', '滑爆可樂'])
  })

  it('reads a listed swirl that shipped without a separator as two flavours', () => {
    // Without the override this name looks single-flavour, which would hide the
    // 起司蛋糕 comparison and mis-label the product in the zone.
    expect(splitFlavors('起司蛋糕比利時巧克力霜淇淋')).toEqual(['起司蛋糕', '比利時巧克力'])
  })

  it('falls back to the whole name rather than producing no flavour at all', () => {
    expect(splitFlavors('霜淇淋')).toEqual(['霜淇淋'])
  })
})

describe('isSoftServe', () => {
  it('excludes tubs and cones, which are a different product to compare', () => {
    expect(isSoftServe(softServe('梨山水蜜桃霜淇淋', 69))).toBe(true)
    expect(isSoftServe(softServe('牧場直送4.0牛奶冰淇淋甜筒', 38))).toBe(false)
  })
})

describe('buildFlavorGroups', () => {
  it('drops flavours with nothing to compare against', () => {
    const groups = buildFlavorGroups([
      softServe('澎湖仙人掌霜淇淋', 74),
      softServe('梨山水蜜桃霜淇淋', 69),
      softServe('梨山水蜜桃x小農牛奶霜淇淋', 54),
    ])

    expect(groups.map((group) => group.flavor)).toEqual(['梨山水蜜桃'])
    expect(groups[0].single?.product.productName).toBe('梨山水蜜桃霜淇淋')
    expect(groups[0].duals).toHaveLength(1)
  })

  it('files a swirl under both of its flavours so each side can be compared', () => {
    const groups = buildFlavorGroups([
      softServe('起司蛋糕霜淇淋', 67),
      softServe('莊園牛奶霜淇淋', 77),
      softServe('起司蛋糕x莊園牛奶霜淇淋', 80),
    ])

    expect(groups.map((group) => group.flavor).sort()).toEqual(['莊園牛奶', '起司蛋糕'].sort())
    for (const group of groups) {
      expect(group.duals.map((dual) => dual.product.productName)).toEqual(['起司蛋糕x莊園牛奶霜淇淋'])
    }
  })

  it('orders swirls by score so the verdict compares against the best pairing', () => {
    const [group] = buildFlavorGroups([
      softServe('莊園牛奶霜淇淋', 77),
      softServe('莊園牛奶X滑爆可樂霜淇淋', 37),
      softServe('起司蛋糕x莊園牛奶霜淇淋', 80),
      softServe('UCC經典炭燒咖啡x莊園牛奶霜淇淋', 65),
    ]).filter((candidate) => candidate.flavor === '莊園牛奶')

    expect(group.duals.map((dual) => dual.product.recommendationScore)).toEqual([80, 65, 37])
  })

  it('sorts groups by their most recent discussion, undated last', () => {
    const groups = buildFlavorGroups([
      softServe('抹茶霜淇淋', 55, '2026-03-10'),
      softServe('抹茶x焦糖霜淇淋', 44, '2026-03-19'),
      softServe('水蜜桃霜淇淋', 69, '2026-07-08'),
      softServe('水蜜桃x牛奶霜淇淋', 54, '2026-07-19'),
    ])

    // 牛奶 and 焦糖 each appear in one product only, so they never form a group.
    expect(groups.map((group) => group.flavor)).toEqual(['水蜜桃', '抹茶'])
  })
})

describe('groupedProductIds', () => {
  it('reports every product the comparison section already shows', () => {
    const products = [
      softServe('梨山水蜜桃霜淇淋', 69),
      softServe('梨山水蜜桃x小農牛奶霜淇淋', 54),
      softServe('澎湖仙人掌霜淇淋', 74),
    ]
    const ids = groupedProductIds(buildFlavorGroups(products))

    // The leftover list is built by difference, so a miss here would duplicate a
    // product across both sections of the page.
    expect(ids.has('全家::梨山水蜜桃霜淇淋')).toBe(true)
    expect(ids.has('全家::梨山水蜜桃x小農牛奶霜淇淋')).toBe(true)
    expect(ids.has('全家::澎湖仙人掌霜淇淋')).toBe(false)
  })
})

describe('comparableFlavors', () => {
  it('covers a swirl partner that has its own card but not one that does not', () => {
    // The zone links a swirl row to its partner's card. 莊園牛奶 was also sold
    // on its own so it has a card; 小農牛奶 only ever appeared inside a swirl,
    // and linking to it would point at nothing.
    const groups = buildFlavorGroups([
      softServe('起司蛋糕霜淇淋', 67),
      softServe('莊園牛奶霜淇淋', 77),
      softServe('起司蛋糕x莊園牛奶霜淇淋', 80),
      softServe('梨山水蜜桃霜淇淋', 69),
      softServe('梨山水蜜桃x小農牛奶霜淇淋', 54),
    ])
    const flavors = comparableFlavors(groups)

    expect(flavors.has('莊園牛奶')).toBe(true)
    expect(flavors.has('小農牛奶')).toBe(false)
  })
})

describe('flavorVerdict', () => {
  function verdictFor(products: Product[], flavor: string) {
    const group = buildFlavorGroups(products).find((candidate) => candidate.flavor === flavor)
    return group ? flavorVerdict(group) : null
  }

  it('names the single flavour when it beats the best swirl', () => {
    const verdict = verdictFor(
      [softServe('梨山水蜜桃霜淇淋', 69), softServe('梨山水蜜桃x小農牛奶霜淇淋', 54)],
      '梨山水蜜桃',
    )

    expect(verdict).toEqual({ winner: 'single', text: '單吃評價較好（69 分 vs 配小農牛奶 54 分）' })
  })

  it('names the winning partner when the swirl beats the single flavour', () => {
    const verdict = verdictFor(
      [softServe('起司蛋糕霜淇淋', 67), softServe('起司蛋糕x莊園牛奶霜淇淋', 80)],
      '起司蛋糕',
    )

    expect(verdict).toEqual({ winner: 'dual', text: '配莊園牛奶評價較好（80 分 vs 單吃 67 分）' })
  })

  it('calls a gap under 5 分 a draw rather than a winner', () => {
    // Scores this close are inside the noise of a handful of PTT comments;
    // declaring a winner would read as a finding the data cannot support.
    const verdict = verdictFor(
      [softServe('滑爆可樂霜淇淋', 34), softServe('莊園牛奶X滑爆可樂霜淇淋', 37)],
      '滑爆可樂',
    )

    expect(verdict).toEqual({ winner: 'tie', text: '單吃與雙拼評價差不多' })
  })

  it('stays silent when a side is missing or unscored', () => {
    expect(
      verdictFor(
        [softServe('起司蛋糕x莊園牛奶霜淇淋', 80), softServe('草莓優酪x莊園牛奶霜淇淋', 69)],
        '莊園牛奶',
      ),
    ).toBeNull()

    expect(
      verdictFor(
        [softServe('白熊霜淇淋', null), softServe('白熊x牛奶霜淇淋', 60)],
        '白熊',
      ),
    ).toBeNull()
  })
})

