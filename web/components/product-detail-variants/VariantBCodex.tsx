'use client'

import { ExternalLink, ThumbsUp, TriangleAlert } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { displayBrand } from '@/lib/data'
import { excerptSegments, ProvisionalNote, type VariantProps } from './shared'

const BRAND_SPINE: Record<string, string> = {
  '7-11': 'border-l-[#F26522]',
  全家: 'border-l-[#009B4C]',
  萊爾富: 'border-l-[#E51F26]',
  OK: 'border-l-[#F5A623]',
  美聯社: 'border-l-[#6C3DBF]',
  其他: 'border-l-[#6B7280]',
}

type SignalPanelProps = {
  label: string
  items: string[]
  tone: 'positive' | 'caution'
  emptyLabel: string
}

function SignalPanel({ label, items, tone, emptyLabel }: SignalPanelProps) {
  const isPositive = tone === 'positive'
  const accentBorder = isPositive ? 'border-l-[#2E9E5B]' : 'border-l-[#D64545]'
  const accentText = isPositive ? 'text-[#0F7C7C]' : 'text-[#B91C1C]'
  const accentWash = isPositive ? 'bg-[#2E9E5B]/10' : 'bg-[#D64545]/10'
  const Icon = isPositive ? ThumbsUp : TriangleAlert

  return (
    <div className={`min-w-0 border-2 border-[#17130E] border-l-[6px] ${accentBorder} bg-[#FFFDF8]`}>
      <div className="flex min-w-0 items-start justify-between gap-2 border-b-2 border-[#17130E] px-2.5 py-2">
        <h4 className={`flex min-w-0 items-start gap-1.5 text-[13px] font-black leading-5 ${accentText}`}>
          <Icon size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span className="break-words">{label}</span>
        </h4>
        <span
          className={`shrink-0 border border-[#17130E] px-1.5 py-1 font-mono text-[10px] font-black leading-none ${accentWash} ${accentText}`}
          aria-label={`${items.length} 項`}
        >
          {String(items.length).padStart(2, '0')}
        </span>
      </div>

      {items.length > 0 ? (
        <ul className="divide-y divide-[#17130E]/20">
          {items.map((item, index) => (
            <li key={`${item}-${index}`} className="flex min-w-0 items-start gap-2.5 px-2.5 py-2.5">
              <span
                className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center border border-[#17130E] font-mono text-[10px] font-black leading-none ${accentWash} ${accentText}`}
                aria-hidden="true"
              >
                {String(index + 1).padStart(2, '0')}
              </span>
              <span className="min-w-0 break-words text-[14px] font-bold leading-5 text-[#17130E]">{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex min-h-[78px] flex-col justify-center gap-1 px-2.5 py-3">
          <p className={`font-mono text-[10px] font-black tracking-[0.16em] ${accentText}`}>NO SIGNAL / 00</p>
          <p className="text-sm font-semibold leading-5 text-[#6E685D]">{emptyLabel}</p>
        </div>
      )}
    </div>
  )
}

export default function VariantBCodex({ product }: VariantProps) {
  const brand = displayBrand(product.brand)
  const segments = excerptSegments(product)
  const signalCount = product.likes.length + product.cautions.length
  const spine = BRAND_SPINE[brand] ?? BRAND_SPINE.其他

  return (
    <div
      className={`mt-4 w-full min-w-0 overflow-hidden rounded-[3px] border-2 border-[#17130E] border-l-[6px] ${spine} bg-[#F6F3EA] shadow-[3px_3px_0_#17130E]`}
    >
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b-2 border-[#17130E] bg-[#17130E] px-3 py-2">
        <p className="min-w-0 break-words font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-[#F6F3EA]">
          OPEN LABEL / REVIEW EVIDENCE
        </p>
        <div className="flex shrink-0 items-center gap-2">
          {product.price != null ? (
            <span className="border-2 border-[#D64545] bg-[#FFFDF8] px-1.5 py-1 font-mono text-xs font-black leading-none text-[#B91C1C]">
              ${product.price}
            </span>
          ) : null}
          <span className="font-mono text-[10px] font-black tracking-[0.12em] text-[#E0A417]">{brand}</span>
        </div>
      </div>

      <div className="min-w-0 p-3 sm:p-4">
        <section>
          <div className="flex min-w-0 items-end justify-between gap-2 border-b-2 border-[#17130E] pb-2">
            <div className="min-w-0">
              <p className="font-mono text-[10px] font-black uppercase tracking-[0.16em] text-[#0F7C7C]">
                01 / SHOPPER EVIDENCE
              </p>
              <h3 className="mt-0.5 break-words text-base font-black leading-5 text-[#17130E]">評價訊號先看</h3>
            </div>
            <span className="shrink-0 border-2 border-[#17130E] bg-[#E0A417] px-2 py-1 font-mono text-[10px] font-black leading-none text-[#17130E]">
              {String(signalCount).padStart(2, '0')} POINTS
            </span>
          </div>

          <div className="mt-3 grid min-w-0 grid-cols-1 gap-3 min-[420px]:grid-cols-2" aria-label="喜歡與留意訊號">
            <SignalPanel
              label="大家喜歡的點"
              items={product.likes}
              tone="positive"
              emptyLabel="目前沒有整理出的喜歡訊號"
            />
            <SignalPanel
              label="需要留意的點"
              items={product.cautions}
              tone="caution"
              emptyLabel="目前沒有整理出的留意訊號"
            />
          </div>
        </section>

        <section className="mt-5 border-t-2 border-dashed border-[#17130E] pt-3">
          <div className="flex min-w-0 items-end justify-between gap-2">
            <div className="min-w-0">
              <p className="font-mono text-[10px] font-black uppercase tracking-[0.16em] text-[#0F7C7C]">
                02 / MODEL SUMMARY
              </p>
              <h3 className="mt-0.5 break-words text-base font-black leading-5 text-[#17130E]">作者摘要（模型整理）</h3>
            </div>
            <span className="shrink-0 border border-[#17130E] bg-[#FFFDF8] px-2 py-1 font-mono text-[10px] font-black leading-none text-[#6E685D]">
              非逐字引文
            </span>
          </div>

          {product.reviewProvisional ? (
            <div className="mt-2 border-2 border-dashed border-[#E0A417] bg-[#E0A417]/15 px-3 py-2 [&>p]:mt-0">
              <ProvisionalNote product={product} />
            </div>
          ) : null}

          {segments.length > 0 ? (
            <ol className="mt-3 min-w-0 border-2 border-[#17130E] bg-[#FFFDF8]">
              {segments.map((segment, index) => (
                <li
                  key={`${segment}-${index}`}
                  className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start gap-2.5 border-b border-[#17130E]/25 last:border-b-0"
                >
                  <span className="m-2 grid min-h-5 min-w-8 place-items-center bg-[#0F7C7C] px-1.5 py-1 font-mono text-[10px] font-black leading-none text-[#F6F3EA]">
                    M{String(index + 1).padStart(2, '0')}
                  </span>
                  <p className="min-w-0 break-words py-2.5 pr-2 text-[14px] font-semibold leading-5 text-[#17130E]">{segment}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-3 border border-dashed border-[#6E685D] bg-[#F7F5EF] px-3 py-3 text-sm font-semibold leading-5 text-[#6E685D]">
              <span className="mb-1 block font-mono text-[10px] font-black tracking-[0.16em] text-[#0F7C7C]">NO SUMMARY / 00</span>
              尚未擷取到作者摘要；可直接查看原文。
            </p>
          )}
        </section>

        {product.postUrls.length > 0 ? (
          <section className="mt-5 border-t-2 border-dashed border-[#17130E] pt-3">
            <div className="flex min-w-0 items-end justify-between gap-2">
              <div className="min-w-0">
                <p className="font-mono text-[10px] font-black uppercase tracking-[0.16em] text-[#0F7C7C]">
                  03 / VERIFY
                </p>
                <h3 className="mt-0.5 break-words text-base font-black leading-5 text-[#17130E]">原文連結</h3>
              </div>
              <span className="shrink-0 font-mono text-[10px] font-black text-[#6E685D]">{product.postUrls.length} POSTS</span>
            </div>

            <ul className="mt-3 grid min-w-0 grid-cols-2 gap-2 min-[420px]:grid-cols-3">
              {product.postUrls.map((url, index) => (
                <li key={`${url}-${index}`} className="min-w-0">
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => trackOutboundPttClick(product.id)}
                    aria-label={`${product.productName}原文 ${index + 1}，另開新分頁`}
                    className="group flex min-w-0 items-center justify-between gap-2 border-2 border-[#17130E] bg-[#FFFDF8] px-2.5 py-2.5 text-sm font-black text-[#0F7C7C] underline decoration-[#0F7C7C]/40 underline-offset-4 hover:bg-[#0F7C7C]/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F7C7C]"
                  >
                    <span className="min-w-0 truncate">原文 {String(index + 1).padStart(2, '0')}</span>
                    <ExternalLink size={15} className="shrink-0" aria-hidden="true" />
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  )
}
