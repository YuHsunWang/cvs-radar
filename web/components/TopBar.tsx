import { useEffect, useRef, useState } from 'react'
import { Bell, Radar, X } from 'lucide-react'
import {
  DATA_STALE_DAYS,
  formatDisplayDate,
  isDataStale,
  sortLabel,
  type CategoryKey,
  type SortKey,
} from '@/lib/data'

type TopBarProps = {
  brand: string | null
  category: CategoryKey | null
  generatedAt: string
  latestDate: string
  productCount: number
  sortKey: SortKey
}

export default function TopBar({
  brand,
  category,
  generatedAt,
  latestDate,
  productCount,
  sortKey,
}: TopBarProps) {
  const [isNoticeOpen, setIsNoticeOpen] = useState(false)
  const noticeButtonRef = useRef<HTMLButtonElement>(null)
  const noticeRef = useRef<HTMLDivElement>(null)
  const dataIsStale = isDataStale(generatedAt)

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
          aria-label={dataIsStale ? '資料更新通知，有資料過期警告' : '資料更新通知'}
          aria-expanded={isNoticeOpen}
          aria-haspopup="dialog"
          onClick={() => setIsNoticeOpen((open) => !open)}
          className="relative grid size-11 place-items-center text-slate-700"
        >
          <Bell size={27} strokeWidth={2.15} />
          {dataIsStale ? (
            <span aria-hidden="true" className="absolute right-2 top-2 size-2.5 rounded-full bg-amber-500 ring-2 ring-[#FCFAF5]" />
          ) : null}
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
              <p className="mt-2 text-xs font-medium text-slate-400">資料更新 {formatDisplayDate(generatedAt)}</p>
              {dataIsStale ? (
                <p role="alert" className="mt-1 text-xs font-bold text-amber-700">
                  資料可能過期（超過 {DATA_STALE_DAYS} 天未更新）
                </p>
              ) : null}
            </div>
            <button type="button" aria-label="關閉通知" onClick={() => setIsNoticeOpen(false)} className="grid size-11 shrink-0 place-items-center text-slate-500">
              <X size={20} />
            </button>
          </div>
        </div>
      ) : null}
    </header>
  )
}
