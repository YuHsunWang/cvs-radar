export type Product = {
  id: string
  brand: string
  productName: string
  price: number | null
  category: string
  fairScore: number | null
  recommendationScore: number | null
  consensus: string
  confidence: string
  nPosts: number
  nComments: number
  volumeLevel: string
  positivePct: number | null
  neutralPct: number | null
  negativePct: number | null
  likes: string[]
  cautions: string[]
  excerpt: string
  postUrls: string[]
  latestDate: string | null
}

export type DataPayload = {
  generatedAt: string
  products: Product[]
}

export type AdvancedFilters = {
  fromDate: string
  toDate: string
}

export type SortKey =
  | 'recentRecommendationDesc'
  | 'discussionHeatDesc'
  | 'fairScoreDesc'
  | 'fairScoreAsc'

export const brands = ['7-11', '全家', '萊爾富', 'OK', '美聯社', '其他'] as const
export const categoryGroups = {
  正餐: ['便當', '鹹食', '泡麵'],
  甜點: ['甜點'],
  冰品: ['冰品'],
  飲料: ['飲料', '乳品'],
  麵包: ['麵包'],
  零食: ['零食'],
  其他: ['其他', '周邊'],
} as const
export type CategoryKey = keyof typeof categoryGroups
export const categoryKeys = Object.keys(categoryGroups) as CategoryKey[]

export function normalizeText(value: string): string {
  return value.normalize('NFKC').toLocaleLowerCase('zh-TW')
}

export function formatDisplayDate(value: string): string {
  if (!value) return '載入中'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10).replaceAll('-', '/')
  return new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

export function filterBySearch(products: Product[], query: string): Product[] {
  const needle = normalizeText(query.trim())
  if (!needle) return products
  return products.filter((product) =>
    normalizeText(`${product.productName} ${product.brand}`).includes(needle),
  )
}

export function filterByBrand(products: Product[], brand: string | null): Product[] {
  if (!brand) return products
  return products.filter((product) => displayBrand(product.brand) === brand)
}

export function filterByCategory(products: Product[], category: CategoryKey | null): Product[] {
  if (!category) return products
  const includedCategories: readonly string[] = categoryGroups[category]
  return products.filter((product) => includedCategories.includes(product.category.trim() || '其他'))
}

export function filterHasScore(products: Product[], hideNoScore: boolean): Product[] {
  if (!hideNoScore) return products
  return products.filter((product) => comprehensiveScore(product) !== null)
}

export function comprehensiveScore(product: Product): number | null {
  return product.recommendationScore === null ? null : product.fairScore
}

const millisecondsPerDay = 24 * 60 * 60 * 1000
const DEFAULT_HALF_LIFE_DAYS = 24
const RECOMMENDATION_HEAT_WEIGHT = 0.15

function toUtcCalendarDay(value: string): number {
  const [year, month, day] = value.split('-').map(Number)
  return Date.UTC(year, month - 1, day)
}

export function dateToOffset(date: string, minDate: string): number {
  return Math.round((toUtcCalendarDay(date) - toUtcCalendarDay(minDate)) / millisecondsPerDay)
}

export function offsetToDate(offset: number, minDate: string): string {
  return new Date(toUtcCalendarDay(minDate) + offset * millisecondsPerDay).toISOString().slice(0, 10)
}

export function normalizeDateRange(
  fromDate: string,
  toDate: string,
  minDate: string,
  maxDate: string,
): Pick<AdvancedFilters, 'fromDate' | 'toDate'> {
  if (fromDate === minDate && toDate === maxDate) return { fromDate: '', toDate: '' }
  return { fromDate, toDate }
}

export function applyAdvanced(products: Product[], filters: AdvancedFilters): Product[] {
  return products.filter((product) => {
    if (!filters.fromDate && !filters.toDate) return true
    if (!product.latestDate) return false
    if (filters.fromDate && product.latestDate < filters.fromDate) return false
    if (filters.toDate && product.latestDate > filters.toDate) return false
    return true
  })
}

export function sortProducts(products: Product[], sortKey: SortKey): Product[] {
  return [...products].sort((a, b) => {
    let difference = 0

    if (sortKey === 'recentRecommendationDesc') {
      difference = compareNullableNumbers(
        recentRecommendationScore(a),
        recentRecommendationScore(b),
        true,
      )
    } else if (sortKey === 'discussionHeatDesc') {
      difference = compareNullableNumbers(discussionHeat(a), discussionHeat(b), true)
    } else {
      difference = compareNullableNumbers(
        comprehensiveScore(a),
        comprehensiveScore(b),
        sortKey === 'fairScoreDesc',
      )
    }

    if (difference !== 0) return difference

    const scoreDiff = (comprehensiveScore(b) ?? -1) - (comprehensiveScore(a) ?? -1)
    const fairScoreDiff = (b.fairScore ?? -1) - (a.fairScore ?? -1)
    const volumeDiff = b.nPosts + b.nComments - (a.nPosts + a.nComments)
    const dateDiff = compareNullableStrings(a.latestDate, b.latestDate, true)

    if (sortKey === 'recentRecommendationDesc' || sortKey === 'discussionHeatDesc') {
      if (scoreDiff !== 0 && sortKey === 'recentRecommendationDesc') return scoreDiff
      if (volumeDiff !== 0 && sortKey === 'discussionHeatDesc') return volumeDiff
      if (dateDiff !== 0) return dateDiff
    } else {
      if (fairScoreDiff !== 0) return sortKey === 'fairScoreDesc' ? fairScoreDiff : -fairScoreDiff
      if (volumeDiff !== 0) return volumeDiff
      if (dateDiff !== 0) return dateDiff
    }

    const brandDiff = brandRank(a.brand) - brandRank(b.brand)
    if (brandDiff !== 0) return brandDiff
    return normalizeText(a.productName).localeCompare(normalizeText(b.productName), 'zh-TW')
  })
}

function compareNullableNumbers(a: number | null, b: number | null, descending: boolean): number {
  if (a === null) return b === null ? 0 : 1
  if (b === null) return -1
  return descending ? b - a : a - b
}

function compareNullableStrings(a: string | null, b: string | null, descending: boolean): number {
  if (a === null) return b === null ? 0 : 1
  if (b === null) return -1
  return descending ? b.localeCompare(a) : a.localeCompare(b)
}

export function sortLabel(sortKey: SortKey): string {
  const labels: Record<SortKey, string> = {
    recentRecommendationDesc: '近期推薦',
    discussionHeatDesc: '討論熱度',
    fairScoreDesc: '綜合評分：高到低',
    fairScoreAsc: '綜合評分：低到高',
  }
  return labels[sortKey]
}

function ageDecay(product: Product, halfLifeDays = DEFAULT_HALF_LIFE_DAYS): number {
  if (!product.latestDate) return 0
  const ageDays = Math.max(0, (Date.now() - Date.parse(`${product.latestDate}T00:00:00+08:00`)) / millisecondsPerDay)
  return Math.pow(0.5, ageDays / halfLifeDays)
}

export function recentRecommendationScore(product: Product): number | null {
  const score = comprehensiveScore(product)
  return score === null
    ? null
    : score * ageDecay(product) * (1 + RECOMMENDATION_HEAT_WEIGHT * Math.log1p(product.nPosts + product.nComments))
}

export function discussionHeat(product: Product): number {
  return ageDecay(product) * Math.log1p(product.nPosts + product.nComments)
}

export function brandRank(brand: string): number {
  const index = brands.indexOf(displayBrand(brand) as (typeof brands)[number])
  return index === -1 ? brands.length : index
}

export function displayBrand(brand: string): string {
  return brands.includes(brand as (typeof brands)[number]) ? brand : '其他'
}

export function displayCategory(category: string): string {
  const rawCategory = category.trim() || '其他'
  return categoryKeys.find((key) => {
    const groupedCategories: readonly string[] = categoryGroups[key]
    return groupedCategories.includes(rawCategory)
  }) ?? '其他'
}

export function consensusTone(consensus: string): 'good' | 'mixed' | 'low' {
  if (consensus === '一致好評') return 'good'
  if (consensus === '評價兩極') return 'mixed'
  return 'low'
}

export type SentimentSegment = {
  label: '正評' | '中立' | '負評'
  value: number
  className: string
}

export function sentimentSegments(product: Product): SentimentSegment[] {
  if (product.confidence === '低') return []

  const rawSegments: SentimentSegment[] = [
    { label: '正評', value: product.positivePct ?? 0, className: 'bg-[#5A9F28]' },
    { label: '中立', value: product.neutralPct ?? 0, className: 'bg-[#9B9A92]' },
    { label: '負評', value: product.negativePct ?? 0, className: 'bg-[#E84D4D]' },
  ]
  const total = rawSegments.reduce((sum, segment) => sum + segment.value, 0)

  if (total <= 0) return []

  return rawSegments.map((segment) => ({
    ...segment,
    value: Math.max(0, Math.round((segment.value / total) * 100)),
  }))
}

export function scoreToneClass(score: number | null): string {
  if (score === null) return 'text-slate-500'
  if (score >= 70) return 'text-green-700'
  if (score >= 50) return 'text-amber-700'
  return 'text-red-700'
}

export function volumePercent(level: string): number {
  if (level === '充足') return 78
  if (level === '中等') return 52
  return 28
}
