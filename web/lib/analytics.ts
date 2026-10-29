// Central GA4 event helper. Components call these functions and never touch
// gtag directly; when NEXT_PUBLIC_GA_ID is unset (local dev, forks) every call
// is a silent no-op and no GA script is loaded at all (see app/layout.tsx).

export const GA_ID = process.env.NEXT_PUBLIC_GA_ID ?? ''

import type { Product } from '@/lib/data'

type GtagParams = Record<string, string | number | Record<string, string | number>[]>

type GtagWindow = Window & {
  gtag?: (command: 'event', name: string, params?: GtagParams) => void
}

// gtag is defined by an afterInteractive script that runs after the page's mount
// effects, so events fired on load (shared-link landing, first impressions) wait here.
const pending: [string, GtagParams | undefined][] = []
let retryTimer: number | null = null

function trackEvent(name: string, params?: GtagParams) {
  if (!GA_ID || typeof window === 'undefined') return
  pending.push([name, params])
  flushPending()
}

function flushPending(attempt = 0) {
  const gtag = (window as GtagWindow).gtag
  if (typeof gtag === 'function') {
    for (const [name, params] of pending.splice(0)) gtag('event', name, params)
    return
  }
  // Give up after ~10s (blocked by an ad blocker, say) rather than retry forever.
  if (retryTimer !== null || attempt >= 40) return
  retryTimer = window.setTimeout(() => {
    retryTimer = null
    flushPending(attempt + 1)
  }, 250)
}

/** Buckets keep score params low-cardinality instead of leaking exact values. */
export function fairScoreBucket(score: number | null): string {
  if (score === null) return 'none'
  if (score >= 70) return '70+'
  if (score >= 50) return '50-69'
  return '<50'
}

// Zhuyin symbols and tone marks only appear while an IME is still composing; a
// pause mid-composition would otherwise log half-typed text as a no-result search.
export function hasUnfinishedZhuyin(query: string): boolean {
  return /[㄀-ㄯㆠ-ㆿˇˉ-ˋ˙]/.test(query)
}

export function trackSearch(query: string, resultCount: number) {
  const queryLength = query.trim().length
  if (!queryLength || hasUnfinishedZhuyin(query)) return
  trackEvent('search', { query_length: queryLength, result_count: resultCount })
  // Text only for misses: those name products the site lacks, which is the content gap.
  if (resultCount === 0) trackEvent('search_no_result', { search_term: query.trim().slice(0, 50) })
}

// Per-product CTR uses GA4's ecommerce list events, so the built-in
// itemsViewedInList / itemsClickedInList metrics work by itemId with no custom
// dimensions. `index` is the position in the current list: CTR is position-biased.
type ListedProduct = { product: Pick<Product, 'id' | 'productName' | 'brand' | 'category'>; index: number }

const LIST = { item_list_id: 'shelf', item_list_name: 'shelf' }
// Keeps each hit well under GA4's payload limit.
const ITEMS_PER_HIT = 30

function listItem({ product, index }: ListedProduct) {
  return {
    item_id: product.id,
    item_name: product.productName,
    item_brand: product.brand,
    item_category: product.category,
    index,
  }
}

export function trackListImpressions(listed: ListedProduct[]) {
  for (let start = 0; start < listed.length; start += ITEMS_PER_HIT) {
    trackEvent('view_item_list', { ...LIST, items: listed.slice(start, start + ITEMS_PER_HIT).map(listItem) })
  }
}

export function trackSelectItem(listed: ListedProduct) {
  trackEvent('select_item', { ...LIST, items: [listItem(listed)] })
}

/** Seconds a product's detail stayed open (visible tab only), capped so a forgotten tab can't skew averages. */
export function trackProductDwell(productId: string, brand: string, seconds: number) {
  trackEvent('product_dwell', { product_id: productId, brand, dwell_seconds: Math.min(Math.round(seconds), 1800) })
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
