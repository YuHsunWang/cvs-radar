import { Product, comprehensiveScore } from './data'

// Soft-serve names encode the flavour count: a swirl of two flavours is spelled
// "A x B霜淇淋", a single flavour has no separator. That is the only signal we
// have — the pipeline carries no flavour-count field — so the zone derives it
// from the name and nothing else.
const SOFT_SERVE_KEYWORD = '霜淇淋'
const FLAVOR_SEPARATOR = /[xX×]/
const NOISE_WORDS = [SOFT_SERVE_KEYWORD, '綜合']

// Names that ship a two-flavour swirl without the separator. The split rule
// alone reads these as one flavour, so they are listed by hand. Keep the list
// short and only add names that were checked against the source post.
const DUAL_FLAVOR_OVERRIDES: Record<string, [string, string]> = {
  起司蛋糕比利時巧克力霜淇淋: ['起司蛋糕', '比利時巧克力'],
}

export const HOT_WITHIN_DAYS = 30
export const QUIET_AFTER_DAYS = 180
export const VERDICT_MIN_GAP = 5

const millisecondsPerDay = 24 * 60 * 60 * 1000

export function isSoftServe(product: Product): boolean {
  return product.productName.includes(SOFT_SERVE_KEYWORD)
}

export function splitFlavors(productName: string): string[] {
  const override = DUAL_FLAVOR_OVERRIDES[productName]
  if (override) return [...override]

  const stripped = NOISE_WORDS.reduce((name, word) => name.replaceAll(word, ''), productName)
  const parts = stripped
    .split(FLAVOR_SEPARATOR)
    .map((part) => part.trim())
    .filter(Boolean)
  return parts.length > 0 ? parts : [productName]
}

export type SoftServeItem = {
  product: Product
  flavors: string[]
  isDual: boolean
}

export function toSoftServeItem(product: Product): SoftServeItem {
  const flavors = splitFlavors(product.productName)
  return { product, flavors, isDual: flavors.length > 1 }
}

export function softServeItems(products: Product[]): SoftServeItem[] {
  return products.filter(isSoftServe).map(toSoftServeItem)
}

export function partnerFlavor(item: SoftServeItem, flavor: string): string {
  return item.flavors.find((candidate) => candidate !== flavor) ?? ''
}

export type FlavorGroup = {
  flavor: string
  single: SoftServeItem | null
  duals: SoftServeItem[]
  latestDate: string | null
}

/**
 * Groups soft-serve products by flavour, keeping only flavours that appear in
 * at least two products — those are the ones where single-vs-swirl can actually
 * be compared. A swirl lands in both of its flavour groups on purpose, so
 * "起司蛋糕×莊園牛奶" shows up under 起司蛋糕 and under 莊園牛奶.
 */
export function buildFlavorGroups(products: Product[]): FlavorGroup[] {
  const byFlavor = new Map<string, SoftServeItem[]>()
  for (const item of softServeItems(products)) {
    for (const flavor of item.flavors) {
      const bucket = byFlavor.get(flavor)
      if (bucket) bucket.push(item)
      else byFlavor.set(flavor, [item])
    }
  }

  const groups: FlavorGroup[] = []
  for (const [flavor, bucket] of byFlavor) {
    if (bucket.length < 2) continue
    groups.push({
      flavor,
      single: bucket.find((item) => !item.isDual) ?? null,
      duals: bucket.filter((item) => item.isDual).sort(byScoreDesc),
      latestDate: bucket.reduce<string | null>(
        (latest, item) =>
          item.product.latestDate && (!latest || item.product.latestDate > latest)
            ? item.product.latestDate
            : latest,
        null,
      ),
    })
  }

  return groups.sort((a, b) => {
    if (a.latestDate === b.latestDate) return a.flavor.localeCompare(b.flavor, 'zh-TW')
    if (a.latestDate === null) return 1
    if (b.latestDate === null) return -1
    return b.latestDate.localeCompare(a.latestDate)
  })
}

/** Products already shown in the comparison section, keyed by product id. */
export function groupedProductIds(groups: FlavorGroup[]): Set<string> {
  const ids = new Set<string>()
  for (const group of groups) {
    if (group.single) ids.add(group.single.product.id)
    for (const dual of group.duals) ids.add(dual.product.id)
  }
  return ids
}

function byScoreDesc(a: SoftServeItem, b: SoftServeItem): number {
  const scoreA = comprehensiveScore(a.product)
  const scoreB = comprehensiveScore(b.product)
  if (scoreA === null) return scoreB === null ? 0 : 1
  if (scoreB === null) return -1
  return scoreB - scoreA
}

export type FlavorVerdict = {
  winner: 'single' | 'dual' | 'tie'
  text: string
}

/**
 * Compares the single-flavour product against the best-scoring swirl. Returns
 * null when there is nothing to compare — a missing side or a missing score is
 * not a draw, and claiming one would invent a result the data does not support.
 */
export function flavorVerdict(group: FlavorGroup): FlavorVerdict | null {
  const singleScore = group.single ? comprehensiveScore(group.single.product) : null
  if (singleScore === null) return null

  const bestDual = group.duals.find((item) => comprehensiveScore(item.product) !== null)
  if (!bestDual) return null
  const dualScore = comprehensiveScore(bestDual.product) as number

  const partner = partnerFlavor(bestDual, group.flavor)
  const gap = dualScore - singleScore

  if (Math.abs(gap) < VERDICT_MIN_GAP) return { winner: 'tie', text: '單吃與雙拼評價差不多' }
  if (gap > 0) {
    return { winner: 'dual', text: `配${partner}評價較好（${dualScore} 分 vs 單吃 ${singleScore} 分）` }
  }
  return { winner: 'single', text: `單吃評價較好（${singleScore} 分 vs 配${partner} ${dualScore} 分）` }
}

// The site has no on-shelf / off-shelf data, only the date of the most recent
// PTT discussion. These buckets describe discussion activity and deliberately
// stop short of claiming a product is still being sold.
export type Freshness = 'hot' | 'steady' | 'quiet' | 'unknown'

export function freshness(latestDate: string | null, now = Date.now()): Freshness {
  if (!latestDate) return 'unknown'
  const latestMs = Date.parse(`${latestDate}T00:00:00+08:00`)
  if (!Number.isFinite(latestMs)) return 'unknown'
  const ageDays = (now - latestMs) / millisecondsPerDay
  if (ageDays <= HOT_WITHIN_DAYS) return 'hot'
  if (ageDays <= QUIET_AFTER_DAYS) return 'steady'
  return 'quiet'
}

export function freshnessLabel(value: Freshness): string | null {
  if (value === 'hot') return '熱議中'
  if (value === 'quiet') return '已沉寂'
  return null
}
