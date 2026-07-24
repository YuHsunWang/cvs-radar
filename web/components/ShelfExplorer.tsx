'use client'

import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { SlidersHorizontal, X } from 'lucide-react'
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
  美廉社: '#6C3DBF',
  其他: '#6B7280',
}
// 美聯社 in lib/data is a typo for 美廉社 and has no products — hide it for now.
const HIDDEN_BRANDS = new Set(['美聯社'])

function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function isoMonthsAgo(months: number): string {
  const d = new Date()
  d.setMonth(d.getMonth() - months)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const DATE_PRESETS = [
  { key: 'all', label: '不限', from: () => '' },
  { key: '3m', label: '近三個月', from: () => isoMonthsAgo(3) },
  { key: '1m', label: '近一個月', from: () => isoMonthsAgo(1) },
  { key: '2w', label: '近兩週', from: () => isoDaysAgo(14) },
  { key: '1w', label: '近一週', from: () => isoDaysAgo(7) },
] as const

const SORT_OPTIONS: readonly { key: SortKey; label: string }[] = [
  { key: 'recentRecommendationDesc', label: '近期推薦' },
  { key: 'discussionHeatDesc', label: '討論熱度' },
  { key: 'fairScoreDesc', label: '評分高→低' },
  { key: 'fairScoreAsc', label: '評分低→高' },
]

// Drag distance (px) past which a downward flick on the sheet handle closes it.
const SHEET_CLOSE_THRESHOLD = 110

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
  const [datePreset, setDatePreset] = useState<string>('all')
  const [sheetOpen, setSheetOpen] = useState(false)
  // Drag-to-dismiss: track finger offset while dragging the sheet's grab handle.
  const [dragY, setDragY] = useState(0)
  const [dragging, setDragging] = useState(false)
  const dragStartY = useRef(0)
  const dragYRef = useRef(0)
  // Ref mirrors `dragging` so move/end read it synchronously (state closure is
  // stale for the first pointermove fired before React re-renders).
  const draggingRef = useRef(false)
  // Client-only store clock (24h konbini). Starts blank so SSR/CSR markup matches.
  const [clock, setClock] = useState<{ time: string; day: string }>({ time: '--:--:--', day: '' })

  function openSheet() {
    dragYRef.current = 0
    setDragY(0)
    setSheetOpen(true)
  }
  function closeSheet() {
    setSheetOpen(false)
    dragYRef.current = 0
    setDragY(0)
  }

  function onSheetDragStart(event: ReactPointerEvent<HTMLDivElement>) {
    dragStartY.current = event.clientY
    draggingRef.current = true
    setDragging(true)
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // Pointer capture is best-effort; drag still works without it.
    }
  }
  function onSheetDragMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!draggingRef.current) return
    const offset = Math.max(0, event.clientY - dragStartY.current)
    dragYRef.current = offset
    setDragY(offset)
  }
  function onSheetDragEnd() {
    if (!draggingRef.current) return
    draggingRef.current = false
    setDragging(false)
    if (dragYRef.current > SHEET_CLOSE_THRESHOLD) {
      closeSheet()
    } else {
      setDragY(0)
    }
    dragYRef.current = 0
  }

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

  // Lock body scroll and wire Escape-to-close while the filter sheet is open.
  useEffect(() => {
    if (!sheetOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeSheet()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [sheetOpen])

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

  const displayedProducts = visibleProducts.slice(0, visibleCount)
  const remainingCount = visibleProducts.length - displayedProducts.length
  const activeFilterCount =
    (category ? 1 : 0) + (brand ? 1 : 0) + (datePreset !== 'all' ? 1 : 0) + (hideNoScore ? 1 : 0)

  function resetPage() {
    setVisibleCount(PAGE_SIZE)
  }

  function applyDatePreset(preset: (typeof DATE_PRESETS)[number]) {
    setDatePreset(preset.key)
    setFilters({ fromDate: preset.from(), toDate: '' })
    resetPage()
    if (preset.key !== 'all') trackFilterApply('date_range', preset.key)
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
    setDatePreset('all')
    resetPage()
  }

  // Filter groups defined once, then placed both in the desktop bar and the
  // mobile sheet (same element rendered in two parents = two live instances).
  const categoryGroup = (
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
  )

  const brandGroup = (
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
        {brands
          .filter((name) => !HIDDEN_BRANDS.has(name))
          .map((name) => (
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
  )

  const dateGroup = (
    <div className="sl-filterrow">
      <span className="sl-eyebrow">日期</span>
      <nav className="sl-chips" aria-label="最新發文日期">
        {DATE_PRESETS.map((preset) => (
          <button
            key={preset.key}
            type="button"
            className={`sl-datebtn${datePreset === preset.key ? ' sl-on' : ''}`}
            onClick={() => applyDatePreset(preset)}
          >
            {preset.label}
          </button>
        ))}
      </nav>
    </div>
  )

  const sortGroup = (
    <div className="sl-filterrow">
      <span className="sl-eyebrow">排序</span>
      <nav className="sl-chips" aria-label="排序方式">
        {SORT_OPTIONS.map((option) => (
          <button
            key={option.key}
            type="button"
            className={`sl-datebtn${sortKey === option.key ? ' sl-on' : ''}`}
            aria-pressed={sortKey === option.key}
            onClick={() => {
              setSortKey(option.key)
              resetPage()
              trackSortChange(option.key)
            }}
          >
            {option.label}
          </button>
        ))}
      </nav>
    </div>
  )

  const hideToggle = (
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
  )

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

      <div className="sl-searchwrap">
        <SearchBar
          value={query}
          onChange={(value) => {
            setQuery(value)
            resetPage()
          }}
        />
      </div>

      {/* Desktop / wide screens: filters inline. Hidden on mobile (sheet used). */}
      <div className="sl-controls">
        {categoryGroup}
        {brandGroup}
        {dateGroup}
        {sortGroup}
        <div className="sl-toolbar-row">{hideToggle}</div>
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

      {/* Mobile only: floating filter button + bottom sheet. */}
      <button
        type="button"
        className="sl-fab"
        aria-label={`篩選${activeFilterCount ? `（已套用 ${activeFilterCount} 項）` : ''}`}
        aria-expanded={sheetOpen}
        onClick={openSheet}
      >
        <SlidersHorizontal size={22} aria-hidden="true" />
        {activeFilterCount > 0 ? <span className="sl-fab-badge">{activeFilterCount}</span> : null}
      </button>

      {sheetOpen ? (
        <div className="sl-sheet-backdrop" onClick={closeSheet}>
          <div
            className={`sl-sheet${dragging ? ' sl-dragging' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-label="篩選"
            onClick={(event) => event.stopPropagation()}
            style={dragY ? ({ transform: `translateY(${dragY}px)` } as CSSProperties) : undefined}
          >
            {/* Grab handle — drag it down past the threshold to dismiss. */}
            <div
              className="sl-sheet-head"
              onPointerDown={onSheetDragStart}
              onPointerMove={onSheetDragMove}
              onPointerUp={onSheetDragEnd}
              onPointerCancel={onSheetDragEnd}
            >
              <span className="sl-grabber" aria-hidden="true" />
              <div className="sl-sheet-headrow">
                <span className="sl-sheet-title">篩選</span>
                <button
                  type="button"
                  className="sl-sheet-x"
                  aria-label="關閉篩選"
                  onClick={closeSheet}
                >
                  <X size={20} aria-hidden="true" />
                </button>
              </div>
            </div>
            <div className="sl-sheet-body">
              {categoryGroup}
              {brandGroup}
              {dateGroup}
              {sortGroup}
              {hideToggle}
            </div>
            <div className="sl-sheet-foot">
              <button type="button" className="sl-sheet-clear" onClick={clearAll}>
                清除
              </button>
              <button type="button" className="sl-sheet-apply" onClick={closeSheet}>
                看 {visibleProducts.length} 項結果
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
