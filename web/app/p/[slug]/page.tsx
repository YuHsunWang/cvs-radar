import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { Package } from 'lucide-react'
import ProductDetail from '@/components/ProductDetail'
import ProductPageTour from '@/components/ProductPageTour'
import { CATEGORY_ICON, scoreTone } from '@/lib/shelf-label'
import ThemeToggle from '@/components/ThemeToggle'
import {
  comprehensiveScore,
  displayBrand,
  displayCategory,
  formatDisplayDate,
  parseDataPayload,
  vegetarianShort,
  type DataPayload,
} from '@/lib/data'
import {
  pageProducts,
  productPageDescription,
  productPagePath,
  productPageTitle,
  productSlug,
  relatedProducts,
} from '@/lib/product-page'
import 'driver.js/dist/driver.css'
import '../../shelf.css'
import '../../soft-serve.css'

// Static export: every page is built ahead of time, unknown slugs are a 404.
export const dynamicParams = false

type Params = { slug: string }

async function loadPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return parseDataPayload(source)
}

async function findProduct(slug: string) {
  // Params arrive percent-encoded for non-ASCII paths in some Next versions.
  const wanted = decodeURIComponent(slug)
  const { products } = await loadPayload()
  return pageProducts(products).find((product) => productSlug(product) === wanted) ?? null
}

export async function generateStaticParams(): Promise<Params[]> {
  const { products } = await loadPayload()
  return pageProducts(products).map((product) => ({ slug: productSlug(product) }))
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const product = await findProduct((await params).slug)
  if (!product) return {}
  const title = productPageTitle(product)
  const description = productPageDescription(product)
  // Our copy resolves against metadataBase; the original only until it exists.
  const image = product.image && (product.image.localSrc ? `/${product.image.localSrc}` : product.image.imageUrl)
  return {
    title,
    description,
    alternates: { canonical: './' },
    openGraph: { title, description, url: './', type: 'article', ...(image ? { images: [{ url: image }] } : {}) },
    twitter: { card: image ? 'summary_large_image' : 'summary', title, description, ...(image ? { images: [image] } : {}) },
  }
}

export default async function ProductPage({ params }: { params: Promise<Params> }) {
  const product = await findProduct((await params).slug)
  if (!product) notFound()
  const { generatedAt, products } = await loadPayload()

  const score = comprehensiveScore(product)
  const channel = displayBrand(product.brand)
  const category = displayCategory(product.category)
  const CategoryIcon = CATEGORY_ICON[category] ?? Package
  const related = relatedProducts(product, pageProducts(products))
  const aisleCount = products.filter((other) => displayCategory(other.category) === category).length
  const aisleHref = `/?cat=${encodeURIComponent(category)}`

  return (
    <div className="sl-page ss-page">
      <header className="sl-sign">
        <div className="sl-sign-main">
          {/* The product name is this page's h1; the site name is just a sign. */}
          <p className="sl-sign-title">
            <span className="sl-logo" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M12 12l6-6" />
                <path d="M20 12a8 8 0 1 1-8-8" />
                <path d="M16 12a4 4 0 1 1-4-4" />
              </svg>
            </span>
            超商雷達
          </p>
        </div>
        <div className="ss-sign-actions">
          <ThemeToggle />
          <Link href="/" className="ss-back">
            ← 回貨架
          </Link>
        </div>
      </header>

      {/* A visitor from search has never heard of the site; say what it is before the label. */}
      <p className="pp-intro">
        超商雷達把 PTT 超商板的心得整理成分數，共收錄 {products.length} 個超商商品。這是其中一個。
      </p>
      <div className="sl-aislebar">
        <span>上架更新 {formatDisplayDate(generatedAt)}</span>
        <span className="sl-ab-sep">·</span>
        <span>分數＝綜合評分／滿分 100</span>
      </div>

      <main className="sl-shelf">
        <article className="sl-label">
          <div className="sl-row">
            <span className="sl-cat" data-cat={category} aria-hidden="true">
              <CategoryIcon size={24} strokeWidth={1.8} />
            </span>
            <span className="sr-only">分類：{category}</span>
            <div className="sl-card-main">
              <div className="sl-card-top">
                <span className="sl-channel">
                  <span className="sl-channel-dot" data-brand={channel} aria-hidden="true" />
                  {channel}
                </span>
                {product.price != null ? <span className="sl-price">${product.price}</span> : null}
                {product.vegetarian ? <span className="sl-veg">{vegetarianShort(product.vegetarian)}</span> : null}
                <span className="sl-meta">{product.nPosts} 篇心得</span>
              </div>
              <h1 className="sl-pname">{product.productName}</h1>
            </div>
            <span className={`sl-score ${scoreTone(score)}`}>
              {score === null ? '—' : score}
              <span className="sr-only">{score === null ? '樣本少，不給分' : ' 分'}</span>
            </span>
          </div>
          <div className="sl-detail sl-open">
            <div className="sl-detail-inner">
              <ProductDetail product={product} />
            </div>
          </div>
        </article>
      </main>

      {related.length > 0 ? (
        <section className="ss-section" aria-labelledby="pp-related">
          <h2 className="ss-h2" id="pp-related">
            同類高分商品
          </h2>
          <ul className="pp-rel">
            {related.map((other) => {
              const otherScore = comprehensiveScore(other)
              return (
                <li key={other.id}>
                  <Link href={productPagePath(other)} className="pp-rel-link">
                    <span className="pp-rel-text">
                      <span className="pp-rel-brand">{displayBrand(other.brand)}</span>
                      <span className="pp-rel-name">{other.productName}</span>
                    </span>
                    <span className={`sl-score pp-rel-score ${scoreTone(otherScore)}`}>
                      {otherScore}
                      <span className="sr-only"> 分</span>
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      <nav className="ss-section" aria-label="更多商品">
        <Link href={aisleHref} className="pp-all">
          看全部 {aisleCount} 個{category}類商品 →
        </Link>
      </nav>
      <ProductPageTour />
    </div>
  )
}
