import ProductDetail from '@/components/ProductDetail'
import { BarChart3, ChevronDown, ChevronUp, CircleCheck, CircleMinus, CircleX } from 'lucide-react'
import { useId } from 'react'
import { Product, consensusTone, displayBrand, displayCategory, scoreToneClass } from '@/lib/data'

const brandBadgeStyles: Record<string, string> = {
  '7-11': 'bg-[#00824E] text-white',
  全家: 'bg-[#0876CE] text-white',
  萊爾富: 'bg-[#E51F26] text-white',
  OK: 'bg-[#EF7D00] text-white',
  美聯社: 'bg-[#6C3DBF] text-white',
  其他: 'bg-slate-500 text-white',
}

const toneStyles = {
  good: 'text-[#2E7D32]',
  mixed: 'text-[#D97706]',
  low: 'text-slate-500',
}

function ConsensusIcon({ consensus }: { consensus: string }) {
  if (consensus === '一致好評') return <CircleCheck size={16} aria-hidden="true" />
  if (consensus === '一致負評') return <CircleX size={16} aria-hidden="true" />
  return <CircleMinus size={16} aria-hidden="true" />
}

type ProductCardProps = {
  product: Product
  rank: number
  isExpanded: boolean
  onToggle: () => void
}

export default function ProductCard({ product, rank, isExpanded, onToggle }: ProductCardProps) {
  const brand = displayBrand(product.brand)
  const tone = consensusTone(product.consensus)
  const scoreTone = scoreToneClass(product.recommendationScore)
  const detailId = useId()

  return (
    <article className="self-start rounded-lg border border-slate-200 bg-white p-3 shadow-card transition hover:border-[#0F7C7C]/40">
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={detailId}
        onClick={onToggle}
        className="block w-full rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-[#0F7C7C] focus-visible:ring-offset-2"
      >
        <div className="grid grid-cols-[2.25rem_minmax(0,1fr)_4.5rem] gap-2.5">
        <div className="pt-1 text-3xl font-black text-[#0F7C7C]">{rank}</div>
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2">
            <span className={`rounded-md px-3 py-1 text-sm font-black ${brandBadgeStyles[brand]}`}>
              {brand}
            </span>
          </div>
          <h2 className="line-clamp-2 text-lg font-black leading-snug text-slate-950">
            {product.productName}
          </h2>
          <div className="mt-2 space-y-1 text-sm font-bold">
            <p className={`flex items-center gap-1 ${toneStyles[tone]}`}>
              <ConsensusIcon consensus={product.consensus} />
              {product.consensus}
            </p>
            <p className="flex items-center gap-1 text-slate-700">
              <BarChart3 size={16} aria-hidden="true" />
              聲量 {product.nPosts + product.nComments}（{product.volumeLevel}）
            </p>
            <p className="text-slate-500">最新發文 {product.latestDate?.replaceAll('-', '/') ?? '日期未知'}</p>
            <span className="inline-flex rounded-md border border-slate-300 bg-slate-50 px-2 py-0.5 text-slate-600">
              {product.price == null ? displayCategory(product.category) : `$${product.price} · ${displayCategory(product.category)}`}
            </span>
          </div>
        </div>
        <div className="flex min-h-24 flex-col items-end justify-between text-right font-black">
          <div>
            <span
              className={`block leading-none ${scoreTone} ${
                product.recommendationScore === null ? 'text-xl' : 'text-3xl'
              }`}
            >
              {product.recommendationScore ?? '暫無'}
            </span>
            <span className="mt-1 block text-xs text-slate-600">
              推薦分
            </span>
            {product.confidence === '低' ? (
              <span className="mt-1 inline-flex rounded-md border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-800">
                樣本少
              </span>
            ) : null}
          </div>
          <span title={isExpanded ? '收合商品詳情' : '展開商品詳情'} className="text-slate-600">
            {isExpanded ? <ChevronUp size={22} aria-hidden="true" /> : <ChevronDown size={22} aria-hidden="true" />}
          </span>
        </div>
      </div>
      </button>

      {isExpanded ? (
        <div id={detailId}>
          <ProductDetail product={product} />
        </div>
      ) : null}
    </article>
  )
}
