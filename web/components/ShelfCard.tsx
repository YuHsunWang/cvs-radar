import { useId } from 'react'
import ProductDetail from '@/components/ProductDetail'
import { Product, comprehensiveScore, displayBrand } from '@/lib/data'

function scoreTone(score: number | null): string {
  if (score === null) return 'sl-na'
  if (score >= 70) return 'sl-good'
  if (score >= 50) return 'sl-mid'
  return 'sl-low'
}

type ShelfCardProps = {
  product: Product
  rank: number
  isExpanded: boolean
  onToggle: () => void
}

export default function ShelfCard({ product, rank, isExpanded, onToggle }: ShelfCardProps) {
  const score = comprehensiveScore(product)
  const detailId = useId()

  return (
    <article className="sl-label">
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={detailId}
        onClick={onToggle}
        className="sl-rowbtn"
      >
        <div className="sl-row">
          <span className="sl-channel">{displayBrand(product.brand)}</span>
          <div className="sl-card-main">
            <h2 className="sl-pname">{product.productName?.trim() || '商品名稱待確認'}</h2>
            <span className="sl-meta">
              {product.price != null ? `$${product.price} · ` : ''}{product.nPosts} 篇心得
            </span>
          </div>
          <span className={`sl-score ${scoreTone(score)}`}>{score === null ? '—' : score}</span>
        </div>
      </button>
      {isExpanded ? (
        <div id={detailId} className="sl-detail">
          <ProductDetail product={product} rank={rank} />
        </div>
      ) : null}
    </article>
  )
}
