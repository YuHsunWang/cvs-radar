'use client'

import { ExternalLink, ThumbsUp, TriangleAlert } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import { Product } from '@/lib/data'

type ProductDetailProps = {
  product: Product
}

export default function ProductDetail({ product }: ProductDetailProps) {
  const takes = (product.excerpt || '')
    .split('；')
    .map((part) => part.trim())
    .filter(Boolean)

  const hasEvidence = product.likes.length > 0 || product.cautions.length > 0

  return (
    <div className="sl-k">
      <div className="sl-k-tickethead">
        <div>
          <span className="sl-k-kicker">PRODUCT INFO CARD</span>
          <h3 className="sl-detail-name">{product.productName?.trim() || '商品名稱待確認'}</h3>
        </div>
        <span className="sl-k-count">{takes.length || product.nPosts} 篇心得</span>
      </div>

      <div className="sl-k-grid">
        <section className="sl-k-panel sl-k-summary">
          <h3 className="sl-k-title">
            <span>大家怎麼說</span>
            {product.reviewProvisional ? <em>暫定</em> : null}
          </h3>
          {takes.length > 0 ? (
            <div className="sl-k-takes">
              {takes.map((take, index) => (
                <p key={`${index}-${take}`} className="sl-k-sum">
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  {take}
                </p>
              ))}
            </div>
          ) : (
            <p className="sl-k-none">
              {product.reviewProvisional ? '尚未完成模型整理，請看原文' : '目前沒有可整理的作者摘要'}
            </p>
          )}
        </section>

        <section className="sl-k-panel sl-k-positive">
          <h3 className="sl-k-title">
            <ThumbsUp size={16} aria-hidden="true" />
            <span>推薦點</span>
          </h3>
          {product.likes.length > 0 ? (
            <ul className="sl-k-list">
              {product.likes.map((item) => (
                <EvidenceRow key={`+${item}`} tone="up" text={item} />
              ))}
            </ul>
          ) : (
            <p className="sl-k-none">留言沒有集中的推薦點</p>
          )}
        </section>

        <section className="sl-k-panel sl-k-negative">
          <h3 className="sl-k-title">
            <TriangleAlert size={16} aria-hidden="true" />
            <span>踩雷點</span>
          </h3>
          {product.cautions.length > 0 ? (
            <ul className="sl-k-list">
              {product.cautions.map((item) => (
                <EvidenceRow key={`-${item}`} tone="dn" text={item} />
              ))}
            </ul>
          ) : (
            <p className="sl-k-none">留言沒有集中的踩雷點</p>
          )}
        </section>
      </div>

      {hasEvidence ? <p className="sr-only">評價重點已分為推薦點與踩雷點</p> : null}

      {product.postUrls.length > 0 ? (
        <section className="sl-k-sources" aria-label="原文來源">
          <div className="sl-k-sourcehead">
            <span>原文來源</span>
            <small>可回看公開討論脈絡</small>
          </div>
          <div className="sl-k-src">
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
                <ExternalLink size={11} aria-hidden="true" />
              </a>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}

function EvidenceRow({ tone, text }: { tone: 'up' | 'dn'; text: string }) {
  const isUp = tone === 'up'
  return (
    <li className={`sl-k-row sl-k-${tone}`}>
      <b aria-hidden="true">
        {isUp ? <ThumbsUp size={13} strokeWidth={2.6} /> : <TriangleAlert size={13} strokeWidth={2.6} />}
      </b>
      <span>
        <span className="sr-only">{isUp ? '優點：' : '缺點：'}</span>
        {text}
      </span>
    </li>
  )
}
