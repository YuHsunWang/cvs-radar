import { BarChart3, ExternalLink, MessageSquareText, ThumbsUp, TriangleAlert, UserRound } from 'lucide-react'
import {
  Product,
  consensusTone,
  scoreToneClass,
  volumePercent,
} from '@/lib/data'

type ProductDetailProps = {
  product: Product
}

export default function ProductDetail({ product }: ProductDetailProps) {
  const hasDistribution =
    product.positivePct !== null && product.neutralPct !== null && product.negativePct !== null
  const hasPosts = product.postUrls.length > 0
  const tone = consensusTone(product.consensus)
  const scoreTone = scoreToneClass(product.recommendationScore)
  const volume = volumePercent(product.volumeLevel)
  const positivePct = product.positivePct ?? 0
  const neutralPct = product.neutralPct ?? 0
  const negativePct = product.negativePct ?? 0

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-[#FFFDF8] p-3">
      <div className="grid grid-cols-1 gap-3 min-[380px]:grid-cols-[0.78fr_1fr]">
        <div>
          <p className="text-lg font-black text-slate-950">單品判斷</p>
          <div className="mt-3">
            <span
              className={`font-black ${scoreTone} ${
                product.recommendationScore === null ? 'text-3xl' : 'text-5xl'
              }`}
            >
              {product.recommendationScore ?? '暫無'}
            </span>
            {product.recommendationScore !== null ? (
              <span className="ml-1 text-xl font-bold text-slate-600">/ 100</span>
            ) : null}
            <p className="font-bold text-slate-600">
              {product.recommendationScore === null ? '暫無可靠分數' : '推薦分數'}
            </p>
            <div className="mt-1 text-xs font-semibold text-slate-500">
              <p>公平分數 {product.fairScore ?? '-'}</p>
              <p>信心度 {product.confidence}</p>
            </div>
          </div>
        </div>
        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="font-black text-slate-950">共識分布</p>
            <span
              className={`shrink-0 rounded-md border px-2 py-1 text-xs font-black ${
                tone === 'good'
                  ? 'border-[#2E9E5B] text-[#2E9E5B]'
                  : tone === 'mixed'
                    ? 'border-[#E0A417] text-[#D97706]'
                    : 'border-slate-400 text-slate-500'
              }`}
            >
              {product.consensus}
            </span>
          </div>

          {hasDistribution ? (
            <>
              <div
                aria-label={`正向 ${positivePct}%，中立 ${neutralPct}%，負向 ${negativePct}%`}
                className="flex h-8 overflow-hidden rounded-md text-sm font-black text-white"
              >
                <div className="grid min-w-0 place-items-center overflow-hidden bg-[#2E9E5B]" style={{ width: `${positivePct}%` }}>
                  {positivePct >= 12 ? `${positivePct}%` : null}
                </div>
                <div className="grid min-w-0 place-items-center overflow-hidden bg-[#E0A417]" style={{ width: `${neutralPct}%` }}>
                  {neutralPct >= 12 ? `${neutralPct}%` : null}
                </div>
                <div className="grid min-w-0 place-items-center overflow-hidden bg-[#D64545]" style={{ width: `${negativePct}%` }}>
                  {negativePct >= 12 ? `${negativePct}%` : null}
                </div>
              </div>
              <p className="mt-2 text-sm font-black">
                <span className="text-[#2E9E5B]">正向 {positivePct}%</span>
                <span className="text-[#D97706]"> · 中立 {neutralPct}%</span>
                <span className="text-[#D64545]"> · 負向 {negativePct}%</span>
              </p>
            </>
          ) : (
            <p className="rounded-md bg-slate-100 px-2.5 py-2 text-sm font-semibold leading-5 text-slate-600">
              有效樣本不足，暫不顯示比例
            </p>
          )}
        </div>
      </div>

      <div className="my-4 border-t border-slate-200 pt-3">
        <div className="mb-2 flex items-center justify-between">
          <p className="font-black text-slate-950">聲量指標</p>
          <span className="inline-flex items-center gap-1 rounded-md border border-[#0F7C7C] bg-[#0F7C7C]/10 px-2 py-1 text-sm font-black text-[#0F7C7C]">
            <BarChart3 size={16} aria-hidden="true" />
            聲量{product.volumeLevel}
          </span>
        </div>
        <div className="h-3 rounded-full bg-slate-100">
          <div className="h-3 rounded-full bg-[#0F7C7C]" style={{ width: `${volume}%` }} />
        </div>
        <p className="mt-2 text-right font-bold text-slate-600">
          {product.nPosts} 篇貼文 · {product.nComments} 則留言
        </p>
      </div>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <UserRound size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          作者評價
        </h3>
        <blockquote className="mt-3 rounded-r-md border-l-4 border-[#0F7C7C] bg-slate-50 px-3 py-2.5 text-sm font-semibold leading-6 text-slate-700">
          {product.excerpt || '未擷取到足夠的作者評價，請查看原文。'}
        </blockquote>
      </section>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <MessageSquareText size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          留言評價
        </h3>
        <div className="mt-3 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 p-3 min-[380px]:grid-cols-2">
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-[#0F7C7C]">
              <ThumbsUp size={17} aria-hidden="true" />
              大家喜歡的點
            </h4>
            <ul className="space-y-1 text-sm font-semibold text-slate-700">
              {(product.likes.length ? product.likes : ['無']).slice(0, 4).map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </div>
          <div className="border-t border-slate-200 pt-3 min-[380px]:border-l min-[380px]:border-t-0 min-[380px]:pl-3 min-[380px]:pt-0">
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-[#D64545]">
              <TriangleAlert size={17} aria-hidden="true" />
              需要留意的點
            </h4>
            <ul className="space-y-1 text-sm font-semibold text-slate-700">
              {(product.cautions.length ? product.cautions : ['無']).slice(0, 4).map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {hasPosts ? (
        <section className="mt-4 border-t border-slate-200 pt-4">
          <h3 className="flex items-center gap-2 font-black text-slate-950">
            <ExternalLink size={20} className="text-[#0F7C7C]" aria-hidden="true" />
            原文連結
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {product.postUrls.map((url, index) => (
              <a
                key={url}
                href={url}
                target="_blank"
                rel="noreferrer"
                aria-label={`${product.productName}原文 ${index + 1}，另開新分頁`}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-bold text-[#0F7C7C] underline decoration-[#0F7C7C]/30 underline-offset-4 hover:bg-[#0F7C7C]/5"
              >
                原文 {index + 1}
                <ExternalLink size={14} aria-hidden="true" />
              </a>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
