'use client'

import { ExternalLink, ThumbsUp, TriangleAlert } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { Product } from '@/lib/data'

export type Treatment = 't1' | 't2' | 't3'

type Props = {
  product: Product
  treatment: Treatment
}

/**
 * The compact panel with three interchangeable polarity treatments.
 *
 * The layout is fixed — only the device that separates 喜歡 from 留意 changes, so
 * the three can be compared without any other variable moving. Every treatment
 * pairs colour with a shape or icon: colour alone would fail for colour-blind
 * readers and in greyscale, and this is the one distinction the panel exists to
 * make.
 */
export default function VariantBCompactTones({ product, treatment }: Props) {
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
        treatment === 't1' ? (
          <Tinted product={product} />
        ) : (
          <ul className="sl-k-list">
            {product.likes.map((item) => (
              <Row key={`+${item}`} treatment={treatment} tone="up" text={item} />
            ))}
            {product.cautions.map((item) => (
              <Row key={`-${item}`} treatment={treatment} tone="dn" text={item} />
            ))}
          </ul>
        )
      ) : (
        <p className="sl-k-none">留言沒有集中的優缺點</p>
      )}

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

function Row({ treatment, tone, text }: { treatment: Treatment; tone: 'up' | 'dn'; text: string }) {
  const isUp = tone === 'up'
  return (
    <li className={`sl-k-row sl-k-${tone} sl-${treatment}`}>
      <b aria-hidden="true">
        {treatment === 't3' ? (
          isUp ? (
            <ThumbsUp size={13} strokeWidth={2.6} />
          ) : (
            <TriangleAlert size={13} strokeWidth={2.6} />
          )
        ) : isUp ? (
          '＋'
        ) : (
          '－'
        )}
      </b>
      <span>
        <span className="sr-only">{isUp ? '優點：' : '缺點：'}</span>
        {text}
      </span>
    </li>
  )
}

function Tinted({ product }: { product: Product }) {
  return (
    <div className="mt-1.5">
      {product.likes.length > 0 ? (
        <div className="sl-t1-grp sl-t1-up">
          <p className="sl-t1-cap">
            <ThumbsUp size={11} strokeWidth={2.8} aria-hidden="true" />
            大家喜歡
          </p>
          <ul className="sl-k-list">
            {product.likes.map((item) => (
              <li key={item} className="sl-k-row sl-k-up">
                <b aria-hidden="true">＋</b>
                <span>
                  <span className="sr-only">優點：</span>
                  {item}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {product.cautions.length > 0 ? (
        <div className="sl-t1-grp sl-t1-dn">
          <p className="sl-t1-cap">
            <TriangleAlert size={11} strokeWidth={2.8} aria-hidden="true" />
            需要留意
          </p>
          <ul className="sl-k-list">
            {product.cautions.map((item) => (
              <li key={item} className="sl-k-row sl-k-dn">
                <b aria-hidden="true">－</b>
                <span>
                  <span className="sr-only">缺點：</span>
                  {item}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
