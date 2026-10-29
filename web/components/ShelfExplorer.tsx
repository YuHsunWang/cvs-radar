'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { SlidersHorizontal, X } from 'lucide-react'
import SearchBar from '@/components/SearchBar'
import ShelfCard from '@/components/ShelfCard'
import {
  trackFilterApply,
  trackListImpressions,
  trackProductDwell,
  trackProductExpand,
  trackSearch,
  trackSelectItem,
  trackSharedLinkLanding,
  trackSortChange,
} from '@/lib/analytics'
import {
  AdvancedFilters,
  CategoryKey,
  DATA_STALE_DAYS,
  DataPayload,
  Product,
  SortKey,
  applyAdvanced,
  brands,
  categoryKeys,
  filterByBrand,
  filterByCategory,
  filterHasScore,
  filterBySearch,
  formatDisplayDate,
  isDataStale,
  sortProducts,
} from '@/lib/data'
import { DEFAULT_SORT, readViewParams, viewSearch } from '@/lib/view-url'

const PAGE_SIZE = 30

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
  { key: 'comprehensiveDesc', label: '評分高→低' },
  { key: 'comprehensiveAsc', label: '評分低→高' },
]

// Drag distance (px) past which a downward flick on the sheet handle closes it.
const SHEET_CLOSE_THRESHOLD = 110
// A downward flick faster than this (px/ms) closes the sheet even if it moved
// less than the threshold: judge the gesture by where it is going, not where it stopped.
const SHEET_FLICK_VELOCITY = 0.5
// Matches the .sl-sheet transform transition so the sheet leaves the way it came in.
const SHEET_EXIT_MS = 220

// Sort options with one dark pill that slides to the chosen option, so the
// change reads as "from here to there" instead of a jump.
function SortChips({ value, onChange }: { value: SortKey; onChange: (key: SortKey) => void }) {
  const navRef = useRef<HTMLElement>(null)
  const [pill, setPill] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  const [ready, setReady] = useState(false)

  useLayoutEffect(() => {
    const nav = navRef.current
    if (!nav) return
    const measure = () => {
      const active = nav.querySelector<HTMLElement>('[aria-pressed="true"]')
      if (!active || !active.offsetWidth) return
      setPill({ x: active.offsetLeft, y: active.offsetTop, w: active.offsetWidth, h: active.offsetHeight })
    }
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(nav)
    return () => observer?.disconnect()
  }, [value])

  // Place the pill once without motion; only later changes slide.
  useEffect(() => {
    if (pill && !ready) requestAnimationFrame(() => setReady(true))
  }, [pill, ready])

  return (
    <nav className="sl-chips sl-chips-sliding" aria-label="排序方式" ref={navRef}>
      {pill ? (
        <span
          className={`sl-chip-pill${ready ? ' sl-ready' : ''}`}
          aria-hidden="true"
          style={{ transform: `translate(${pill.x}px, ${pill.y}px)`, width: pill.w, height: pill.h }}
        />
      ) : null}
      {SORT_OPTIONS.map((option) => (
        <button
          key={option.key}
          type="button"
          className={`sl-datebtn${value === option.key ? ' sl-on' : ''}${pill ? ' sl-on-pill' : ''}`}
          aria-pressed={value === option.key}
          onClick={() => onChange(option.key)}
        >
          {option.label}
        </button>
      ))}
    </nav>
  )
}

// A number that pops its digits in (staggered) whenever it changes after first render.
function PopNumber({ value }: { value: number }) {
  const [prev, setPrev] = useState(value)
  const [tick, setTick] = useState(0)
  if (value !== prev) {
    setPrev(value)
    setTick((t) => t + 1)
  }
  return (
    <span className="sl-num" key={tick} data-pop={tick > 0 ? '' : undefined}>
      {String(value).split('').map((digit, i) => (
        <span key={i} style={{ '--i': i } as CSSProperties}>{digit}</span>
      ))}
    </span>
  )
}

type ShelfExplorerProps = {
  initialPayload: DataPayload
}

export default function ShelfExplorer({ initialPayload }: ShelfExplorerProps) {
  const [products] = useState<Product[]>(initialPayload.products)
  const [query, setQuery] = useState('')
  const [brand, setBrand] = useState<string | null>(null)
  const [category, setCategory] = useState<CategoryKey | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>(DEFAULT_SORT)
  const [hideNoScore, setHideNoScore] = useState(false)
  const [filters, setFilters] = useState<AdvancedFilters>({ fromDate: '', toDate: '' })
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [datePreset, setDatePreset] = useState<string>('all')
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetClosing, setSheetClosing] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [sheetSection, setSheetSection] = useState('category')
  const sheetBody = useRef<HTMLDivElement>(null)
  const inlineControls = useRef<HTMLDivElement>(null)
  // Drag-to-dismiss: track finger offset while dragging the sheet's grab handle.
  const [dragY, setDragY] = useState(0)
  const [dragging, setDragging] = useState(false)
  const dragStartY = useRef(0)
  const dragYRef = useRef(0)
  // Last two pointer samples, for release velocity.
  const lastMove = useRef({ y: 0, t: 0, v: 0 })
  // Ref mirrors `dragging` so move/end read it synchronously (state closure is
  // stale for the first pointermove fired before React re-renders).
  const draggingRef = useRef(false)
  // Client-only as well. The page is a static export rebuilt right after each data
  // refresh, so at build time the data is always fresh; only the visitor's clock can
  // tell that refreshes have stopped.
  const [dataStale, setDataStale] = useState(false)
  // The product most recently opened, carried in the URL so the address bar shares it.
  const [openedId, setOpenedId] = useState<string | null>(null)
  // URL writes wait until the shared view has been read, or the first render would erase it.
  const [restored, setRestored] = useState(false)
  const pendingScroll = useRef<string | null>(null)
  // Analytics bookkeeping only; none of it drives rendering.
  const seen = useRef(new Set<string>())
  const clicked = useRef(new Set<string>())
  const impressionQueue = useRef<{ product: Product; index: number }[]>([])
  const dwellStart = useRef(new Map<string, { brand: string; since: number }>())

  // `paused` keeps the entry so the clock restarts when the tab is visible again.
  function endDwell(id: string, paused = false) {
    const entry = dwellStart.current.get(id)
    if (!entry) return
    trackProductDwell(id, entry.brand, (Date.now() - entry.since) / 1000)
    if (!paused) dwellStart.current.delete(id)
  }

  function openSheet(section = 'sort') {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setSheetClosing(false)
    setSheetSection(section)
    dragYRef.current = 0
    setDragY(0)
    setSheetOpen(true)
  }
  // Phones reach the filters through the sheet; wider screens already show the
  // inline bar, so send them there rather than open a surface CSS keeps hidden.
  function revealSection(section = 'category') {
    const bar = inlineControls.current
    if (bar && getComputedStyle(bar).display !== 'none') {
      const group = bar.querySelector<HTMLElement>(`[data-section="${section}"]`)
      group?.scrollIntoView({ block: 'nearest' })
      group?.querySelector<HTMLElement>('button, input')?.focus()
      return
    }
    openSheet(section)
  }

  function finishClose() {
    closeTimer.current = null
    setSheetOpen(false)
    setSheetClosing(false)
    dragYRef.current = 0
    setDragY(0)
  }
  function closeSheet() {
    if (closeTimer.current) return
    const reduceMotion = typeof window !== 'undefined'
      && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduceMotion) {
      finishClose()
      return
    }
    // Slide out from wherever the sheet is now (including mid-drag), then unmount.
    setSheetClosing(true)
    closeTimer.current = setTimeout(finishClose, SHEET_EXIT_MS)
  }

  function onSheetDragStart(event: ReactPointerEvent<HTMLDivElement>) {
    dragStartY.current = event.clientY
    lastMove.current = { y: event.clientY, t: event.timeStamp, v: 0 }
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
    const dt = event.timeStamp - lastMove.current.t
    if (dt > 0) {
      lastMove.current = { y: event.clientY, t: event.timeStamp, v: (event.clientY - lastMove.current.y) / dt }
    }
    dragYRef.current = offset
    setDragY(offset)
  }
  function onSheetDragEnd(event: ReactPointerEvent<HTMLDivElement>) {
    if (!draggingRef.current) return
    draggingRef.current = false
    setDragging(false)
    // A finger that paused before lifting has no momentum left.
    const flicked = event.timeStamp - lastMove.current.t < 100 && lastMove.current.v > SHEET_FLICK_VELOCITY
    if (dragYRef.current > SHEET_CLOSE_THRESHOLD || flicked) {
      closeSheet()
    } else {
      setDragY(0)
    }
    dragYRef.current = 0
  }

  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
  }, [])

  useEffect(() => {
    setDataStale(isDataStale(initialPayload.generatedAt))
  }, [initialPayload.generatedAt])

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

  useEffect(() => {
    if (!sheetOpen) return
    sheetBody.current?.querySelector(`[data-section="${sheetSection}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [sheetOpen, sheetSection])

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

  // Static export: only the client sees the query string, so restore it after mount.
  useEffect(() => {
    const view = readViewParams(window.location.search)
    setQuery(view.query)
    setBrand(view.brand)
    setCategory(view.category)
    setSortKey(view.sortKey)
    setHideNoScore(view.hideNoScore)
    const preset = DATE_PRESETS.find((item) => item.key === view.datePreset)
    if (preset && preset.key !== 'all') {
      setDatePreset(preset.key)
      setFilters({ fromDate: preset.from(), toDate: '' })
    }
    if (view.product) {
      // The URL keeps the open product while browsing, so a reload or back/forward
      // would also land here; only a plain navigation counts as a shared link.
      const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
      if (nav?.type === 'navigate') trackSharedLinkLanding(view.product)
      setExpanded(new Set([view.product]))
      setOpenedId(view.product)
      pendingScroll.current = view.product
    }
    setRestored(true)
  }, [])

  useEffect(() => {
    if (!restored) return
    const search = viewSearch({ query, brand, category, datePreset, sortKey, hideNoScore, product: openedId })
    window.history.replaceState(null, '', `${window.location.pathname}${search}`)
  }, [restored, query, brand, category, datePreset, sortKey, hideNoScore, openedId])

  // A shared product may sit past the first page: grow the list to it, then scroll there.
  // Gated on `restored`: the restore effect's state lands one render later, and
  // reading the default ordering first would consume the scroll at the wrong index.
  useEffect(() => {
    const id = pendingScroll.current
    if (!restored || !id) return
    const index = visibleProducts.findIndex((product) => product.id === id)
    if (index < 0) {
      pendingScroll.current = null
      return
    }
    if (index >= visibleCount) {
      setVisibleCount(index + 1)
      return
    }
    pendingScroll.current = null
    document.getElementById(`p-${id}`)?.scrollIntoView({ block: 'start' })
  }, [restored, visibleProducts, visibleCount])

  const searchHitCount = useMemo(() => filterBySearch(products, query).length, [products, query])

  useEffect(() => {
    if (!query.trim()) return
    const timer = window.setTimeout(() => trackSearch(query, searchHitCount), 800)
    return () => window.clearTimeout(timer)
  }, [query, searchHitCount])

  const displayedProducts = visibleProducts.slice(0, visibleCount)

  // A card counts as seen once per visit, when half of it is on screen. Batched,
  // because a fast scroll would otherwise send one hit per card.
  useEffect(() => {
    const byId = new Map(displayedProducts.map((product, index) => [product.id, { product, index }]))
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const id = entry.target.id.slice(2)
        const listed = byId.get(id)
        observer.unobserve(entry.target)
        if (!listed || seen.current.has(id)) continue
        seen.current.add(id)
        impressionQueue.current.push(listed)
      }
    }, { threshold: 0.5 })
    for (const product of displayedProducts) {
      if (seen.current.has(product.id)) continue
      const card = document.getElementById(`p-${product.id}`)
      if (card) observer.observe(card)
    }
    return () => observer.disconnect()
  }, [displayedProducts])

  useEffect(() => {
    const flush = () => {
      if (impressionQueue.current.length) trackListImpressions(impressionQueue.current.splice(0))
    }
    const timer = window.setInterval(flush, 3000)
    // Hidden tab: send what is pending and stop the dwell clocks; restart them on return.
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        flush()
        for (const id of Array.from(dwellStart.current.keys())) endDwell(id, true)
      } else {
        for (const entry of Array.from(dwellStart.current.values())) entry.since = Date.now()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

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

  function toggleProduct(product: Product, index: number) {
    const closing = expanded.has(product.id)
    if (closing) {
      endDwell(product.id)
    } else {
      dwellStart.current.set(product.id, { brand: product.brand, since: Date.now() })
      // Once per product per visit, matching impressions, so CTR stays a share of viewers.
      if (!clicked.current.has(product.id)) {
        clicked.current.add(product.id)
        trackSelectItem({ product, index })
      }
    }
    setOpenedId((current) => (closing ? (current === product.id ? null : current) : product.id))
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

  function toggleBrand(name: string) {
    const next = brand === name ? null : name
    setBrand(next)
    resetPage()
    if (next) trackFilterApply('brand', next)
  }

  function toggleCategory(key: CategoryKey) {
    const next = category === key ? null : key
    setCategory(next)
    resetPage()
    if (next) trackFilterApply('category', next)
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
    <div className="sl-filterrow" data-section="category">
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
            onClick={() => toggleCategory(key)}
          >
            {key}
          </button>
        ))}
      </nav>
    </div>
  )

  const brandGroup = (
    <div className="sl-filterrow" data-section="brand">
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
              className={`sl-chip-btn${brand === name ? ' sl-on' : ''}`}
              onClick={() => toggleBrand(name)}
            >
              {name}
            </button>
        ))}
      </nav>
    </div>
  )

  const dateGroup = (
    <div className="sl-filterrow" data-section="date">
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
    <div className="sl-filterrow" data-section="sort">
      <span className="sl-eyebrow">排序</span>
      <SortChips
        value={sortKey}
        onChange={(key) => {
          setSortKey(key)
          resetPage()
          trackSortChange(key)
        }}
      />
    </div>
  )

  const hideToggle = (
    <label className="sl-check" data-section="score">
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
          <h1 className="sl-sign-title">
            <span className="sl-logo" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M12 12l6-6" />
                <path d="M20 12a8 8 0 1 1-8-8" />
                <path d="M16 12a4 4 0 1 1-4-4" />
              </svg>
            </span>
            超商雷達
          </h1>
        </div>
        <span className="sl-update-date">{initialPayload.generatedAt ? `${formatDisplayDate(initialPayload.generatedAt)} 更新` : '更新時間不明'}</span>
        <div className="sl-searchwrap">
          <SearchBar
            value={query}
            onChange={(value) => {
              setQuery(value)
              resetPage()
            }}
          />
        </div>
      </header>

      {/* Phones only: one-tap brand and category toggles, so the common filters
          don't sit behind the sheet. The "其他" buckets stay in the sheet. */}
      <nav className="sl-quick" aria-label="快速篩選">
        {brands.filter((name) => name !== '其他').map((name) => (
          <button
            key={name}
            type="button"
            className={`sl-quick-btn${brand === name ? ' sl-on' : ''}`}
            aria-pressed={brand === name}
            onClick={() => toggleBrand(name)}
          >
            {name}
          </button>
        ))}
        <span className="sl-quick-sep" aria-hidden="true" />
        {categoryKeys.filter((key) => key !== '其他').map((key) => (
          <button
            key={key}
            type="button"
            className={`sl-quick-btn${category === key ? ' sl-on' : ''}`}
            aria-pressed={category === key}
            onClick={() => toggleCategory(key)}
          >
            {key}
          </button>
        ))}
      </nav>

      {dataStale ? (
        <div className="sl-aislebar">
          <span className="sl-ab-stale" role="status">
            已超過 {DATA_STALE_DAYS} 天未更新
          </span>
        </div>
      ) : null}

      {/* Desktop / wide screens: filters inline. Hidden on mobile (sheet used). */}
      <div className="sl-controls" ref={inlineControls}>
        {categoryGroup}
        {brandGroup}
        {dateGroup}
        {sortGroup}
        <div className="sl-toolbar-row">{hideToggle}</div>
      </div>

      {/* Phones only (CSS hides it on wide screens, where the inline bar already
          shows every choice): names what the sheet has applied. */}
      {activeFilterCount > 0 ? (
        <div className="sl-count">
          <span className="sl-active-context">
            {brand ? <button type="button" className="sl-context-button" onClick={() => revealSection('brand')}>品牌：{brand}</button> : null}
            {category ? <button type="button" className="sl-context-button" onClick={() => revealSection('category')}>分類：{category}</button> : null}
            {datePreset !== 'all' ? <button type="button" className="sl-context-button" onClick={() => revealSection('date')}>最新心得：{DATE_PRESETS.find((preset) => preset.key === datePreset)?.label}</button> : null}
            {hideNoScore ? <button type="button" className="sl-context-button" onClick={() => revealSection('score')}>隱藏暫無綜合評分</button> : null}
          </span>
        </div>
      ) : null}

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
                isExpanded={expanded.has(product.id)}
                onToggle={() => toggleProduct(product, index)}
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
        <p>評分只根據 PTT CVS 板的心得文與留言計算，不針對個別商品調分；僅供選購參考。</p>
      </footer>

      {/* Mobile only: floating filter button + bottom sheet. */}
      <button
        type="button"
        className="sl-fab"
        aria-label={`排序與篩選${activeFilterCount ? `（已套用 ${activeFilterCount} 項）` : ''}`}
        aria-expanded={sheetOpen}
        onClick={() => openSheet()}
      >
        <SlidersHorizontal size={22} aria-hidden="true" />
        <span>排序・篩選</span>
        {activeFilterCount > 0 ? <span className="sl-fab-badge">{activeFilterCount}</span> : null}
      </button>

      {sheetOpen ? (
        <div className={`sl-sheet-backdrop${sheetClosing ? ' sl-closing' : ''}`} onClick={closeSheet}>
          <div
            className={`sl-sheet${dragging ? ' sl-dragging' : ''}${sheetClosing ? ' sl-closing' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-label="排序與篩選"
            onClick={(event) => event.stopPropagation()}
            style={
              sheetClosing
                ? ({ '--sl-from': `${dragY}px` } as CSSProperties)
                : dragY ? ({ transform: `translateY(${dragY}px)` } as CSSProperties) : undefined
            }
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
                <span className="sl-sheet-title">排序與篩選</span>
                <button
                  type="button"
                  className="sl-sheet-x"
                  aria-label="關閉排序與篩選"
                  onClick={closeSheet}
                >
                  <X size={20} aria-hidden="true" />
                </button>
              </div>
            </div>
            <div className="sl-sheet-body" ref={sheetBody}>
              {sortGroup}
              {categoryGroup}
              {brandGroup}
              {dateGroup}
              {hideToggle}
            </div>
            <div className="sl-sheet-foot">
              <button type="button" className="sl-sheet-clear" onClick={clearAll}>
                清除
              </button>
              <button type="button" className="sl-sheet-apply" onClick={closeSheet}>
                看 <PopNumber value={visibleProducts.length} /> 項結果
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
