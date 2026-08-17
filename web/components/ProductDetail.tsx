'use client'

import { ExternalLink, ThumbsUp, TriangleAlert } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { Product } from '@/lib/data'

type ProductDetailProps = {
  product: Product
}

/**
 * The back of the shelf label: evidence first, then the model's summary.
 *
 * Styled with the `sl-*` system the collapsed card uses rather than in Tailwind
 * utilities, because the two sat side by side and read as different apps.
 *
 * The author's summary leads, then the like/caution evidence: the summary is one
 * short sentence that frames what follows, so reading it first costs almost
 * nothing and makes the bullets land as detail rather than as a list to parse
 * cold.
 *
 * Kept deliberately short. Evidence items are at most 19 characters and the
 * median summary is 17, so the height this panel used to have was going into
 * per-item containers, not text — and an inline expander that pushes the next
 * product off a 360×800 screen defeats its own purpose. Both polarities share one
 * heading and one list; each row is carried by an icon in the polarity colour,
 * which keeps the distinction legible in greyscale and for colour-blind readers,
 * where colour alone would not be.
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
      {/* Rendered when there is a summary OR the row is provisional: a provisional
          row with no summary still has to admit it is a rule fallback, otherwise
          it is presented as though a model had labelled it. */}
      {takes.length > 0 || product.reviewProvisional ? (
        <section>
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
                {/* Numbering only earns its place when there are several
                    reviewers to tell apart. */}
                {takes.length > 1 ? <span>{String(index + 1).padStart(2, '0')}</span> : null}
                {take}
              </p>
            ))
          ) : (
            <p className="sl-k-none">尚未完成模型整理，請看原文</p>
          )}
        </section>
      ) : null}

      <section className={takes.length > 0 || product.reviewProvisional ? 'sl-k-sec' : ''}>
        <h3 className="sl-k-head">
          EVIDENCE
          <b>評價重點</b>
        </h3>

        {hasEvidence ? (
          <ul className="sl-k-list">
            {product.likes.map((item) => (
              <EvidenceRow key={`+${item}`} tone="up" text={item} />
            ))}
            {product.cautions.map((item) => (
              <EvidenceRow key={`-${item}`} tone="dn" text={item} />
            ))}
          </ul>
        ) : (
          <p className="sl-k-none">留言沒有集中的優缺點</p>
        )}
      </section>

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

function EvidenceRow({ tone, text }: { tone: 'up' | 'dn'; text: string }) {
  const isUp = tone === 'up'
  return (
    <li className={`sl-k-row sl-k-${tone} sl-t3`}>
      <b aria-hidden="true">
        {isUp ? (
          <ThumbsUp size={13} strokeWidth={2.6} />
        ) : (
          <TriangleAlert size={13} strokeWidth={2.6} />
        )}
      </b>
      <span>
        {/* The icon is the only visual carrier of polarity, so screen readers
            need it spelled out. */}
        <span className="sr-only">{isUp ? '優點：' : '缺點：'}</span>
        {text}
      </span>
    </li>
  )
}
