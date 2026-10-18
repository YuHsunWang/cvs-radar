import { CategoryKey, SortKey, brands, categoryKeys } from './data'

/**
 * The shelf view a link can carry: search, filters, sort and one opened product.
 * Only non-default values go into the query string, so a plain visit stays `/`.
 */
export type ViewState = {
  query: string
  brand: string | null
  category: CategoryKey | null
  datePreset: string
  sortKey: SortKey
  hideNoScore: boolean
  product: string | null
}

export const DEFAULT_SORT: SortKey = 'recentRecommendationDesc'
const SORT_KEYS: readonly SortKey[] = ['recentRecommendationDesc', 'discussionHeatDesc', 'comprehensiveDesc', 'comprehensiveAsc']
const DATE_KEYS = ['all', '3m', '1m', '2w', '1w']

export function readViewParams(search: string): ViewState {
  const params = new URLSearchParams(search)
  const pick = <T extends string>(key: string, allowed: readonly T[]): T | null => {
    const value = params.get(key)
    return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null
  }
  // Hand-edited or stale links fall back to defaults instead of producing an empty shelf.
  return {
    query: params.get('q') ?? '',
    brand: pick('brand', brands),
    category: pick('cat', categoryKeys),
    datePreset: pick('date', DATE_KEYS) ?? 'all',
    sortKey: pick('sort', SORT_KEYS) ?? DEFAULT_SORT,
    hideNoScore: params.get('hide') === '1',
    product: params.get('p') || null,
  }
}

export function viewSearch(state: ViewState): string {
  const params = new URLSearchParams()
  if (state.query.trim()) params.set('q', state.query.trim())
  if (state.brand) params.set('brand', state.brand)
  if (state.category) params.set('cat', state.category)
  if (state.datePreset !== 'all') params.set('date', state.datePreset)
  if (state.sortKey !== DEFAULT_SORT) params.set('sort', state.sortKey)
  if (state.hideNoScore) params.set('hide', '1')
  if (state.product) params.set('p', state.product)
  const search = params.toString()
  return search ? `?${search}` : ''
}
