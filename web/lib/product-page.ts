import { Product, comprehensiveScore, displayCategory } from './data'

// Below this many usable comments a page has too little text of its own to be
// worth indexing; those products stay reachable on the shelf.
export const MIN_PAGE_COMMENTS = 3

/**
 * The readable path segment for a product page, e.g. 全家-生巧風味餅乾夾心.
 * Characters that mean something in a URL or a file path become a hyphen, so
 * the static export writes one plain directory per product.
 */
export function productSlug(product: Pick<Product, 'brand' | 'productName'>): string {
  return `${product.brand}-${product.productName}`
    .normalize('NFKC')
    .trim()
    .replace(/[\s/\\?#%&+:]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-|-$/g, '')
}

/** Products that get a page. A slug two products would share goes to neither. */
export function pageProducts(products: Product[]): Product[] {
  const eligible = products.filter((product) => product.eligibleComments >= MIN_PAGE_COMMENTS)
  const counts = new Map<string, number>()
  for (const product of eligible) {
    const slug = productSlug(product)
    counts.set(slug, (counts.get(slug) ?? 0) + 1)
  }
  return eligible.filter((product) => counts.get(productSlug(product)) === 1)
}

export function productPagePath(product: Pick<Product, 'brand' | 'productName'>): string {
  return `/p/${productSlug(product)}/`
}

/**
 * The best-scored other pages in the same aisle: somewhere to go next for a
 * visitor who arrived from search, and links that let a crawler find the rest.
 * Unscored products are left out, since "—" gives no reason to click.
 */
export function relatedProducts(product: Product, pages: Product[], limit = 6): Product[] {
  const category = displayCategory(product.category)
  return pages
    .filter((other) => other.id !== product.id && displayCategory(other.category) === category && comprehensiveScore(other) !== null)
    .sort((a, b) =>
      (comprehensiveScore(b) ?? 0) - (comprehensiveScore(a) ?? 0)
      || b.eligibleComments - a.eligibleComments
      || a.id.localeCompare(b.id),
    )
    .slice(0, limit)
}

/** The search-result headline: what people type, then the number that answers it. */
export function productPageTitle(product: Product): string {
  const score = comprehensiveScore(product)
  const verdict = score === null ? `PTT 評價：${product.consensus}` : `PTT 評價 ${score} 分`
  return `${product.brand} ${product.productName} 好吃嗎？${verdict} | CVS Radar`
}

export function productPageDescription(product: Product): string {
  const summary = (product.excerpt || '').split('；')[0].trim()
  const price = product.price != null ? `售價 ${product.price} 元，` : ''
  const lead = `${product.brand}「${product.productName}」${price}整理 PTT CVS 板 ${product.nPosts} 篇心得、${product.eligibleComments} 則留言。`
  return summary ? `${lead}${summary}` : lead
}
