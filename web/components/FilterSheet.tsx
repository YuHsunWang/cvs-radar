import { useEffect, useRef, useState } from 'react'
import { RotateCcw, X } from 'lucide-react'

type FilterSheetProps = {
  minScore: number
  isOpen: boolean
  onClose: () => void
  onChange: (minScore: number) => void
}

export default function FilterSheet({ minScore, isOpen, onClose, onChange }: FilterSheetProps) {
  const [draftMinScore, setDraftMinScore] = useState(minScore)
  const dialogRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!isOpen) return

    setDraftMinScore(minScore)
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
  }, [isOpen, minScore])

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
              {draftMinScore}
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={draftMinScore}
            onChange={(event) => setDraftMinScore(Number(event.target.value))}
            className="w-full accent-[#0F7C7C]"
          />
        </label>

        <div className="mt-5 grid grid-cols-[0.8fr_1.2fr] gap-3">
          <button
            type="button"
            onClick={() => setDraftMinScore(0)}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 px-3 py-3 font-black text-slate-700"
          >
            <RotateCcw size={18} aria-hidden="true" />
            清除
          </button>
          <button
            type="button"
            onClick={() => {
              onChange(draftMinScore)
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
