'use client'

import { useEffect, useRef, useState } from 'react'
import { CalendarDays } from 'lucide-react'
import { dateToOffset, normalizeDateRange, offsetToDate } from '@/lib/data'

type DateRangeSliderProps = {
  dateBounds: { minDate: string; maxDate: string }
  fromDate: string
  toDate: string
  onChange: (range: { fromDate: string; toDate: string }) => void
}

export default function DateRangeSlider({ dateBounds, fromDate, toDate, onChange }: DateRangeSliderProps) {
  const hasDateBounds = Boolean(dateBounds.minDate && dateBounds.maxDate)
  const maxDateOffset = hasDateBounds ? dateToOffset(dateBounds.maxDate, dateBounds.minDate) : 0
  const controlledStart = hasDateBounds ? dateToOffset(fromDate || dateBounds.minDate, dateBounds.minDate) : 0
  const controlledEnd = hasDateBounds ? dateToOffset(toDate || dateBounds.maxDate, dateBounds.minDate) : 0
  const [startOffset, setStartOffset] = useState(controlledStart)
  const [endOffset, setEndOffset] = useState(controlledEnd)
  const [activeThumb, setActiveThumb] = useState<'start' | 'end'>('end')
  const changeFrameRef = useRef<number | null>(null)
  const pendingRangeRef = useRef({ startOffset: controlledStart, endOffset: controlledEnd })
  const onChangeRef = useRef(onChange)

  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  useEffect(() => {
    setStartOffset(controlledStart)
    setEndOffset(controlledEnd)
    pendingRangeRef.current = { startOffset: controlledStart, endOffset: controlledEnd }
  }, [controlledEnd, controlledStart])

  useEffect(() => {
    return () => {
      if (changeFrameRef.current !== null) cancelAnimationFrame(changeFrameRef.current)
    }
  }, [])

  function scheduleChange(nextStartOffset: number, nextEndOffset: number) {
    pendingRangeRef.current = { startOffset: nextStartOffset, endOffset: nextEndOffset }
    if (changeFrameRef.current !== null) return

    changeFrameRef.current = requestAnimationFrame(() => {
      changeFrameRef.current = null
      const pendingRange = pendingRangeRef.current
      const nextFromDate = offsetToDate(pendingRange.startOffset, dateBounds.minDate)
      const nextToDate = offsetToDate(pendingRange.endOffset, dateBounds.minDate)
      onChangeRef.current(
        normalizeDateRange(nextFromDate, nextToDate, dateBounds.minDate, dateBounds.maxDate),
      )
    })
  }

  function updateStart(nextOffset: number) {
    const clampedOffset = Math.min(nextOffset, endOffset)
    setStartOffset(clampedOffset)
    scheduleChange(clampedOffset, endOffset)
  }

  function updateEnd(nextOffset: number) {
    const clampedOffset = Math.max(nextOffset, startOffset)
    setEndOffset(clampedOffset)
    scheduleChange(startOffset, clampedOffset)
  }

  const startDate = hasDateBounds ? offsetToDate(startOffset, dateBounds.minDate) : ''
  const endDate = hasDateBounds ? offsetToDate(endOffset, dateBounds.minDate) : ''
  const startPercent = maxDateOffset > 0 ? (startOffset / maxDateOffset) * 100 : 0
  const endPercent = maxDateOffset > 0 ? (endOffset / maxDateOffset) * 100 : 100

  return (
    <fieldset className="min-w-0 rounded-xl border border-slate-200 bg-white px-4 pb-4 pt-3 shadow-sm">
      <legend className="flex items-center gap-2 px-1 text-sm font-black text-slate-800">
        <CalendarDays size={18} aria-hidden="true" />
        最新發文日期範圍
      </legend>

      {hasDateBounds ? (
        <>
          <div className="mt-2 grid grid-cols-2 gap-3">
            <label
              htmlFor="date-range-start"
              onPointerDown={() => setActiveThumb('start')}
              className="min-w-0 cursor-pointer rounded-lg bg-[#0F7C7C]/10 px-3 py-2 text-left"
            >
              <span className="block text-xs font-bold text-slate-500">起始</span>
              <span className="block truncate text-sm font-black tabular-nums text-[#0F6666]">
                {formatDate(startDate)}
              </span>
            </label>
            <label
              htmlFor="date-range-end"
              onPointerDown={() => setActiveThumb('end')}
              className="min-w-0 cursor-pointer rounded-lg bg-[#0F7C7C]/10 px-3 py-2 text-right"
            >
              <span className="block text-xs font-bold text-slate-500">結束</span>
              <span className="block truncate text-sm font-black tabular-nums text-[#0F6666]">
                {formatDate(endDate)}
              </span>
            </label>
          </div>

          <div className="relative mt-2 h-11" data-date-range-track>
            <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-slate-200" />
            <div
              aria-hidden="true"
              className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-[#0F7C7C]"
              style={{ left: `${startPercent}%`, right: `${100 - endPercent}%` }}
            />
            <input
              id="date-range-start"
              type="range"
              min="0"
              max={maxDateOffset}
              step="1"
              value={startOffset}
              aria-valuetext={`起始日期 ${formatDate(startDate)}`}
              onFocus={() => setActiveThumb('start')}
              onPointerDown={() => setActiveThumb('start')}
              onChange={(event) => updateStart(Number(event.target.value))}
              className="date-range-input"
              style={{ zIndex: activeThumb === 'start' ? 4 : 3 }}
            />
            <input
              id="date-range-end"
              type="range"
              min="0"
              max={maxDateOffset}
              step="1"
              value={endOffset}
              aria-valuetext={`結束日期 ${formatDate(endDate)}`}
              onFocus={() => setActiveThumb('end')}
              onPointerDown={() => setActiveThumb('end')}
              onChange={(event) => updateEnd(Number(event.target.value))}
              className="date-range-input"
              style={{ zIndex: activeThumb === 'end' ? 4 : 3 }}
            />
          </div>

          <p className="mt-1 text-xs font-semibold leading-5 text-slate-500">
            拖曳圓點即時篩選；選滿完整範圍會顯示所有日期。
          </p>
        </>
      ) : (
        <p className="mt-2 text-sm font-semibold text-slate-500">目前沒有可篩選的發文日期。</p>
      )}
    </fieldset>
  )
}

function formatDate(value: string): string {
  return value ? value.replaceAll('-', '/') : '載入中'
}
