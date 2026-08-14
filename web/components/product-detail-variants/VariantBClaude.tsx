'use client'

import { ExternalLink } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { Product } from '@/lib/data'

type Props = {
  product: Product
}

/**
 * Variant B's information architecture — evidence first, model summary demoted —
 * rendered in the shelf-label design system rather than in generic panel styling.
 *
 * The collapsed row is a price tag; this is the back of that same tag. It keeps
 * the card's ink, hairlines, mono micro-labels and 3px corners, and separates
 * itself from the closed state by surface (faint ruled docket paper) instead of
 * by switching to a different visual language, which is what the previous panel
 * did.
 */
export default function VariantBClaude({ product }: Props) {
  // One rewrite per reviewing post, joined with 「；」 upstream. Splitting them
  // back out is the honest reading: they are separate people, not one sentence.
  const takes = (product.excerpt || '')
    .split('；')
    .map((part) => part.trim())
    .filter(Boolean)

  return (
    <div className="sl-d">
      <Evidence
        label="大家喜歡的點"
        kicker="LIKED"
        items={product.likes}
        tone="like"
        emptyText="這批留言沒有集中的優點"
      />
      <Evidence
        label="需要留意的點"
        kicker="CAUTION"
        items={product.cautions}
        tone="warn"
        emptyText="這批留言沒有提出缺點"
      />

      {/* Rendered whenever there is a summary OR the row is provisional. A
          provisional row with no excerpt still has to say so — hiding the marker
          with the section would silently present a rule fallback as a real label. */}
      {takes.length > 0 || product.reviewProvisional ? (
        <section className="sl-d-sec">
          <h3 className="sl-d-head">
            SUMMARY
            <b>
              作者評價
              {product.reviewProvisional ? <span className="sl-d-prov">暫定</span> : null}
            </b>
            {takes.length > 1 ? <span className="sl-d-count">{takes.length} 篇</span> : null}
          </h3>
          {takes.length > 0 ? (
            <div className="sl-d-sum">
              {takes.map((take, index) => (
                <div key={take} className="sl-d-take">
                  {/* Numbering only earns its place when there is more than one
                      reviewer to tell apart. */}
                  {takes.length > 1 ? <em>{String(index + 1).padStart(2, '0')}</em> : null}
                  <p>{take}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="sl-d-none">尚未完成模型整理，請看原文</p>
          )}
        </section>
      ) : null}

      {product.postUrls.length > 0 ? (
        <div className="sl-d-src">
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
              <ExternalLink size={12} aria-hidden="true" />
            </a>
          ))}
        </div>
      ) : null}
    </div>
  )
}

type EvidenceProps = {
  label: string
  kicker: string
  items: string[]
  tone: 'like' | 'warn'
  emptyText: string
}

function Evidence({ label, kicker, items, tone, emptyText }: EvidenceProps) {
  return (
    <section className="sl-d-sec">
      <h3 className="sl-d-head">
        {kicker}
        <b>{label}</b>
        {items.length > 0 ? <span className="sl-d-count">{items.length}</span> : null}
      </h3>
      {items.length > 0 ? (
        <ul className="sl-d-ev">
          {items.map((item) => (
            <li key={item} className={`sl-d-item ${tone === 'like' ? 'sl-d-like' : 'sl-d-warn'}`}>
              <i aria-hidden="true" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        // An empty half states what was found, not the word 無 dressed as a
        // review point. It stays a struck-out docket line so the eye skips it.
        <p className="sl-d-none">{emptyText}</p>
      )}
    </section>
  )
}
