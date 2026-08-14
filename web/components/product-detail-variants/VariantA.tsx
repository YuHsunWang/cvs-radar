'use client'

import { MessageSquareText, ThumbsUp, TriangleAlert, UserRound } from 'lucide-react'
import {
  excerptSegments,
  ProvisionalNote,
  SourceLinks,
  type VariantProps,
} from './shared'

function EvidenceList({ items, emptyLabel }: { items: string[]; emptyLabel: string }) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-white/60 px-3 py-2 text-sm font-semibold leading-5 text-slate-500">
        {emptyLabel}
      </div>
    )
  }

  return (
    <ul className="space-y-2 text-sm font-semibold leading-5 text-slate-700">
      {items.map((item, index) => (
        <li key={`${item}-${index}`} className="flex min-w-0 items-start gap-2">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
          <span className="min-w-0 break-words">{item}</span>
        </li>
      ))}
    </ul>
  )
}

export default function VariantA({ product }: VariantProps) {
  const segments = excerptSegments(product)
  const signalCount = product.likes.length + product.cautions.length

  return (
    <div className="mt-4 w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-[#FFFDF8] p-3 sm:p-4">
      <section>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 font-black text-slate-950">
            <UserRound size={20} className="text-[#0F7C7C]" aria-hidden="true" />
            作者摘要
          </h3>
          <span className="rounded-full bg-[#0F7C7C]/10 px-2 py-1 text-xs font-black text-[#0F7C7C]">
            {segments.length > 1 ? `${segments.length} 則來源摘要` : '模型整理'}
          </span>
        </div>
        <ProvisionalNote product={product} />

        {segments.length > 0 ? (
          <div className="mt-3 space-y-2">
            {segments.map((segment, index) => (
              <div
                key={`${segment}-${index}`}
                className="min-w-0 rounded-r-md border-l-4 border-[#0F7C7C] bg-slate-50 px-3 py-2.5 text-sm font-semibold leading-6 text-slate-700"
              >
                {segments.length > 1 ? (
                  <span className="mr-2 text-xs font-black text-[#0F7C7C]">來源摘要 {index + 1}</span>
                ) : null}
                <span className="break-words">{segment}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-3">
            <p className="text-sm font-black text-slate-700">目前沒有作者摘要</p>
            <p className="mt-1 text-xs font-semibold leading-5 text-slate-500">
              可從下方整理重點或原文確認。
            </p>
          </div>
        )}
      </section>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 font-black text-slate-950">
            <MessageSquareText size={20} className="text-[#0F7C7C]" aria-hidden="true" />
            三秒重點
          </h3>
          <span className="text-xs font-bold text-slate-500">{signalCount} 個整理訊號</span>
        </div>

        <div className="mt-3 grid min-w-0 grid-cols-1 gap-3 min-[380px]:grid-cols-2">
          <div className="min-w-0 rounded-lg border border-[#0F7C7C]/20 bg-[#0F7C7C]/5 p-3">
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-[#0F7C7C]">
              <ThumbsUp size={17} aria-hidden="true" />
              大家喜歡的點
              <span className="ml-auto text-xs">{product.likes.length}</span>
            </h4>
            <EvidenceList items={product.likes} emptyLabel="目前沒有整理出的喜歡訊號" />
          </div>

          <div className="min-w-0 rounded-lg border border-red-200 bg-red-50/60 p-3">
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-red-700">
              <TriangleAlert size={17} aria-hidden="true" />
              需要留意的點
              <span className="ml-auto text-xs">{product.cautions.length}</span>
            </h4>
            <EvidenceList items={product.cautions} emptyLabel="目前沒有整理出的留意訊號" />
          </div>
        </div>
      </section>

      <SourceLinks product={product} />
    </div>
  )
}
