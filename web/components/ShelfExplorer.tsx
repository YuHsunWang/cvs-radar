'use client'

import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { ChevronDown, SlidersHorizontal } from 'lucide-react'
import DateRangeSlider from '@/components/DateRangeSlider'
import SearchBar from '@/components/SearchBar'
import ShelfCard from '@/components/ShelfCard'
import {
  trackFilterApply,
  trackProductExpand,
  trackSearch,
  trackSortChange,
} from '@/lib/analytics'
import {
  AdvancedFilters,
  CategoryKey,
  DataPayload,
  Product,
  SortKey,
  applyAdvanced,
  brands,
  categoryKeys,
  displayBrand,
  filterByBrand,
  filterByCategory,
  filterHasScore,
  filterBySearch,
  formatDisplayDate,
  sortProducts,
} from '@/lib/data'

const PAGE_SIZE = 30

// Rail colours mirror ShelfCard so an active brand chip wears its shelf colour.
const BRAND_RAIL: Record<string, string> = {
  '7-11': '#F26522',
  全家: '#009B4C',
  萊爾富: '#E51F26',
  OK: '#F5A623',
  美聯社: '#6C3DBF',
  其他: '#6B7280',
}

type ShelfExplorerProps = {
  initialPayload: DataPayload
}

export default function ShelfExplorer({ initialPayload }: ShelfExplorerProps) {
  const [products] = useState<Product[]>(initialPayload.products)
  const [query, setQuery] = useState('')
  const [brand, setBrand] = useState<string | null>(null)
  const [category, setCategory] = useState<CategoryKey | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('recentRecommendationDesc')
  const [hideNoScore, setHideNoScore] = useState(false)
  const [filters, setFilters] = useState<AdvancedFilters>({ fromDate: '', toDate: '' })
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  // Client-only store clock (24h konbini). Starts blank so SSR/CSR markup matches.
  const [clock, setClock] = useState<{ time: string; day: string }>({ time: '--:--:--', day: '' })

  useEffect(() => {
    const tick = () => {
      const timeFmt = new Intl.DateTimeFormat('zh-TW', {
        timeZone: 'Asia/Taipei',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
      const dayFmt = new Intl.DateTimeFormat('zh-TW', { timeZone: 'Asia/Taipei', weekday: 'short' })
      const now = new Date()
      setClock({ time: timeFmt.format(now), day: dayFmt.format(now) })
    }
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [])

  const advancedActive = Boolean(filters.fromDate || filters.toDate || hideNoScore)

  const visibleProducts = useMemo(() => {
    return sortProducts(
      applyAdvanced(
        filterHasScore(
          filterByCategory(filterByBrand(filterBySearch(products, query), brand), category),
          hideNoScore,
        ),
        filters,
      ),
      sortKey,
    )
  }, [brand, category, filters, hideNoScore, products, query, sortKey])

  const searchHitCount = useMemo(() => filterBySearch(products, query).length, [products, query])

  useEffect(() => {
    if (!query.trim()) return
    const timer = window.setTimeout(() => trackSearch(query, searchHitCount), 800)
    return () => window.clearTimeout(timer)
  }, [query, searchHitCount])

  const dateBounds = useMemo(() => {
    const dates = products.flatMap((product) => (product.latestDate ? [product.latestDate] : []))
    return {
      minDate: dates.length ? dates.reduce((earliest, date) => (date < earliest ? date : earliest)) : '',
      maxDate: dates.length ? dates.reduce((latest, date) => (date > latest ? date : latest)) : '',
    }
  }, [products])

  const displayedProducts = visibleProducts.slice(0, visibleCount)
  const remainingCount = visibleProducts.length - displayedProducts.length

  function resetPage() {
    setVisibleCount(PAGE_SIZE)
  }

  function toggleProduct(product: Product) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(product.id)) {
        next.delete(product.id)
      } else {
        next.add(product.id)
        trackProductExpand({
          productId: product.id,
          brand: product.brand,
          category: product.category,
          fairScore: product.fairScore,
        })
      }
      return next
    })
  }

  function clearAll() {
    setQuery('')
    setBrand(null)
    setCategory(null)
    setHideNoScore(false)
    setFilters({ fromDate: '', toDate: '' })
    resetPage()
  }

  return (
    <div className="sl-page">
      <header className="sl-sign">
        <div className="sl-sign-main">
          <div className="sl-sign-mark" aria-hidden="true">
            <span className="sl-sweep" />
          </div>
          <div>
            <p className="sl-sign-kicker">便利商店・新品貨架</p>
            <h1 className="sl-sign-title">
              貨架雷達 <span>CVS&nbsp;RADAR</span>
            </h1>
          </div>
        </div>
        <div className="sl-sign-stamp">
          <span className="sl-clock-time" aria-label={`目前時間 ${clock.time}`}>
            {clock.time}
          </span>
          <span className="sl-st-line">24H 營業中{clock.day ? ` · ${clock.day}` : ''}</span>
        </div>
      </header>

      <div className="sl-aislebar">
        <span className="sl-ab-slot">本區 {products.length} 品</span>
        <span className="sl-ab-sep">·</span>
        <span>上架更新 {formatDisplayDate(initialPayload.generatedAt)}</span>
        <span className="sl-ab-sep">·</span>
        <span>分數＝綜合評分／滿分 100</span>
      </div>

      <div className="sl-controls">
        <div className="sl-searchrow">
          <SearchBar
            value={query}
            onChange={(value) => {
              setQuery(value)
              resetPage()
            }}
          />
          <div className="sl-select-wrap">
            <label className="sr-only" htmlFor="sl-sort">
              排序
            </label>
            <select
              id="sl-sort"
              className="sl-select"
              value={sortKey}
              onChange={(event) => {
                setSortKey(event.target.value as SortKey)
                resetPage()
                trackSortChange(event.target.value)
              }}
            >
              <option value="recentRecommendationDesc">近期推薦</option>
              <option value="discussionHeatDesc">討論熱度</option>
              <option value="fairScoreDesc">評分 高→低</option>
              <option value="fairScoreAsc">評分 低→高</option>
            </select>
          </div>
        </div>

        <div className="sl-filterrow">
          <span className="sl-eyebrow">分類</span>
          <nav className="sl-chips" aria-label="分類">
            <button
              type="button"
              className={`sl-chip-btn${category === null ? ' sl-on' : ''}`}
              onClick={() => {
                setCategory(null)
                resetPage()
              }}
            >
              全部
            </button>
            {categoryKeys.map((key) => (
              <button
                key={key}
                type="button"
                className={`sl-chip-btn${category === key ? ' sl-on' : ''}`}
                onClick={() => {
                  const next = category === key ? null : key
                  setCategory(next)
                  resetPage()
                  if (next) trackFilterApply('category', next)
                }}
              >
                {key}
              </button>
            ))}
          </nav>
        </div>

        <div className="sl-filterrow">
          <span className="sl-eyebrow">品牌</span>
          <nav className="sl-chips" aria-label="品牌">
            <button
              type="button"
              className={`sl-chip-btn${brand === null ? ' sl-on' : ''}`}
              onClick={() => {
                setBrand(null)
                resetPage()
              }}
            >
              全部
            </button>
            {brands.map((name) => (
              <button
                key={name}
                type="button"
                className={`sl-chip-btn sl-brand${brand === name ? ' sl-on' : ''}`}
                style={
                  brand === name
                    ? ({ '--sl-brand': BRAND_RAIL[displayBrand(name)] } as CSSProperties)
                    : undefined
                }
                onClick={() => {
                  const next = brand === name ? null : name
                  setBrand(next)
                  resetPage()
                  if (next) trackFilterApply('brand', next)
                }}
              >
                {name}
              </button>
            ))}
          </nav>
        </div>

        <div className="sl-advanced">
          <button
            type="button"
            className="sl-adv-toggle"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((open) => !open)}
          >
            <SlidersHorizontal size={16} aria-hidden="true" />
            進階篩選
            {advancedActive ? <span className="sl-dot" aria-hidden="true" /> : null}
            <ChevronDown
              size={16}
              aria-hidden="true"
              className={`sl-caret${advancedOpen ? ' sl-caret-open' : ''}`}
            />
          </button>
          {advancedOpen ? (
            <div className="sl-adv-panel">
              <DateRangeSlider
                dateBounds={dateBounds}
                fromDate={filters.fromDate}
                toDate={filters.toDate}
                onChange={(range) => {
                  setFilters((current) => ({ ...current, ...range }))
                  resetPage()
                  trackFilterApply('date_range', 'adjusted')
                }}
              />
              <label className="sl-check">
                <input
                  type="checkbox"
                  checked={hideNoScore}
                  onChange={(event) => {
                    setHideNoScore(event.target.checked)
                    resetPage()
                    if (event.target.checked) trackFilterApply('hide_no_score', 'on')
                  }}
                />
                隱藏暫無綜合評分
              </label>
            </div>
          ) : null}
        </div>
      </div>

      <p className="sl-count" aria-live="polite">
        找到 <b>{visibleProducts.length}</b> 項商品
      </p>

      <main className="sl-shelf">
        {visibleProducts.length === 0 ? (
          <div className="sl-empty">
            <p>沒有符合條件的商品</p>
            <button type="button" onClick={clearAll}>
              清除搜尋與篩選
            </button>
          </div>
        ) : (
          <>
            {displayedProducts.map((product, index) => (
              <ShelfCard
                key={product.id}
                product={product}
                rank={index + 1}
                isExpanded={expanded.has(product.id)}
                onToggle={() => toggleProduct(product)}
              />
            ))}
            {remainingCount > 0 ? (
              <div className="sl-loadmore">
                <p>
                  已顯示 {displayedProducts.length} / {visibleProducts.length} 項
                </p>
                <button type="button" onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}>
                  再顯示 {Math.min(PAGE_SIZE, remainingCount)} 項
                </button>
              </div>
            ) : null}
          </>
        )}
      </main>

      <footer className="sl-foot">
        <p>資料來自公開使用者內容，僅供選購參考；本頁為 CVS Radar 的介面設計試作，非官方評鑑。</p>
        <p className="sl-foot-mono">
          SHELF-EDGE LABEL VARIANT · 資料更新 {formatDisplayDate(initialPayload.generatedAt)} ·{' '}
          <a href="/classic">經典版</a>
        </p>
      </footer>
    </div>
  )
}
