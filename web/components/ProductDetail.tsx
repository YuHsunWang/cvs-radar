'use client'

import { ExternalLink, ThumbsUp, TriangleAlert } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { Nutrition, Product } from '@/lib/data'

type ProductDetailProps = {
  product: Product
}

/**
 * The back of the shelf label: what reviewers said, then the two polarities, then
 * the sources they came from.
 *
 * Styled with the `sl-*` system the collapsed card uses rather than in Tailwind
 * utilities, because the two sat side by side and read as different apps.
 *
 * The product name is deliberately NOT repeated here. It used to be, so a name
 * clamped to two lines on the collapsed card could still be read in full; no
 * name in the current data reaches that clamp (longest is 27 characters), so the
 * repeat only pushed the evidence further down. If names ever get long enough to
 * truncate again, restore it rather than letting the panel hide the identity.
 *
 * Three blocks, each with its own count, replacing the earlier single mixed
 * evidence list: a shopper deciding between two products asks "what do people
 * like" and "what goes wrong" as separate questions, and one merged list makes
 * them count icons to answer either. The counts sit in the headings so the
 * balance is readable before the text is.
 *
 * Kept deliberately short. Evidence items are at most 19 characters and the
 * median summary is 17, so height goes into text, not containers; the two
 * polarity blocks sit side by side from 560px up and stack below it, which is
 * what keeps an inline expander from pushing the next product off a 360×800
 * screen. Colour never carries polarity alone — each block keeps its icon and a
 * screen-reader label, so the split survives greyscale and colour-blind vision.
 */
export default function ProductDetail({ product }: ProductDetailProps) {
  // One rewrite per reviewing post, joined with 「；」 upstream. Splitting them
  // back out is the honest reading: they are separate people, not one sentence.
  const takes = (product.excerpt || '')
    .split('；')
    .map((part) => part.trim())
    .filter(Boolean)

  const hasEvidence = product.likes.length > 0 || product.cautions.length > 0

  return (
    <div className="sl-k">
      <div className="sl-detail-meta">
        <span>{product.latestDate ? `最新心得 ${product.latestDate.replaceAll('-', '/')}` : '心得日期不明'}</span>
        <span>共識：{product.consensus}</span>
        <span>討論量：{product.nPosts + product.nComments}</span>
        {product.confidence === '低' ? <span>樣本少</span> : null}
      </div>
      {/* Rendered when there is a summary OR the row is provisional: a provisional
          row with no summary still has to admit it is a rule fallback, otherwise
          it is presented as though a model had labelled it. */}
      {takes.length > 0 || product.reviewProvisional ? (
        <section className="sl-kb sl-kb-say">
          <h4 className="sl-kb-head">
            <b>大家怎麼說</b>
            {takes.length > 0 ? <i>{takes.length} 篇整理</i> : null}
            {product.reviewProvisional ? <span className="sl-k-prov">暫定</span> : null}
          </h4>
          {takes.length > 0 ? (
            <ol className="sl-say-list">
              {takes.map((take, index) => (
                <li key={take} className="sl-say-row">
                  {/* Numbering only earns its place when there are several
                      reviewers to tell apart. */}
                  {takes.length > 1 ? <span>{String(index + 1).padStart(2, '0')}</span> : null}
                  <p>{take}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="sl-k-none">尚未完成模型整理，請看原文</p>
          )}
        </section>
      ) : null}

      {hasEvidence ? (
        <div className="sl-k-split">
          <EvidenceBlock tone="up" items={product.likes} />
          <EvidenceBlock tone="dn" items={product.cautions} />
        </div>
      ) : (
        <p className="sl-k-none sl-k-none-wide">留言沒有集中的優缺點</p>
      )}

      {product.kcal != null ? (
        // Folded by default: most readers came for the reviews, not the numbers.
        <details className="sl-nutri-fold">
          <summary>看營養標示</summary>
          {product.nutrition ? (
            <NutritionLabel nutrition={product.nutrition} />
          ) : (
            // 7-11 publishes calories only; an empty 蛋白質 row would read as "zero".
            <table className="sl-nutri">
              <caption>營養標示</caption>
              <thead>
                <tr><th scope="col" /><th scope="col">每包裝</th></tr>
              </thead>
              <tbody>
                <tr><th scope="row">熱量</th><td>{product.kcal} 大卡</td></tr>
              </tbody>
              <tfoot>
                <tr><td colSpan={2}>取自官網標示；其他營養素未收錄</td></tr>
              </tfoot>
            </table>
          )}
        </details>
      ) : null}

      {product.postUrls.length > 0 ? (
        <div className="sl-k-src">
          <span>
            原文來源<i>{product.postUrls.length}</i>
          </span>
          <div className="sl-k-srclist">
            {product.postUrls.map((url, index) => (
              <a
                key={url}
                href={url}
                target="_blank"
                rel="noreferrer"
                onClick={() => trackOutboundPttClick(product.id)}
                aria-label={`${product.productName}原文 ${index + 1}，另開新分頁`}
              >
                <span className="sl-k-barcode" aria-hidden="true" />
                PTT {String(index + 1).padStart(2, '0')}
                <ExternalLink size={12} aria-hidden="true" />
              </a>
            ))}
          </div>
        </div>
      ) : (
        <p className="sl-k-none sl-k-none-wide">原文連結暫缺</p>
      )}
    </div>
  )
}

const NUTRITION_ROWS = [
  ['kcal', '熱量', '大卡', false],
  ['protein', '蛋白質', '公克', false],
  ['fat', '脂肪', '公克', false],
  ['saturatedFat', '飽和脂肪', '公克', true],
  ['transFat', '反式脂肪', '公克', true],
  ['carbohydrate', '碳水化合物', '公克', false],
  ['sugar', '糖', '公克', true],
  ['sodium', '鈉', '毫克', false],
] as const

function amount(value: number): string {
  return String(Math.round(value * 10) / 10)
}

/** The packaging label, row for row: per serving, plus the package when it holds several. */
function NutritionLabel({ nutrition }: { nutrition: Nutrition }) {
  const multi = nutrition.servings > 1
  return (
    <table className="sl-nutri">
      <caption>營養標示</caption>
      <thead>
        <tr>
          <td colSpan={multi ? 3 : 2} className="sl-nutri-serving">
            {nutrition.servingSize ? <>每一份量 {nutrition.servingSize}<br /></> : null}
            {nutrition.packageServings != null ? <>本包裝含 {amount(nutrition.packageServings)} 份</> : null}
          </td>
        </tr>
        <tr>
          <th scope="col" />
          <th scope="col">每份</th>
          {multi ? <th scope="col">每包裝</th> : null}
        </tr>
      </thead>
      <tbody>
        {NUTRITION_ROWS.map(([key, label, unit, indented]) => (
          <tr key={key}>
            <th scope="row" className={indented ? 'sl-nutri-sub' : undefined}>{label}</th>
            <td>{amount(nutrition.perServing[key])} {unit}</td>
            {multi ? <td>{amount(nutrition.perServing[key] * nutrition.servings)} {unit}</td> : null}
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr><td colSpan={multi ? 3 : 2}>取自全家官網標示</td></tr>
      </tfoot>
    </table>
  )
}

/**
 * One polarity. An empty block is still drawn when the other side has items:
 * "no one complained" and "we found three complaints" are different facts, and
 * dropping the block would let the reader mistake the first for the second.
 */
function EvidenceBlock({ tone, items }: { tone: 'up' | 'dn'; items: string[] }) {
  const isUp = tone === 'up'
  return (
    <section className={`sl-kb sl-kb-${tone}`}>
      <h4 className="sl-kb-head">
        <b aria-hidden="true" className="sl-kb-icon">
          {isUp ? (
            <ThumbsUp size={13} strokeWidth={2.6} />
          ) : (
            <TriangleAlert size={13} strokeWidth={2.6} />
          )}
        </b>
        <b>{isUp ? '推薦點' : '踩雷點'}</b>
        {items.length > 0 ? <i>{items.length}</i> : null}
      </h4>
      {items.length > 0 ? (
        <ul className="sl-kb-list">
          {items.map((item) => (
            <li key={item}>
              {/* The heading names the polarity once for sighted readers; a
                  screen reader meets each row on its own, so it needs it too. */}
              <span className="sr-only">{isUp ? '優點：' : '缺點：'}</span>
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="sl-kb-none">{isUp ? '沒有集中的優點' : '沒有集中的缺點'}</p>
      )}
    </section>
  )
}
