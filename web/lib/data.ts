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
  minScore: number
  fromDate: string
  toDate: string
}

export type SortKey =
  | 'latestDateDesc'
  | 'latestDateAsc'
  | 'volumeDesc'
  | 'volumeAsc'
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

export function applyAdvanced(products: Product[], filters: AdvancedFilters): Product[] {
  return products.filter((product) => {
    if ((product.recommendationScore ?? 0) < filters.minScore) return false
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

    if (sortKey === 'latestDateDesc' || sortKey === 'latestDateAsc') {
      difference = compareNullableStrings(a.latestDate, b.latestDate, sortKey === 'latestDateDesc')
    } else if (sortKey === 'volumeDesc' || sortKey === 'volumeAsc') {
      const aVolume = a.nPosts + a.nComments
      const bVolume = b.nPosts + b.nComments
      difference = sortKey === 'volumeDesc' ? bVolume - aVolume : aVolume - bVolume
    } else {
      difference = compareNullableNumbers(
        a.recommendationScore,
        b.recommendationScore,
        sortKey === 'fairScoreDesc',
      )
    }

    if (difference !== 0) return difference

    const scoreDiff = (b.recommendationScore ?? -1) - (a.recommendationScore ?? -1)
    const fairScoreDiff = (b.fairScore ?? -1) - (a.fairScore ?? -1)
    const volumeDiff = b.nPosts + b.nComments - (a.nPosts + a.nComments)
    const dateDiff = compareNullableStrings(a.latestDate, b.latestDate, true)

    if (sortKey === 'latestDateDesc' || sortKey === 'latestDateAsc') {
      if (scoreDiff !== 0) return scoreDiff
      if (volumeDiff !== 0) return volumeDiff
    } else if (sortKey === 'volumeDesc' || sortKey === 'volumeAsc') {
      if (scoreDiff !== 0) return scoreDiff
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
    latestDateDesc: '發文時間：近到遠',
    latestDateAsc: '發文時間：遠到近',
    volumeDesc: '聲量：高到低',
    volumeAsc: '聲量：低到高',
    fairScoreDesc: '推薦分：高到低',
    fairScoreAsc: '推薦分：低到高',
  }
  return labels[sortKey]
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

export function volumePercent(level: string): number {
  if (level === '充足') return 78
  if (level === '中等') return 52
  return 28
}
