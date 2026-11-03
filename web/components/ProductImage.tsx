'use client'

import { useState } from 'react'
import { isProductImage, type Product } from '@/lib/data'

type Props = {
  product: Product
}

export default function ProductImage({ product }: Props) {
  const image = isProductImage(product.image) ? product.image : null
  // A new item or metadata retries a previously broken image, even at one URL.
  const key = JSON.stringify([product.id, product.productName, image])
  const [state, setState] = useState({ key, broken: false })
  if (state.key !== key) setState({ key, broken: false })
  if (!image || (state.key === key && state.broken)) {
    return image ? <span className="sl-image-missing">圖片暫時無法載入</span> : null
  }
  const picture = (
    <img
      src={image.imageUrl}
      alt={`${product.productName?.trim() || '商品'}的商品圖片`}
      width={320}
      height={240}
      className={image.rotate ? `sl-image-full sl-rot-${image.rotate}` : 'sl-image-full'}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setState({ key, broken: true })}
      // A prerendered image can fail before hydration, when onError is not yet attached.
      ref={(element) => { if (element?.complete && !element.naturalWidth) setState({ key, broken: true }) }}
    />
  )
  return (
    <figure className="sl-product-image">
      {/* A turned photo sits in a fixed 4:3 box so its rotated corners never spill out. */}
      {image.rotate ? <span className="sl-image-box">{picture}</span> : picture}
      <figcaption>
        <a href={image.sourcePageUrl} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
          圖片來源：{image.sourceKind === 'ptt' ? 'PTT 補充圖片' : image.sourceKind === 'official_brand' ? '品牌官方' : '通路官方'}
        </a>
      </figcaption>
    </figure>
  )
}
