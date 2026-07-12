import { useEffect, useRef, useState } from 'react'
import { CalendarDays, RotateCcw, X } from 'lucide-react'
import type { AdvancedFilters } from '@/lib/data'

type FilterSheetProps = {
  dateBounds: { minDate: string; maxDate: string }
  filters: AdvancedFilters
  isOpen: boolean
  onClose: () => void
  onChange: (filters: AdvancedFilters) => void
}

const emptyFilters: AdvancedFilters = { minScore: 0, fromDate: '', toDate: '' }

export default function FilterSheet({ dateBounds, filters, isOpen, onClose, onChange }: FilterSheetProps) {
  const [draft, setDraft] = useState(filters)
  const dialogRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!isOpen) return

    setDraft(filters)
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const originalBodyOverflow = document.body.style.overflow
    const originalHtmlOverflow = document.documentElement.style.overflow
    document.body.style.overflow = 'hidden'
    document.documentElement.style.overflow = 'hidden'

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }

      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      )
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    const focusFrame = requestAnimationFrame(() => closeButtonRef.current?.focus())

    return () => {
      cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = originalBodyOverflow
      document.documentElement.style.overflow = originalHtmlOverflow
      returnFocusRef.current?.focus()
    }
  }, [filters, isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/40" onClick={onClose}>
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="filter-sheet-title"
        className="absolute bottom-0 left-1/2 max-h-[calc(100dvh-1rem)] w-full max-w-[430px] -translate-x-1/2 overflow-y-auto rounded-t-lg bg-white p-5 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 id="filter-sheet-title" className="text-2xl font-black text-slate-950">調整篩選</h2>
          <button ref={closeButtonRef} type="button" aria-label="關閉篩選" onClick={onClose} className="grid size-10 place-items-center text-slate-500">
            <X size={25} />
          </button>
        </div>

        <label className="block">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-black text-slate-800">最低推薦分數</span>
            <span className="rounded-md bg-[#0F7C7C]/10 px-2 py-1 font-black text-[#0F7C7C]">
              {draft.minScore}
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={draft.minScore}
            onChange={(event) => setDraft({ ...draft, minScore: Number(event.target.value) })}
            className="w-full accent-[#0F7C7C]"
          />
        </label>

        <fieldset className="mt-6 border-t border-slate-200 pt-5">
          <legend className="flex items-center gap-2 pr-3 font-black text-slate-800">
            <CalendarDays size={20} aria-hidden="true" />
            最新發文日期範圍
          </legend>
          <div className="mt-3 grid grid-cols-1 gap-3 min-[360px]:grid-cols-2">
            <label className="min-w-0 text-sm font-bold text-slate-600">
              起始日期
              <LocalizedDateInput
                min={dateBounds.minDate}
                max={draft.toDate || dateBounds.maxDate}
                value={draft.fromDate}
                onChange={(value) => setDraft({ ...draft, fromDate: value })}
              />
            </label>
            <label className="min-w-0 text-sm font-bold text-slate-600">
              結束日期
              <LocalizedDateInput
                min={draft.fromDate || dateBounds.minDate}
                max={dateBounds.maxDate}
                value={draft.toDate}
                onChange={(value) => setDraft({ ...draft, toDate: value })}
              />
            </label>
          </div>
          <p className="mt-2 text-xs font-semibold text-slate-400">
            可篩選資料範圍：{formatDate(dateBounds.minDate)} 至 {formatDate(dateBounds.maxDate)}
          </p>
        </fieldset>

        <div className="mt-5 grid grid-cols-[0.8fr_1.2fr] gap-3">
          <button
            type="button"
            onClick={() => setDraft(emptyFilters)}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 px-3 py-3 font-black text-slate-700"
          >
            <RotateCcw size={18} aria-hidden="true" />
            清除
          </button>
          <button
            type="button"
            onClick={() => {
              onChange(draft)
              onClose()
            }}
            className="rounded-lg bg-[#0F7C7C] px-4 py-3 text-lg font-black text-white"
          >
            套用篩選
          </button>
        </div>
      </section>
    </div>
  )
}

function formatDate(value: string): string {
  return value ? value.replaceAll('-', '/') : '載入中'
}

type LocalizedDateInputProps = {
  min: string
  max: string
  value: string
  onChange: (value: string) => void
}

function LocalizedDateInput({ min, max, value, onChange }: LocalizedDateInputProps) {
  const [text, setText] = useState(value ? formatDate(value) : '')

  useEffect(() => {
    setText(value ? formatDate(value) : '')
  }, [value])

  function commit(nextText: string) {
    const nextValue = parseDate(nextText)
    if (!nextText || (nextValue && nextValue >= min && nextValue <= max)) {
      onChange(nextValue ?? '')
    }
  }

  return (
    <input
      type="text"
      inputMode="numeric"
      placeholder="年/月/日"
      aria-label="請以年/月/日輸入"
      value={text}
      onChange={(event) => {
        const nextText = event.target.value
        setText(nextText)
        commit(nextText)
      }}
      onBlur={() => setText(value ? formatDate(value) : '')}
      className="mt-1.5 min-h-11 w-full min-w-0 rounded-md border border-slate-300 bg-white px-2 text-sm font-semibold text-slate-900"
    />
  )
}

function parseDate(value: string): string | null {
  const normalized = value.replaceAll('/', '-')
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return null
  const date = new Date(`${normalized}T00:00:00Z`)
  return date.toISOString().slice(0, 10) === normalized ? normalized : null
}
