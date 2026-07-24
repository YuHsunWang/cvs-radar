import { ChevronDown, ChevronUp } from 'lucide-react'
import { useId, type CSSProperties } from 'react'
import CountUp from '@/components/CountUp'
import ProductDetail from '@/components/ProductDetail'
import {
  Product,
  comprehensiveScore,
  consensusTone,
  displayBrand,
  displayCategory,
} from '@/lib/data'

// Shelf-edge label palette: brand-colour rails + gold/silver/bronze rank medals.
const RAIL: Record<string, string> = {
  '7-11': '#F26522',
  全家: '#009B4C',
  萊爾富: '#E51F26',
  OK: '#F5A623',
  美聯社: '#6C3DBF',
  其他: '#6B7280',
}
const MEDAL: Record<number, string> = { 1: 'sl-gold', 2: 'sl-silver', 3: 'sl-bronze' }

function scoreTone(score: number | null): string {
  if (score === null) return 'sl-na'
  if (score >= 70) return 'sl-good'
  if (score >= 50) return 'sl-mid'
  return 'sl-low'
}

const stampTone: Record<'good' | 'mixed' | 'low', string> = {
  good: 'sl-s-good',
  mixed: 'sl-s-mixed',
  low: 'sl-s-lowc',
}

type ShelfCardProps = {
  product: Product
  rank: number
  isExpanded: boolean
  onToggle: () => void
}

export default function ShelfCard({ product, rank, isExpanded, onToggle }: ShelfCardProps) {
  const brand = displayBrand(product.brand)
  const score = comprehensiveScore(product)
  const volume = product.nPosts + product.nComments
  const pop = (product.likes[0] ?? '').replace(/\s+/g, ' ').trim().slice(0, 16)
  const date = product.latestDate ? product.latestDate.replaceAll('-', '/') : '—'
  const detailId = useId()

  return (
    <article className={`sl-label${rank === 1 ? ' sl-top' : ''}`}>
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={detailId}
        onClick={onToggle}
        className="sl-rowbtn"
      >
        <div className="sl-row">
          <div className="sl-rail" style={{ '--sl-rail': RAIL[brand] } as CSSProperties}>
            <span>{brand}</span>
          </div>

          <div className="sl-body">
            <div className="sl-slotline">
              {rank in MEDAL ? (
                <span className={`sl-medal ${MEDAL[rank]}`} title={`第 ${rank} 名`}>
                  <b>{rank}</b>
                </span>
              ) : (
                <span className="sl-slot">架位 {String(rank).padStart(2, '0')}</span>
              )}
              <span>上架 {date}</span>
            </div>

            <h2 className="sl-pname">{product.productName}</h2>

            <div className="sl-tags">
              <span className="sl-tag">{displayCategory(product.category)}</span>
              {product.price != null ? <span className="sl-tag sl-price">${product.price}</span> : null}
              <span className="sl-tag sl-ghost">聲量 {volume}</span>
            </div>

            <div className="sl-stampline">
              <span className={`sl-stamp ${stampTone[consensusTone(product.consensus)]}`}>
                {product.consensus}
              </span>
              {pop ? <p className="sl-pop">「{pop}」</p> : null}
            </div>
          </div>

          <div className="sl-pricebox">
            <div className="sl-pb-top">
              <span className="sl-pb-label">綜合評分</span>
              <div className={`sl-score ${scoreTone(score)}`}>
                {score === null ? (
                  <span className="sl-s-na">暫無</span>
                ) : (
                  <>
                    <span className="sl-s-num">
                      <CountUp end={score} />
                    </span>
                    <span className="sl-s-unit">分</span>
                  </>
                )}
              </div>
              {product.confidence === '低' ? <span className="sl-chip-warn">樣本少</span> : null}
            </div>
            <span className="sl-chevron" aria-hidden="true">
              {isExpanded ? <ChevronUp size={22} /> : <ChevronDown size={22} />}
            </span>
          </div>
        </div>
      </button>

      {isExpanded ? (
        <div id={detailId} className="sl-detail">
          <ProductDetail product={product} />
        </div>
      ) : null}
    </article>
  )
}
