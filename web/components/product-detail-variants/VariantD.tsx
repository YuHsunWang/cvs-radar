'use client'

import { MessageSquareText, ThumbsUp, TriangleAlert, UserRound } from 'lucide-react'
import { excerptSegments, ProvisionalNote, SourceLinks, type VariantProps } from './shared'

function InlineEvidence({
  items,
  emptyLabel,
}: {
  items: string[]
  emptyLabel: string
}) {
  if (items.length === 0) {
    return <p className="text-sm font-semibold leading-5 text-slate-500">{emptyLabel}</p>
  }

  return (
    <p className="min-w-0 break-words text-sm font-semibold leading-6 text-slate-700">
      {items.map((item, index) => (
        <span key={`${item}-${index}`}>
          {index > 0 ? <span className="mx-1 text-slate-400" aria-hidden="true">·</span> : null}
          {item}
        </span>
      ))}
    </p>
  )
}

export default function VariantD({ product }: VariantProps) {
  const segments = excerptSegments(product)
  const hasAnyEvidence = product.likes.length > 0 || product.cautions.length > 0

  return (
    <div className="mt-4 w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-[#FFFDF8] p-3 sm:p-4">
      <section>
        <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 font-black text-slate-950">
            <UserRound size={20} className="text-[#0F7C7C]" aria-hidden="true" />
            作者摘要筆記
          </h3>
          <span className="rounded bg-slate-100 px-2 py-1 text-xs font-black text-slate-600">模型整理，非逐字引文</span>
        </div>
        <ProvisionalNote product={product} />

        {segments.length > 0 ? (
          <div className="mt-3 space-y-2">
            {segments.map((segment, index) => (
              <div
                key={`${segment}-${index}`}
                className="min-w-0 rounded-lg bg-[#0F7C7C]/5 px-3 py-2.5 text-sm font-semibold leading-6 text-slate-700"
              >
                <span className="mr-2 inline-block text-xs font-black text-[#0F7C7C]">來源摘要 {index + 1}</span>
                <span className="break-words">{segment}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-3">
            <p className="text-sm font-black text-slate-700">這筆沒有作者摘要</p>
            <p className="mt-1 text-xs font-semibold leading-5 text-slate-500">下面只顯示已整理的訊號。</p>
          </div>
        )}
      </section>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <MessageSquareText size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          一眼帶走
        </h3>
        <div className="mt-3 space-y-2">
          {hasAnyEvidence ? (
            <>
              <div className="min-w-0 rounded-md border-l-4 border-[#2E9E5B] bg-[#2E9E5B]/10 px-3 py-2.5">
                <h4 className="flex items-center gap-1.5 text-sm font-black text-[#0F7C7C]">
                  <ThumbsUp size={16} aria-hidden="true" />
                  會喜歡
                  <span className="ml-auto text-xs">{product.likes.length}</span>
                </h4>
                <div className="mt-1">
                  <InlineEvidence items={product.likes} emptyLabel="沒有額外整理出的喜歡訊號" />
                </div>
              </div>
              <div className="min-w-0 rounded-md border-l-4 border-[#B91C1C] bg-red-50 px-3 py-2.5">
                <h4 className="flex items-center gap-1.5 text-sm font-black text-red-700">
                  <TriangleAlert size={16} aria-hidden="true" />
                  先留意
                  <span className="ml-auto text-xs">{product.cautions.length}</span>
                </h4>
                <div className="mt-1">
                  <InlineEvidence items={product.cautions} emptyLabel="沒有額外整理出的留意訊號" />
                </div>
              </div>
            </>
          ) : (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-3 text-sm font-semibold leading-5 text-slate-500">
              目前沒有額外的喜歡或留意訊號，先以作者摘要與原文為準。
            </div>
          )}
        </div>
      </section>

      <SourceLinks product={product} />
    </div>
  )
}
