'use client'

import { MessageSquareText, ThumbsUp, TriangleAlert, UserRound } from 'lucide-react'
import { excerptSegments, ProvisionalNote, SourceLinks, type VariantProps } from './shared'

const BAR_WIDTH: Record<number, string> = {
  0: 'w-0',
  1: 'w-1/3',
  2: 'w-2/3',
  3: 'w-full',
}

function SignalLedger({
  label,
  items,
  tone,
}: {
  label: string
  items: string[]
  tone: 'teal' | 'red'
}) {
  const isTeal = tone === 'teal'
  const bar = isTeal ? 'bg-[#2E9E5B]' : 'bg-[#B91C1C]'
  const labelColor = isTeal ? 'text-[#0F7C7C]' : 'text-red-700'

  return (
    <div className={`min-w-0 rounded-lg border p-3 ${isTeal ? 'border-[#0F7C7C]/20 bg-[#0F7C7C]/5' : 'border-red-200 bg-red-50/60'}`}>
      <h4 className={`flex items-center gap-1.5 font-black ${labelColor}`}>
        {isTeal ? <ThumbsUp size={17} aria-hidden="true" /> : <TriangleAlert size={17} aria-hidden="true" />}
        {label}
        <span className="ml-auto text-lg leading-none">{items.length}</span>
      </h4>
      <ol className="mt-2 space-y-2 text-sm font-semibold leading-5 text-slate-700">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="flex min-w-0 items-start gap-2 border-t border-slate-200/80 pt-2 first:border-t-0 first:pt-0">
            <span className={`shrink-0 text-xs font-black ${labelColor}`}>{index + 1}</span>
            <span className="min-w-0 break-words">{item}</span>
          </li>
        ))}
      </ol>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/80" aria-hidden="true">
        <span
          className={`block h-full rounded-full ${bar} ${BAR_WIDTH[Math.min(items.length, 3)]}`}
        />
      </div>
    </div>
  )
}

export default function VariantC({ product }: VariantProps) {
  const segments = excerptSegments(product)
  const hasLikes = product.likes.length > 0
  const hasCautions = product.cautions.length > 0
  const hasBothSides = hasLikes && hasCautions

  return (
    <div className="mt-4 w-full min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-[#FFFDF8] p-3 sm:p-4">
      <section>
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <MessageSquareText size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          買前取捨
        </h3>
        <div className="mt-3 grid grid-cols-2 gap-2" aria-label="喜歡與留意訊號數量">
          <div className="min-w-0 rounded-lg border border-[#0F7C7C]/20 bg-[#0F7C7C]/5 px-3 py-2.5">
            <p className="text-xs font-black text-[#0F7C7C]">喜歡</p>
            <p className="mt-1 text-2xl font-black leading-none text-slate-950">{product.likes.length}</p>
          </div>
          <div className="min-w-0 rounded-lg border border-red-200 bg-red-50/60 px-3 py-2.5">
            <p className="text-xs font-black text-red-700">留意</p>
            <p className="mt-1 text-2xl font-black leading-none text-slate-950">{product.cautions.length}</p>
          </div>
        </div>

        <div className={`mt-3 grid min-w-0 gap-3 ${hasBothSides ? 'min-[380px]:grid-cols-2' : 'grid-cols-1'}`}>
          {hasLikes ? <SignalLedger label="大家喜歡的點" items={product.likes} tone="teal" /> : null}
          {hasCautions ? (
            <SignalLedger label="需要留意的點" items={product.cautions} tone="red" />
          ) : null}
          {!hasLikes && !hasCautions ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-3 text-sm font-semibold leading-5 text-slate-500">
              這筆資料尚未形成可分辨的喜歡／留意訊號。
            </div>
          ) : null}
          {hasLikes !== hasCautions ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-3 text-sm font-semibold leading-5 text-slate-500">
              {hasLikes ? '目前沒有整理出的留意訊號。' : '目前沒有整理出的喜歡訊號。'}
            </div>
          ) : null}
        </div>
      </section>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <UserRound size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          作者摘要（模型整理）
        </h3>
        <ProvisionalNote product={product} />
        {segments.length > 0 ? (
          <div className="mt-3 min-w-0 rounded-md border-l-4 border-slate-300 bg-slate-50 px-3 py-2.5 text-sm font-semibold leading-6 text-slate-700">
            <span className="break-words">{product.excerpt}</span>
          </div>
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
