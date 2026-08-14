'use client'

import { ExternalLink } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { Product } from '@/lib/data'

type Props = {
  product: Product
}

/**
 * Variant B's IA in the shelf-label system, built for vertical economy.
 *
 * The evidence is tiny — items are at most 19 characters, the median summary is
 * 17 — so the panel's height was going into containers rather than text. Here the
 * two polarities share one heading and one list, each row carried by a coloured
 * ＋ / － glyph instead of its own bordered card. That is what makes it fit under
 * the collapsed card on a 360×800 phone without pushing the next product off
 * screen, which is the whole point of an inline expander.
 */
export default function VariantBCompact({ product }: Props) {
  const takes = (product.excerpt || '')
    .split('；')
    .map((part) => part.trim())
    .filter(Boolean)

  const hasEvidence = product.likes.length > 0 || product.cautions.length > 0

  return (
    <div className="sl-k">
      <h3 className="sl-k-head">
        EVIDENCE
        <b>評價重點</b>
      </h3>

      {hasEvidence ? (
        <ul className="sl-k-list">
          {product.likes.map((item) => (
            <li key={`+${item}`} className="sl-k-row sl-k-up">
              <b aria-hidden="true">＋</b>
              <span>
                <span className="sr-only">優點：</span>
                {item}
              </span>
            </li>
          ))}
          {product.cautions.map((item) => (
            <li key={`-${item}`} className="sl-k-row sl-k-dn">
              <b aria-hidden="true">－</b>
              <span>
                <span className="sr-only">缺點：</span>
                {item}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sl-k-none">留言沒有集中的優缺點</p>
      )}

      {/* Shown whenever there is a summary OR the row is provisional: a
          provisional row with no summary still has to admit it is a rule
          fallback rather than a model label. */}
      {takes.length > 0 || product.reviewProvisional ? (
        <section className="sl-k-sec">
          <h3 className="sl-k-head">
            SUMMARY
            <b>
              作者評價
              {product.reviewProvisional ? <span className="sl-k-prov">暫定</span> : null}
            </b>
            {takes.length > 1 ? <i>{takes.length} 篇</i> : null}
          </h3>
          {takes.length > 0 ? (
            takes.map((take, index) => (
              <p key={take} className="sl-k-sum">
                {takes.length > 1 ? <span>{String(index + 1).padStart(2, '0')}</span> : null}
                {take}
              </p>
            ))
          ) : (
            <p className="sl-k-none">尚未完成模型整理，請看原文</p>
          )}
        </section>
      ) : null}

      {product.postUrls.length > 0 ? (
        <div className="sl-k-src">
          <span>原文</span>
          {product.postUrls.map((url, index) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noreferrer"
              onClick={() => trackOutboundPttClick(product.id)}
              aria-label={`${product.productName}原文 ${index + 1}，另開新分頁`}
            >
              PTT {String(index + 1).padStart(2, '0')}
              <ExternalLink size={11} aria-hidden="true" />
            </a>
          ))}
        </div>
      ) : null}
    </div>
  )
}
