'use client'

import { MessageSquareText, ThumbsUp, TriangleAlert, UserRound } from 'lucide-react'
import {
  excerptSegments,
  ProvisionalNote,
  SourceLinks,
  type VariantProps,
} from './shared'

function SignalChips({
  items,
  emptyLabel,
  tone,
}: {
  items: string[]
  emptyLabel: string
  tone: 'teal' | 'red'
}) {
  const palette =
    tone === 'teal'
      ? 'border-[#0F7C7C]/20 bg-[#0F7C7C]/5 text-[#0F7C7C]'
      : 'border-red-200 bg-red-50/70 text-red-700'

  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-white/70 px-3 py-2 text-sm font-semibold leading-5 text-slate-500">
        {emptyLabel}
      </div>
    )
  }

  return (
    <ul className="flex min-w-0 flex-wrap gap-2">
      {items.map((item, index) => (
        <li
          key={`${item}-${index}`}
          className={`max-w-full rounded-full border px-2.5 py-1.5 text-sm font-bold leading-5 ${palette}`}
        >
          <span className="break-words">{item}</span>
        </li>
      ))}
    </ul>
  )
}

export default function VariantB({ product }: VariantProps) {
  const segments = excerptSegments(product)

  return (
    <div className="mt-4 w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-[#FFFDF8] p-3 sm:p-4">
      <section>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 font-black text-slate-950">
            <MessageSquareText size={20} className="text-[#0F7C7C]" aria-hidden="true" />
            評價訊號先看
          </h3>
          <span className="text-xs font-bold text-slate-500">像貨架標籤一樣掃讀</span>
        </div>

        <div className="mt-3 space-y-3">
          <div className="min-w-0 rounded-lg border border-[#0F7C7C]/20 bg-[#0F7C7C]/5 p-3">
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-[#0F7C7C]">
              <ThumbsUp size={17} aria-hidden="true" />
              大家喜歡的點
              <span className="ml-auto text-xs">{product.likes.length}</span>
            </h4>
            <SignalChips
              items={product.likes}
              tone="teal"
              emptyLabel="目前沒有可貼上的喜歡訊號"
            />
          </div>

          <div className="min-w-0 rounded-lg border border-red-200 bg-red-50/60 p-3">
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-red-700">
              <TriangleAlert size={17} aria-hidden="true" />
              需要留意的點
              <span className="ml-auto text-xs">{product.cautions.length}</span>
            </h4>
            <SignalChips
              items={product.cautions}
              tone="red"
              emptyLabel="目前沒有可貼上的留意訊號"
            />
          </div>
        </div>
      </section>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <UserRound size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          作者摘要（模型整理）
        </h3>
        <ProvisionalNote product={product} />
        {segments.length > 0 ? (
          <ol className="mt-3 divide-y divide-slate-200 rounded-lg border border-slate-200 bg-slate-50">
            {segments.map((segment, index) => (
              <li key={`${segment}-${index}`} className="flex min-w-0 gap-3 px-3 py-2.5">
                <span className="shrink-0 text-xs font-black text-[#0F7C7C]">{index + 1}</span>
                <p className="min-w-0 break-words text-sm font-semibold leading-6 text-slate-700">
                  {segment}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-3 rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-3 text-sm font-semibold leading-5 text-slate-500">
            尚未擷取到作者摘要；可直接查看原文。
          </p>
        )}
      </section>

      <SourceLinks product={product} />
    </div>
  )
}
