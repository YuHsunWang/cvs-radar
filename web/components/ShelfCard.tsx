import { Package } from 'lucide-react'
import { useId, useState } from 'react'
import ProductDetail from '@/components/ProductDetail'
import { CATEGORY_ICON, scoreTone } from '@/lib/shelf-label'
import { Product, comprehensiveScore, displayBrand, displayCategory, isYoutubeOnly, vegetarianShort } from '@/lib/data'

type ShelfCardProps = {
  product: Product
  isExpanded: boolean
  onToggle: () => void
}

export default function ShelfCard({ product, isExpanded, onToggle }: ShelfCardProps) {
  const score = comprehensiveScore(product)
  const detailId = useId()
  // Mount the detail on first open and keep it, so closing can animate back to 0.
  const [mounted, setMounted] = useState(isExpanded)
  if (isExpanded && !mounted) setMounted(true)
  const channel = displayBrand(product.brand)
  const category = displayCategory(product.category)
  const CategoryIcon = CATEGORY_ICON[category] ?? Package
  const youtubeOnly = isYoutubeOnly(product)
  // The excerpt joins one rewrite per post with 「；」; the card shows the first one.
  // A product only YouTube covers has no excerpt, so its newest creator verdict stands in.
  const summary = youtubeOnly ? product.youtube[0].summary : (product.excerpt || '').split('；')[0].trim()

  return (
    <article className="sl-label" id={`p-${product.id}`}>
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={detailId}
        onClick={onToggle}
        className="sl-rowbtn"
      >
        <div className="sl-row">
          <span className="sl-cat" data-cat={category} aria-hidden="true">
            <CategoryIcon size={24} strokeWidth={1.8} />
          </span>
          {/* The icon is aria-hidden and the detail no longer prints the category. */}
          <span className="sr-only">分類：{category}</span>
          <div className="sl-card-main">
            <div className="sl-card-top">
              <span className="sl-channel"><span className="sl-channel-dot" data-brand={channel} aria-hidden="true" />{channel}</span>
              {product.price != null ? <span className="sl-price">${product.price}</span> : null}
              {product.vegetarian ? <span className="sl-veg">{vegetarianShort(product.vegetarian)}</span> : null}
              {youtubeOnly
                ? <span className="sl-yt"><span aria-hidden="true">🎬 </span>YouTuber 開箱</span>
                : <span className="sl-meta">{product.nPosts} 篇心得</span>}
            </div>
            <h2 className="sl-pname">{product.productName?.trim() || '商品名稱待確認'}</h2>
            {/* Open, the same line leads the 大家怎麼說 list; showing it twice reads as a repeat. */}
            {summary && !isExpanded ? <p className="sl-summary">{summary}</p> : null}
          </div>
          <span className={`sl-score ${scoreTone(score)}`}>{score === null ? '—' : score}</span>
        </div>
      </button>
      <div
        id={detailId}
        className={`sl-detail${isExpanded ? ' sl-open' : ''}`}
        inert={!isExpanded}
      >
        <div className="sl-detail-inner">
          {mounted ? <ProductDetail product={product} /> : null}
        </div>
      </div>
    </article>
  )
}
