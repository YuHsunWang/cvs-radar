import { CakeSlice, Cookie, Croissant, CupSoda, IceCreamCone, Package, Soup, type LucideIcon } from 'lucide-react'
import { useId } from 'react'
import ProductDetail from '@/components/ProductDetail'
import { Product, comprehensiveScore, displayBrand, displayCategory } from '@/lib/data'

// One icon per category group so neighbouring cards differ at a glance.
const CATEGORY_ICON: Record<string, LucideIcon> = {
  正餐: Soup,
  甜點: CakeSlice,
  冰品: IceCreamCone,
  飲料: CupSoda,
  麵包: Croissant,
  零食: Cookie,
  其他: Package,
}

function scoreTone(score: number | null): string {
  if (score === null) return 'sl-na'
  if (score >= 85) return 'sl-great'
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
  const channel = displayBrand(product.brand)
  const category = displayCategory(product.category)
  const CategoryIcon = CATEGORY_ICON[category] ?? Package

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
          <span className="sl-cat" data-cat={category} aria-hidden="true">
            <CategoryIcon size={24} strokeWidth={1.8} />
          </span>
          <div className="sl-card-main">
            <div className="sl-card-top">
              <span className="sl-channel"><span className="sl-channel-dot" data-brand={channel} aria-hidden="true" />{channel}</span>
              <span className="sl-meta">
                {product.price != null ? `$${product.price} · ` : ''}{product.nPosts} 篇心得
              </span>
            </div>
            <h2 className="sl-pname">{product.productName?.trim() || '商品名稱待確認'}</h2>
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
