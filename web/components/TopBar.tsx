import { useEffect, useRef, useState } from 'react'
import { Bell, Radar, SlidersHorizontal, X } from 'lucide-react'
import { formatDisplayDate, sortLabel, type CategoryKey, type SortKey } from '@/lib/data'

type TopBarProps = {
  brand: string | null
  category: CategoryKey | null
  generatedAt: string
  latestDate: string
  productCount: number
  activeFilterCount: number
  sortKey: SortKey
  onSortChange: (sortKey: SortKey) => void
  onOpenFilters: () => void
}

export default function TopBar({
  brand,
  category,
  generatedAt,
  latestDate,
  productCount,
  activeFilterCount,
  sortKey,
  onSortChange,
  onOpenFilters,
}: TopBarProps) {
  const [isNoticeOpen, setIsNoticeOpen] = useState(false)
  const noticeButtonRef = useRef<HTMLButtonElement>(null)
  const noticeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isNoticeOpen) return

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (!noticeButtonRef.current?.contains(target) && !noticeRef.current?.contains(target)) {
        setIsNoticeOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsNoticeOpen(false)
        noticeButtonRef.current?.focus()
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isNoticeOpen])

  function openFilters() {
    setIsNoticeOpen(false)
    onOpenFilters()
  }

  return (
    <header className="relative border-b border-slate-200 bg-[#FCFAF5]">
      <div className="grid grid-cols-[2.75rem_minmax(0,1fr)_2.75rem] items-center gap-2 px-4 pb-4 pt-7">
        <div aria-hidden="true" className="grid size-10 place-items-center text-[#0F7C7C]">
          <Radar size={30} strokeWidth={2.2} />
        </div>
        <div className="min-w-0 px-1">
          <p className="whitespace-nowrap text-2xl font-black leading-tight text-slate-950">CVS Radar</p>
          <p className="truncate text-sm font-bold text-slate-500">
            {brand ?? '全部品牌'} · {category ?? '全部分類'} · {sortLabel(sortKey)}
          </p>
        </div>
        <button
          ref={noticeButtonRef}
          type="button"
          aria-label="資料更新通知"
          aria-expanded={isNoticeOpen}
          aria-haspopup="dialog"
          onClick={() => setIsNoticeOpen((open) => !open)}
          className="grid size-11 place-items-center text-slate-700"
        >
          <Bell size={27} strokeWidth={2.15} />
        </button>
      </div>

      {isNoticeOpen ? (
        <div
          ref={noticeRef}
          role="dialog"
          aria-label="資料更新資訊"
          className="absolute right-4 top-[5.1rem] z-20 w-[min(20rem,calc(100%-2rem))] rounded-lg border border-slate-200 bg-white p-4 shadow-xl"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-black text-slate-950">資料更新</p>
              <p className="mt-1 text-sm font-semibold text-slate-600">目前收錄 {productCount} 項商品</p>
              <p className="text-sm font-semibold text-slate-600">最新發文 {formatDisplayDate(latestDate)}</p>
              <p className="mt-2 text-xs font-medium text-slate-400">資料建立 {formatDisplayDate(generatedAt)}</p>
            </div>
            <button type="button" aria-label="關閉通知" onClick={() => setIsNoticeOpen(false)} className="grid size-11 shrink-0 place-items-center text-slate-500">
              <X size={20} />
            </button>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2 px-4 pb-4">
        <button
          type="button"
          data-filter-trigger
          onClick={openFilters}
          className="inline-flex min-w-0 items-center justify-center gap-1.5 rounded-lg bg-[#0F7C7C] px-2 py-3 text-base font-black text-white shadow-md shadow-teal-900/20"
        >
          <SlidersHorizontal className="shrink-0" size={19} aria-hidden="true" />
          調整篩選
          {activeFilterCount > 0 ? (
            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-white text-xs text-[#0F7C7C]">
              {activeFilterCount}
            </span>
          ) : null}
        </button>
        <label className="relative">
          <span className="sr-only">排序</span>
          <select
            value={sortKey}
            onChange={(event) => onSortChange(event.target.value as SortKey)}
            className="h-full w-full appearance-none rounded-lg border border-slate-300 bg-white py-3 pl-2 pr-7 text-center text-base font-black text-slate-900 shadow-sm"
          >
            <option value="latestDateDesc">發文 近到遠</option>
            <option value="latestDateAsc">發文 遠到近</option>
            <option value="volumeDesc">聲量 高到低</option>
            <option value="volumeAsc">聲量 低到高</option>
            <option value="fairScoreDesc">推薦分 高到低</option>
            <option value="fairScoreAsc">推薦分 低到高</option>
          </select>
          <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-base font-black text-slate-800">
            ▾
          </span>
        </label>
      </div>
    </header>
  )
}
