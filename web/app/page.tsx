'use client'

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, FileText, X } from 'lucide-react'
import BrandChips from '@/components/BrandChips'
import CategoryChips from '@/components/CategoryChips'
import FilterSheet from '@/components/FilterSheet'
import ProductCard from '@/components/ProductCard'
import SearchBar from '@/components/SearchBar'
import TopBar from '@/components/TopBar'
import {
  AdvancedFilters,
  CategoryKey,
  Product,
  SortKey,
  applyAdvanced,
  filterByBrand,
  filterByCategory,
  filterBySearch,
  formatDisplayDate,
  loadProducts,
  sortProducts,
} from '@/lib/data'

const PAGE_SIZE = 30

export default function HomePage() {
  const [products, setProducts] = useState<Product[]>([])
  const [query, setQuery] = useState('')
  const [brand, setBrand] = useState<string | null>(null)
  const [category, setCategory] = useState<CategoryKey | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('fairScoreDesc')
  const [filters, setFilters] = useState<AdvancedFilters>({ minScore: 0, fromDate: '', toDate: '' })
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [isSheetOpen, setIsSheetOpen] = useState(false)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [generatedAt, setGeneratedAt] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    loadProducts()
      .then((payload) => {
        if (!mounted) return
        setProducts(payload.products)
        setGeneratedAt(payload.generatedAt)
      })
      .catch((err: unknown) => {
        if (!mounted) return
        setError(err instanceof Error ? err.message : '資料載入失敗')
      })
      .finally(() => {
        if (mounted) setIsLoading(false)
      })

    return () => {
      mounted = false
    }
  }, [])

  const visibleProducts = useMemo(() => {
    return sortProducts(
      applyAdvanced(
        filterByCategory(filterByBrand(filterBySearch(products, query), brand), category),
        filters,
      ),
      sortKey,
    )
  }, [brand, category, filters, products, query, sortKey])

  const dateBounds = useMemo(() => {
    const dates = products.flatMap((product) => (product.latestDate ? [product.latestDate] : []))
    return {
      minDate: dates.length ? dates.reduce((earliest, date) => (date < earliest ? date : earliest)) : '',
      maxDate: dates.length ? dates.reduce((latest, date) => (date > latest ? date : latest)) : '',
    }
  }, [products])

  const activeFilterLabels = useMemo(() => {
    const labels: string[] = []
    if (filters.minScore > 0) labels.push(`最低推薦分 ${filters.minScore}`)
    if (filters.fromDate && filters.toDate) {
      labels.push(`最新發文 ${formatDisplayDate(filters.fromDate)}–${formatDisplayDate(filters.toDate)}`)
    } else if (filters.fromDate) {
      labels.push(`最新發文自 ${formatDisplayDate(filters.fromDate)}`)
    } else if (filters.toDate) {
      labels.push(`最新發文至 ${formatDisplayDate(filters.toDate)}`)
    }
    return labels
  }, [filters])

  const displayedProducts = visibleProducts.slice(0, visibleCount)
  const remainingCount = visibleProducts.length - displayedProducts.length

  function toggleProduct(id: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  return (
    <main className="min-h-screen bg-[#F7F5EF] text-slate-900">
      <div className="mx-auto min-h-screen w-full max-w-[430px] bg-[#FCFAF5] shadow-2xl shadow-slate-300/50">
        <TopBar
          activeFilterCount={activeFilterLabels.length}
          brand={brand}
          category={category}
          generatedAt={generatedAt}
          latestDate={dateBounds.maxDate}
          productCount={products.length}
          sortKey={sortKey}
          onSortChange={(nextSortKey) => {
            setSortKey(nextSortKey)
            setVisibleCount(PAGE_SIZE)
          }}
          onOpenFilters={() => setIsSheetOpen(true)}
        />

        <div className="space-y-4 px-4 pb-8 pt-4">
          <SearchBar
            value={query}
            onChange={(value) => {
              setQuery(value)
              setVisibleCount(PAGE_SIZE)
            }}
          />
          <CategoryChips
            selectedCategory={category}
            onSelect={(nextCategory) => {
              setCategory(nextCategory)
              setVisibleCount(PAGE_SIZE)
            }}
          />
          <BrandChips
            selectedBrand={brand}
            onSelect={(nextBrand) => {
              setBrand(nextBrand)
              setVisibleCount(PAGE_SIZE)
            }}
          />

          <div className="border-y border-slate-200 py-3">
            <p aria-live="polite" className="flex items-center gap-1.5 text-[15px] font-semibold text-slate-600">
              <FileText size={16} aria-hidden="true" />
              找到 {visibleProducts.length} 項商品
            </p>
            {activeFilterLabels.length > 0 ? (
              <div className="mt-2 flex items-start justify-between gap-2 rounded-md bg-[#0F7C7C]/10 px-2.5 py-2">
                <p className="text-sm font-bold leading-5 text-[#0F6666]">
                  篩選：{activeFilterLabels.join(' · ')}
                </p>
                <button
                  type="button"
                  aria-label="清除進階篩選"
                  onClick={() => {
                    setFilters({ minScore: 0, fromDate: '', toDate: '' })
                    setVisibleCount(PAGE_SIZE)
                  }}
                  className="grid size-7 shrink-0 place-items-center rounded-md text-[#0F6666] hover:bg-[#0F7C7C]/10"
                >
                  <X size={18} />
                </button>
              </div>
            ) : null}
          </div>

          <h1 className="text-2xl font-black tracking-wide text-slate-950">架上候選商品</h1>

          {isLoading ? (
            <div className="rounded-lg border border-slate-200 bg-white p-6 text-center text-slate-500">
              載入商品資料中...
            </div>
          ) : error ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">
              {error}
            </div>
          ) : visibleProducts.length === 0 ? (
            <div className="rounded-lg border border-slate-200 bg-white p-6 text-center text-slate-500">
              沒有符合條件的商品
            </div>
          ) : (
            <div className="space-y-2.5">
              {displayedProducts.map((product, index) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  rank={index + 1}
                  isExpanded={expanded.has(product.id)}
                  onToggle={() => toggleProduct(product.id)}
                />
              ))}
              {remainingCount > 0 ? (
                <div className="pt-2 text-center">
                  <p className="mb-2 text-sm font-semibold text-slate-500">
                    已顯示 {displayedProducts.length} / {visibleProducts.length} 項
                  </p>
                  <button
                    type="button"
                    onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-[#0F7C7C] bg-white px-4 py-3 font-black text-[#0F7C7C] hover:bg-[#0F7C7C]/5"
                  >
                    再顯示 {Math.min(PAGE_SIZE, remainingCount)} 項
                    <ChevronDown size={20} aria-hidden="true" />
                  </button>
                </div>
              ) : null}
            </div>
          )}
        </div>
      </div>

      <FilterSheet
        dateBounds={dateBounds}
        filters={filters}
        isOpen={isSheetOpen}
        onClose={() => setIsSheetOpen(false)}
        onChange={(nextFilters) => {
          setFilters(nextFilters)
          setVisibleCount(PAGE_SIZE)
        }}
      />
    </main>
  )
}
