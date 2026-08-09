'use client'

import Link from 'next/link'
import { useMemo, useState, type CSSProperties } from 'react'
import ShelfCard from '@/components/ShelfCard'
import { trackProductExpand } from '@/lib/analytics'
import {
  DataPayload,
  Product,
  brands,
  comprehensiveScore,
  displayBrand,
  formatDisplayDate,
  sortProducts,
} from '@/lib/data'
import {
  FlavorGroup,
  SoftServeItem,
  buildFlavorGroups,
  comparableFlavors,
  flavorAnchorId,
  flavorVerdict,
  freshness,
  freshnessLabel,
  groupedProductIds,
  partnerFlavor,
  softServeItems,
} from '@/lib/soft-serve'

type SoftServeZoneProps = {
  initialPayload: DataPayload
}

// Same 70/50 bands as ShelfCard, but under ss- names: the shelf's tone classes
// only take effect alongside .sl-score.
function scoreTone(score: number | null): string {
  if (score === null) return 'ss-t-na'
  if (score >= 70) return 'ss-t-good'
  if (score >= 50) return 'ss-t-mid'
  return 'ss-t-low'
}

export default function SoftServeZone({ initialPayload }: SoftServeZoneProps) {
  const [brand, setBrand] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const allItems = useMemo(() => softServeItems(initialPayload.products), [initialPayload])

  const availableBrands = useMemo(
    () => brands.filter((name) => allItems.some((item) => displayBrand(item.product.brand) === name)),
    [allItems],
  )

  const products = useMemo(
    () =>
      allItems
        .map((item) => item.product)
        .filter((product) => !brand || displayBrand(product.brand) === brand),
    [allItems, brand],
  )

  const groups = useMemo(() => buildFlavorGroups(products), [products])
  const linkable = useMemo(() => comparableFlavors(groups), [groups])

  const leftovers = useMemo(() => {
    const grouped = groupedProductIds(groups)
    return sortProducts(
      products.filter((product) => !grouped.has(product.id)),
      'recentRecommendationDesc',
    )
  }, [groups, products])

  function toggleProduct(product: Product) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(product.id)) {
        next.delete(product.id)
      } else {
        next.add(product.id)
        trackProductExpand({
          productId: product.id,
          brand: product.brand,
          category: product.category,
          fairScore: product.fairScore,
        })
      }
      return next
    })
  }

  return (
    <div className="sl-page ss-page">
      <header className="sl-sign">
        <div className="sl-sign-main">
          <div className="sl-sign-mark" aria-hidden="true">
            <span className="sl-sweep" />
          </div>
          <div>
            <p className="sl-sign-kicker">便利商店・期間限定</p>
            <h1 className="sl-sign-title">
              霜淇淋專區 <span>SOFT&nbsp;SERVE</span>
            </h1>
          </div>
        </div>
        <Link href="/" className="ss-back">
          ← 回貨架
        </Link>
      </header>

      <div className="sl-aislebar">
        <span className="sl-ab-slot">本區 {allItems.length} 品</span>
        <span className="sl-ab-sep">·</span>
        <span>上架更新 {formatDisplayDate(initialPayload.generatedAt)}</span>
        <span className="sl-ab-sep">·</span>
        <span>分數＝綜合評分／滿分 100</span>
      </div>

      <p className="ss-note">
        霜淇淋幾乎都是期間限定,但本站沒有官方上下架資料。這裡的日期是
        <b> PTT 最新討論日</b>,「熱議中／已沉寂」描述的是討論熱度,不等於現在買不買得到。
      </p>

      {/* ss-controls, not sl-controls: the shelf hides its inline filter bar on
          phones in favour of a sheet, and one brand row does not need one. */}
      <div className="ss-controls">
        <div className="sl-filterrow">
          <span className="sl-eyebrow">品牌</span>
          <nav className="sl-chips" aria-label="品牌">
            <button
              type="button"
              className={`sl-chip-btn${brand === null ? ' sl-on' : ''}`}
              onClick={() => setBrand(null)}
            >
              全部
            </button>
            {availableBrands.map((name) => (
              <button
                key={name}
                type="button"
                className={`sl-chip-btn${brand === name ? ' sl-on' : ''}`}
                onClick={() => setBrand(brand === name ? null : name)}
              >
                {name}
              </button>
            ))}
          </nav>
        </div>
      </div>

      <section className="ss-section" aria-labelledby="ss-compare">
        <h2 className="ss-h2" id="ss-compare">
          單雙口味對照
        </h2>
        <p className="ss-sub">
          同一個口味有單吃、也有跟別的口味做成雙拼時,才排得進這裡——共 {groups.length} 組。
        </p>

        {groups.length === 0 ? (
          <div className="sl-empty">
            <p>
              {brand ? `${brand} 沒有可對照的雙口味品項` : '目前沒有可對照的口味'}
            </p>
            {brand ? (
              <button type="button" onClick={() => setBrand(null)}>
                看全部品牌
              </button>
            ) : null}
          </div>
        ) : (
          <div className="ss-groups">
            {groups.map((group) => (
              <FlavorCard key={group.flavor} group={group} linkable={linkable} />
            ))}
          </div>
        )}
      </section>

      <section className="ss-section" aria-labelledby="ss-rest">
        <h2 className="ss-h2" id="ss-rest">
          其餘霜淇淋
        </h2>
        <p className="ss-sub">只出現過一種吃法,沒有可比較的另一半——共 {leftovers.length} 支。</p>

        <main className="sl-shelf">
          {leftovers.map((product, index) => (
            <ShelfCard
              key={product.id}
              product={product}
              rank={index + 1}
              isExpanded={expanded.has(product.id)}
              onToggle={() => toggleProduct(product)}
            />
          ))}
        </main>
      </section>
    </div>
  )
}

function FlavorCard({ group, linkable }: { group: FlavorGroup; linkable: Set<string> }) {
  const verdict = flavorVerdict(group)
  const rows = group.single ? [group.single, ...group.duals] : group.duals

  return (
    <article className="ss-group" id={flavorAnchorId(group.flavor)}>
      <header className="ss-g-head">
        <h3 className="ss-g-flavor">{group.flavor}</h3>
        <span className="ss-g-count">{rows.length} 種吃法</span>
      </header>

      <ul className="ss-rows">
        {rows.map((item) => (
          <FlavorRow key={item.product.id} item={item} flavor={group.flavor} linkable={linkable} />
        ))}
      </ul>

      {verdict ? (
        <p className={`ss-verdict ss-v-${verdict.winner}`}>→ {verdict.text}</p>
      ) : (
        <p className="ss-verdict ss-v-none">
          → {group.single ? '其中一邊還沒有足夠評分,無法比較' : '這個口味只出過雙拼,沒有單吃可比'}
        </p>
      )}
    </article>
  )
}

function FlavorRow({
  item,
  flavor,
  linkable,
}: {
  item: SoftServeItem
  flavor: string
  linkable: Set<string>
}) {
  const score = comprehensiveScore(item.product)
  const badge = freshnessLabel(freshness(item.product.latestDate))
  // Full date, not MM/DD: the zone spans more than a year, so a bare 08/04 is
  // ambiguous between a product from this summer and one from the last.
  const date = item.product.latestDate ? item.product.latestDate.replaceAll('-', '/') : '—'
  const partner = item.isDual ? partnerFlavor(item, flavor) : ''

  return (
    <li className="ss-row" title={item.product.productName}>
      <div className="ss-r-top">
        <span className={`ss-r-kind${item.isDual ? ' ss-dual' : ''}`}>
          {!item.isDual ? (
            '單吃'
          ) : linkable.has(partner) ? (
            <a className="ss-r-jump" href={`#${flavorAnchorId(partner)}`} title={`看 ${partner} 的對照`}>
              × {partner}
            </a>
          ) : (
            `× ${partner}`
          )}
        </span>
        <span className={`ss-r-score ${scoreTone(score)}`}>
          {score === null ? '暫無' : score}
        </span>
      </div>

      <div className="ss-bar" aria-hidden="true">
        <span
          className={`ss-bar-fill ${scoreTone(score)}`}
          style={{ '--ss-w': `${score ?? 0}%` } as CSSProperties}
        />
      </div>

      <div className="ss-r-meta">
        <span className="ss-m-brand">{displayBrand(item.product.brand)}</span>
        <span>最新討論 {date}</span>
        {badge ? <span className={`ss-m-badge ss-b-${badge === '熱議中' ? 'hot' : 'quiet'}`}>{badge}</span> : null}
        {item.product.confidence === '低' ? <span className="ss-m-warn">樣本少</span> : null}
      </div>
    </li>
  )
}
