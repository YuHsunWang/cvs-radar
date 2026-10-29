// Central GA4 event helper. Components call these functions and never touch
// gtag directly; when NEXT_PUBLIC_GA_ID is unset (local dev, forks) every call
// is a silent no-op and no GA script is loaded at all (see app/layout.tsx).

export const GA_ID = process.env.NEXT_PUBLIC_GA_ID ?? ''

type GtagWindow = Window & {
  gtag?: (command: 'event', name: string, params?: Record<string, string | number>) => void
}

function trackEvent(name: string, params?: Record<string, string | number>) {
  if (!GA_ID || typeof window === 'undefined') return
  const gtag = (window as GtagWindow).gtag
  if (typeof gtag !== 'function') return
  gtag('event', name, params)
}

/** Buckets keep score params low-cardinality instead of leaking exact values. */
export function fairScoreBucket(score: number | null): string {
  if (score === null) return 'none'
  if (score >= 70) return '70+'
  if (score >= 50) return '50-69'
  return '<50'
}

export function trackSearch(query: string, resultCount: number) {
  const queryLength = query.trim().length
  if (!queryLength) return
  trackEvent('search', { query_length: queryLength, result_count: resultCount })
  // Text only for misses: those name products the site lacks, which is the content gap.
  if (resultCount === 0) trackEvent('search_no_result', { search_term: query.trim().slice(0, 50) })
}

/** A fresh visit that opens on a product from the URL, i.e. someone sent the link. */
export function trackSharedLinkLanding(productId: string) {
  trackEvent('shared_link_landing', { product_id: productId })
}

export function trackProductExpand(params: {
  productId: string
  brand: string
  category: string
  fairScore: number | null
}) {
  trackEvent('product_expand', {
    product_id: params.productId,
    brand: params.brand,
    category: params.category,
    fair_score_bucket: fairScoreBucket(params.fairScore),
  })
}

export function trackFilterApply(filterType: string, value: string) {
  trackEvent('filter_apply', { filter_type: filterType, value })
}

export function trackSortChange(sortKey: string) {
  trackEvent('sort_change', { sort_key: sortKey })
}

export function trackOutboundPttClick(productId: string) {
  trackEvent('outbound_ptt_click', { product_id: productId })
}

/** Measures whether shoppers read the label, to decide if more chains are worth scraping. */
export function trackNutritionOpen(productId: string, brand: string, fullLabel: boolean) {
  trackEvent('nutrition_open', {
    product_id: productId,
    brand,
    nutrition_type: fullLabel ? 'full' : 'kcal_only',
  })
}
